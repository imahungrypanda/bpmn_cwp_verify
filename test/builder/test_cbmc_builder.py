import subprocess
from pathlib import Path
from xml.etree.ElementTree import parse

import pytest
from returns.result import Failure

from bpmncwpverify.builder.cbmc_bound import get_unwinding_bound
from bpmncwpverify.builder.cbmc_builder import CbmcBuilder
from bpmncwpverify.core.accessmethods import bpmnmethods
from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.bpmn import (
    Bpmn,
    EndEvent,
    ExclusiveGatewayNode,
    Node,
    ParallelGatewayNode,
    Process,
    SequenceFlow,
    StartEvent,
    Task,
)
from bpmncwpverify.core.cwp import Cwp
from bpmncwpverify.core.error import (
    BpmnCbmcUnsupportedElementError,
    CbmcBuildError,
    NotInitializedError,
)
from bpmncwpverify.core.state import State

FACE2FACE = "test/resources/face2face/"


@pytest.fixture(scope="module")
def state() -> State:
    with open(FACE2FACE + "state.txt") as f:
        return State.from_str(f.read()).unwrap()


@pytest.fixture(scope="module")
def cwp(state: State) -> Cwp:
    return CwpXmlParser.from_xml(parse(FACE2FACE + "cwp.xml").getroot(), state).unwrap()


def _bpmn(nodes: dict[str, Node], edges: list[tuple[str, str, str]]) -> Bpmn:
    """edges are (source, target, condition)"""
    process = Process("p", "p")
    for node in nodes.values():
        process[node.id] = node
    for source, target, condition in edges:
        flow = SequenceFlow(f"{source}_{target}", "")
        flow.expression = condition
        flow.source_node, flow.target_node = nodes[source], nodes[target]
        nodes[source].add_out_flow(flow)
        nodes[target].add_in_flow(flow)
        process[flow.id] = flow
    bpmn = Bpmn()
    bpmn.processes["p"] = process
    return bpmn


def _linear() -> Bpmn:
    nodes: dict[str, Node] = {
        "s": StartEvent("s", "s", "", ""),
        "t": Task("t", "t", ""),
        "e": EndEvent("e", "e", "", ""),
    }
    return _bpmn(nodes, [("s", "t", ""), ("t", "e", "")])


def _exclusive() -> Bpmn:
    nodes: dict[str, Node] = {
        "s": StartEvent("s", "s", "", ""),
        "x": ExclusiveGatewayNode("x", "x"),
        "t": Task("t", "t", ""),
        "e1": EndEvent("e1", "e1", "", ""),
        "e2": EndEvent("e2", "e2", "", ""),
    }
    edges = [
        ("s", "x", ""),
        ("x", "e1", "terms == agreed"),
        ("x", "t", "terms != agreed"),
        ("t", "e2", ""),
    ]
    return _bpmn(nodes, edges)


def _builder(state: State, cwp: Cwp, bpmn: Bpmn) -> CbmcBuilder:
    return CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn)


def _cbmc(tmp_path: Path, source: str, unwind: int) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "model.c"
    path.write_text(source)
    return subprocess.run(
        ["cbmc", str(path), "--unwind", str(unwind), "--unwinding-assertions"],
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize("make", [_linear, _exclusive])
def test_builds_and_verifies(state: State, cwp: Cwp, tmp_path: Path, make) -> None:
    bpmn = make()
    program = _builder(state, cwp, bpmn).build_program().unwrap()
    assert program.bound == get_unwinding_bound(bpmn)
    assert program.unwind == program.bound + 1
    result = _cbmc(tmp_path, program.source, program.unwind)
    assert "VERIFICATION SUCCESSFUL" in result.stdout, result.stdout + result.stderr


def test_build_returns_the_source(state: State, cwp: Cwp) -> None:
    builder = _builder(state, cwp, _linear())
    assert builder.build().unwrap() == builder.build_program().unwrap().source


def test_declares_state(state: State, cwp: Cwp) -> None:
    source = _builder(state, cwp, _linear()).build().unwrap()
    assert "#define paymentAmount 253" in source
    assert "enum TermsType { agreed, failed, noRetry, pending };" in source
    assert "enum TermsType terms = pending;" in source
    assert "unsigned char paymentOffered = pendingPayment;" in source


def test_cwp_state_is_set_before_loop(state: State, cwp: Cwp) -> None:
    source = _builder(state, cwp, _linear()).build().unwrap()
    main = source[source.index("int main(void)") :]
    calculate = main.index("cwp_calculate_state();")
    assert calculate < main.index("for (")
    assert main.index("cwp_update_state();") > main.index("for (")
    # the loop runs no more than the bound
    assert "step < 3u" in main


def test_loop_is_not_over_transitions(state: State, cwp: Cwp) -> None:
    main = _builder(state, cwp, _exclusive()).build().unwrap().split("int main")[1]
    assert main.count("for (") == 1
    assert "while" not in main


@pytest.mark.parametrize("missing", ["state", "cwp", "bpmn"])
def test_missing_input(state: State, cwp: Cwp, missing: str) -> None:
    builder = CbmcBuilder()
    if missing != "state":
        builder.with_state(state)
    if missing != "cwp":
        builder.with_cwp(cwp)
    if missing != "bpmn":
        builder.with_bpmn(_linear())
    result = builder.build()
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, NotInitializedError)
    assert error.var_name == f"CbmcBuilder.{missing}"


def test_unsupported_element_fails(state: State, cwp: Cwp, monkeypatch) -> None:
    # Whatever the BPMN visitor cannot express comes back as its error
    nodes: dict[str, Node] = {
        "s": StartEvent("s", "s", "", ""),
        "p": ParallelGatewayNode("p", "p"),
        "e": EndEvent("e", "e", "", ""),
    }
    bpmn = _bpmn(nodes, [("s", "p", ""), ("p", "e", "")])
    from bpmncwpverify.visitors import bpmn_cbmc_visitor

    monkeypatch.setattr(
        bpmn_cbmc_visitor.CbmcGenVisitor,
        "visit_parallel_gateway",
        lambda self, gateway: self._unsupported(gateway.id, "parallel gateway")
        or False,
    )
    result = _builder(state, cwp, bpmn).build()
    assert isinstance(result.failure(), BpmnCbmcUnsupportedElementError)


def test_cwp_without_start_state_fails(state: State) -> None:
    result = _builder(state, Cwp(), _linear()).build()
    assert isinstance(result.failure(), CbmcBuildError)


@pytest.mark.parametrize("file", ["workflow.bpmn", "face2face_open.bpmn"])
def test_face2face_builds_or_reports_unsupported(
    state: State, cwp: Cwp, file: str, tmp_path: Path
) -> None:
    bpmn = bpmnmethods.from_xml(parse(FACE2FACE + file).getroot(), state).unwrap()
    result = _builder(state, cwp, bpmn).build_program()
    if isinstance(result, Failure):
        # parallel gateways may not be supported yet
        assert isinstance(result.failure(), BpmnCbmcUnsupportedElementError)
        return
    program = result.unwrap()
    assert program.bound == 25
    assert "cwp_calculate_state();" in program.source
