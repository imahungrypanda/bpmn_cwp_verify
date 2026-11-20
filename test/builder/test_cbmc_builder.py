# type: ignore
import shutil
import subprocess
from xml.etree import ElementTree as ET

import pytest
from returns.result import Failure, Success

from bpmncwpverify.builder.cbmc_builder import CbmcBuilder, CbmcProgram
from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.bpmn import (
    Bpmn,
    EndEvent,
    ExclusiveGatewayNode,
    Process,
    SequenceFlow,
    StartEvent,
    Task,
)
from bpmncwpverify.core.error import CbmcBuildError, NotInitializedError
from bpmncwpverify.core.state import State

FACE2FACE = "test/resources/face2face/"


def _node(kind, id):
    if kind == "start":
        return StartEvent(id, id, "", "")
    if kind == "end":
        return EndEvent(id, id, "", "")
    if kind == "task":
        return Task(id, id, "")
    return ExclusiveGatewayNode(id, id)


def _bpmn(nodes, edges):
    process = Process("p", "p")
    built = {id: _node(kind, id) for id, kind in nodes.items()}
    for node in built.values():
        process[node.id] = node
    for i, (src, dst) in enumerate(edges):
        flow = SequenceFlow(f"f{i}", f"f{i}")
        flow.source_node, flow.target_node = built[src], built[dst]
        built[src].add_out_flow(flow)
        built[dst].add_in_flow(flow)
        process[flow.id] = flow
    bpmn = Bpmn()
    bpmn.processes["p"] = process
    return bpmn


@pytest.fixture(scope="module")
def state():
    with open(FACE2FACE + "state.txt") as f:
        return State.from_str(f.read()).unwrap()


@pytest.fixture(scope="module")
def cwp(state):
    with open(FACE2FACE + "cwp.xml") as f:
        return CwpXmlParser.from_xml(ET.fromstring(f.read()), state).unwrap()


def _build(state, cwp, bpmn):
    return CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn).build()


WORKFLOWS = {
    "straight": (
        {"s": "start", "a": "task", "e": "end"},
        [("s", "a"), ("a", "e")],
    ),
    "just_start_end": ({"s": "start", "e": "end"}, [("s", "e")]),
    "two_tasks": (
        {"s": "start", "a": "task", "b": "task", "e": "end"},
        [("s", "a"), ("a", "b"), ("b", "e")],
    ),
}


@pytest.fixture(params=sorted(WORKFLOWS))
def program(request, state, cwp):
    nodes, edges = WORKFLOWS[request.param]
    result = _build(state, cwp, _bpmn(nodes, edges))
    assert isinstance(result, Success)
    return result.unwrap()


def test_build_returns_program_with_bound(state, cwp):
    nodes, edges = WORKFLOWS["straight"]
    program = _build(state, cwp, _bpmn(nodes, edges)).unwrap()
    assert isinstance(program, CbmcProgram)
    assert program.bound == 3
    assert program.unwind == 4
    assert str(program) == program.code
    assert "#define BOUND 3" in program.code


def test_declares_state(program):
    code = program.code
    assert "#define paymentAmount 253" in code
    assert "enum TermsType {agreed, failed, pending, noRetry};" in code
    assert "enum TermsType terms = pending;" in code
    assert "unsigned char paymentOffered = pendingPayment;" in code


def test_main_inits_cwp_before_loop(program):
    code = program.code
    main = code[code.index("int main(void)") :]
    assert main.index("cwp_init();") < main.index("for (")
    assert "cwp_update();" in main
    assert main.count("for (") == 1


@pytest.mark.skipif(shutil.which("gcc") is None, reason="needs gcc")
def test_c_compiles(program, tmp_path):
    src = tmp_path / "prog.c"
    src.write_text(program.code)
    proc = subprocess.run(
        ["gcc", "-fsyntax-only", "-Wall", str(src)], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(shutil.which("cbmc") is None, reason="needs cbmc")
def test_cbmc_runs(program, tmp_path):
    src = tmp_path / "prog.c"
    src.write_text(program.code)
    proc = subprocess.run(
        ["cbmc", str(src), "--unwind", str(program.unwind), "--unwinding-assertions"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "VERIFICATION" in proc.stdout, proc.stdout + proc.stderr


def test_unsupported_element_is_an_error(state, cwp):
    bpmn = _bpmn(
        {"s": "start", "g": "xor", "e": "end"},
        [("s", "g"), ("g", "e"), ("g", "e")],
    )
    result = _build(state, cwp, bpmn)
    assert isinstance(result, Failure)


def test_no_processes_is_an_error(state, cwp):
    result = _build(state, cwp, Bpmn())
    assert isinstance(result.failure(), CbmcBuildError)


@pytest.mark.parametrize("missing", ["state", "cwp", "bpmn"])
def test_missing_input_is_an_error(missing, state, cwp):
    nodes, edges = WORKFLOWS["straight"]
    builder = CbmcBuilder()
    if missing != "state":
        builder.with_state(state)
    if missing != "cwp":
        builder.with_cwp(cwp)
    if missing != "bpmn":
        builder.with_bpmn(_bpmn(nodes, edges))
    error = builder.build().failure()
    assert isinstance(error, NotInitializedError)
    assert error.var_name == f"CbmcBuilder.{missing}"
