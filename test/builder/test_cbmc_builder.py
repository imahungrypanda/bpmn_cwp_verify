import shutil
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from returns.result import Failure, Success

from bpmncwpverify.builder.cbmc_builder import CbmcBuilder, CbmcProgram
from bpmncwpverify.core.accessmethods import bpmnmethods
from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.bpmn import (
    Bpmn,
    EndEvent,
    ExclusiveGatewayNode,
    ParallelGatewayNode,
    Process,
    SequenceFlow,
    StartEvent,
    Task,
)
from bpmncwpverify.core.error import CbmcBuildError, NotInitializedError
from bpmncwpverify.core.state import State

FACE2FACE = Path(__file__).parent.parent / "resources" / "face2face"
HAS_CBMC = shutil.which("cbmc") is not None


def _load(bpmn_name: str):
    state = State.from_str((FACE2FACE / "state.txt").read_text()).unwrap()
    cwp = CwpXmlParser.from_xml(
        ET.fromstring((FACE2FACE / "cwp.xml").read_text()), state
    ).unwrap()
    bpmn = bpmnmethods.from_xml(
        ET.fromstring((FACE2FACE / bpmn_name).read_text()), state
    ).unwrap()
    return state, cwp, bpmn


def _build(bpmn_name: str) -> CbmcProgram:
    state, cwp, bpmn = _load(bpmn_name)
    result = CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn).build()
    assert isinstance(result, Success)
    return result.unwrap()


def _run_cbmc(tmp_path: Path, program: CbmcProgram) -> subprocess.CompletedProcess[str]:
    src = tmp_path / "model.c"
    src.write_text(program.source)
    return subprocess.run(
        ["cbmc", str(src), "--unwind", str(program.unwind), "--unwinding-assertions"],
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.mark.parametrize("name", ["workflow.bpmn", "face2face_open.bpmn"])
def test_build_face2face(name):
    program = _build(name)
    assert program.bound == 25
    assert program.unwind == 26
    assert "int main(void)" in program.source
    assert "#define paymentAmount 253" in program.source
    assert "unsigned char paymentOffered = pendingPayment;" in program.source
    assert "int terms = pending;" in program.source


def test_main_calculates_state_before_loop():
    source = _build("workflow.bpmn").source
    main = source[source.index("int main(void)") :]
    assert main.index("cwp_calculate_state();") < main.index("for (")
    assert main.index("for (") < main.index("bpmn_step();")
    assert "pass < BOUND" in main
    assert "#define BOUND 25u" in source


@pytest.mark.skipif(not HAS_CBMC, reason="cbmc is not installed")
@pytest.mark.parametrize("name", ["workflow.bpmn", "face2face_open.bpmn"])
def test_face2face_compiles_in_cbmc(tmp_path, name):
    result = _run_cbmc(tmp_path, _build(name))
    assert "PARSING ERROR" not in result.stdout + result.stderr
    assert "CONVERSION ERROR" not in result.stdout + result.stderr
    assert "VERIFICATION" in result.stdout


@pytest.mark.skipif(not HAS_CBMC, reason="cbmc is not installed")
def test_gcc_free_syntax_of_state_declarations(tmp_path):
    program = _build("workflow.bpmn")
    head = program.source[: program.source.index("//**********CWP")]
    src = tmp_path / "decls.c"
    src.write_text(head + "int main(void){return 0;}\n")
    result = subprocess.run(["cbmc", str(src)], capture_output=True, text=True)
    assert "VERIFICATION SUCCESSFUL" in result.stdout


def test_missing_inputs():
    state, cwp, bpmn = _load("workflow.bpmn")
    for builder in (
        CbmcBuilder().with_cwp(cwp).with_bpmn(bpmn),
        CbmcBuilder().with_state(state).with_bpmn(bpmn),
        CbmcBuilder().with_state(state).with_cwp(cwp),
        CbmcBuilder(),
    ):
        result = builder.build()
        assert isinstance(result, Failure)
        assert isinstance(result.failure(), NotInitializedError)


def test_unsupported_variable_type():
    state, cwp, bpmn = _load("workflow.bpmn")
    state.vars[0].type_ = "mystery"
    result = CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn).build()
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), CbmcBuildError)


def _small_bpmn(kind: str) -> Bpmn:
    process = Process("p", "p")
    nodes = {
        "s": StartEvent("s", "s", "", ""),
        "a": Task("a", "a", ""),
        "b": Task("b", "b", ""),
        "e": EndEvent("e", "e", "", ""),
    }
    if kind == "linear":
        edges = [("s", "a"), ("a", "b"), ("b", "e")]
    elif kind == "xor":
        nodes["g"] = ExclusiveGatewayNode("g", "g")
        edges = [("s", "g"), ("g", "a"), ("g", "b"), ("a", "e"), ("b", "e")]
    else:
        nodes["f"] = ParallelGatewayNode("f", "f")
        nodes["j"] = ParallelGatewayNode("j", "j")
        edges = [("s", "f"), ("f", "a"), ("f", "b"), ("a", "j"), ("b", "j"), ("j", "e")]
    for name, node in nodes.items():
        process[name] = node
    for i, (src, dst) in enumerate(edges):
        flow = SequenceFlow(f"f{i}", "")
        flow.source_node = nodes[src]
        flow.target_node = nodes[dst]
        nodes[src].add_out_flow(flow)
        nodes[dst].add_in_flow(flow)
        process[flow.id] = flow
    bpmn = Bpmn()
    bpmn.processes["p"] = process
    return bpmn


@pytest.mark.skipif(not HAS_CBMC, reason="cbmc is not installed")
@pytest.mark.parametrize("kind", ["linear", "xor", "parallel"])
def test_small_workflows_compile_and_verify(tmp_path, kind):
    state, cwp, _ = _load("workflow.bpmn")
    result = (
        CbmcBuilder()
        .with_state(state)
        .with_cwp(cwp)
        .with_bpmn(_small_bpmn(kind))
        .build()
    )
    program = result.unwrap()
    assert program.bound > 0
    out = _run_cbmc(tmp_path, program)
    assert "VERIFICATION SUCCESSFUL" in out.stdout, out.stdout + out.stderr
