# type: ignore
import shutil
import subprocess
from pathlib import Path
from xml.etree.ElementTree import parse

import pytest
from returns.result import Failure

from bpmncwpverify.builder.cbmc_builder import CbmcBuilder
from bpmncwpverify.core.accessmethods import bpmnmethods
from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.bpmn import (
    Bpmn,
    EndEvent,
    ExclusiveGatewayNode,
    Node,
    Process,
    SequenceFlow,
    StartEvent,
    Task,
)
from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState
from bpmncwpverify.core.error import (
    BpmnCbmcUnsupportedElementError,
    CbmcBuildError,
    NotInitializedError,
)
from bpmncwpverify.core.state import State

RESOURCES = Path(__file__).parent.parent / "resources"
STATE = """
enum Mode { idle busy }
const LIMIT: int = 3
var x: int = 0
var flag: bool = false
var level: byte = 1
var mode: Mode = idle
"""

needs_cbmc = pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc missing")


def seq(src: Node, dst: Node, expr: str = "") -> None:
    flow = SequenceFlow(f"{src.id}_{dst.id}", "flow")
    flow.source_node, flow.target_node = src, dst
    flow.expression = expr
    src.add_out_flow(flow)
    dst.add_in_flow(flow)


def make_bpmn(*processes: tuple[str, list[Node]]) -> Bpmn:
    bpmn = Bpmn()
    for pid, nodes in processes:
        process = Process(pid, pid)
        for node in nodes:
            process[node.id] = node
        bpmn.processes[pid] = process
    return bpmn


def linear(pid: str = "P") -> Bpmn:
    s, t, e = (
        StartEvent("S", "S", "", ""),
        Task("T", "T", ""),
        EndEvent("E", "E", "", ""),
    )
    seq(s, t)
    seq(t, e)
    return make_bpmn((pid, [s, t, e]))


def choice() -> Bpmn:
    s, g = StartEvent("S", "S", "", ""), ExclusiveGatewayNode("G", "G")
    a, b = Task("A", "A", ""), Task("B", "B", "")
    e = EndEvent("E", "E", "", "")
    seq(s, g)
    seq(g, a, "x > 1")
    seq(g, b, "x <= 1")
    seq(a, e)
    seq(b, e)
    return make_bpmn(("P", [s, g, a, b, e]))


def two_processes() -> Bpmn:
    first, second = linear("P"), None
    s, e = StartEvent("S2", "S2", "", ""), EndEvent("E2", "E2", "", "")
    seq(s, e)
    second = make_bpmn(("Q", [s, e]))
    first.processes.update(second.processes)
    return first


def make_cwp() -> Cwp:
    cwp = Cwp()
    s0, s1 = CwpState("0", "S0"), CwpState("1", "S1")
    edge = CwpEdge("e", "e")
    edge.expression = "x > 0"
    edge.set_source(s0)
    edge.set_dest(s1)
    s0.out_edges.append(edge)
    s1.in_edges.append(edge)
    s0.init_state = True
    cwp.states = {"0": s0, "1": s1}
    cwp.edges = {"e": edge}
    cwp.start_state = s0
    cwp.end_states = [s1]
    return cwp


def builder(bpmn: Bpmn) -> CbmcBuilder:
    state = State.from_str(STATE).unwrap()
    return CbmcBuilder().with_state(state).with_cwp(make_cwp()).with_bpmn(bpmn)


def compile_c(tmp_path: Path, code: str, bound: int) -> subprocess.CompletedProcess:
    path = tmp_path / "model.c"
    path.write_text(code)
    return subprocess.run(
        ["cbmc", str(path), "--unwind", str(bound)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_state_is_declared():
    code = builder(linear()).build().unwrap()

    assert "#define LIMIT 3" in code
    assert "enum Mode { idle, busy };" in code
    assert "int x = 0;" in code
    assert "bool flag = false;" in code
    assert "unsigned char level = 1;" in code
    assert "enum Mode mode = idle;" in code


def test_cwp_and_bpmn_are_included():
    code = builder(linear()).build().unwrap()

    assert "void updateState(void)" in code
    assert "void calculateState(void)" in code
    assert "bool P_step(void)" in code
    assert "void P_init(void)" in code
    assert code.index("int x = 0;") < code.index("void updateState(void)")
    assert code.index("void updateState(void)") < code.index("int main(void)")


def test_main_covers_every_process():
    code = builder(two_processes()).build().unwrap()

    assert "P_init();" in code
    assert "Q_init();" in code
    assert "P_step() || Q_step()" in code
    assert "Q_step() || P_step()" in code


def test_unwind_bound_matches_macro():
    b = builder(linear())
    bound = b.unwind_bound().unwrap()

    assert bound > 1
    assert f"#define UNWIND_BOUND {bound}" in b.build().unwrap()


def test_unwind_bound_without_bpmn_fails():
    result = CbmcBuilder().unwind_bound()

    assert isinstance(result, Failure)
    assert isinstance(result.failure(), NotInitializedError)


@pytest.mark.parametrize("missing", ["state", "cwp", "bpmn"])
def test_missing_input_is_an_error(missing):
    full = builder(linear())
    partial = CbmcBuilder()
    for name in ("state", "cwp", "bpmn"):
        if name != missing:
            setattr(partial, name, getattr(full, name))

    result = partial.build()

    assert isinstance(result, Failure)
    assert isinstance(result.failure(), NotInitializedError)


def test_nothing_set_is_an_error():
    assert isinstance(CbmcBuilder().build(), Failure)


def test_setters_return_builder():
    b = CbmcBuilder()
    assert b.with_bpmn(linear()) is b
    assert b.with_cwp(make_cwp()) is b
    assert b.with_state(State.from_str(STATE).unwrap()) is b


def test_bpmn_without_processes_is_a_build_error():
    result = builder(Bpmn()).build()

    assert isinstance(result, Failure)
    assert isinstance(result.failure(), CbmcBuildError)


def test_unsupported_element_error_is_passed_on():
    s, t = StartEvent("S", "S", "", ""), Task("T", "T", "")
    e = EndEvent("E", "E", "", "")
    t.msg_boundary_events.append(Task.BoundaryEvent("B", "B", "", "", "T"))
    seq(s, t)
    seq(t, e)

    result = builder(make_bpmn(("P", [s, t, e]))).build()

    assert isinstance(result, Failure)
    assert isinstance(result.failure(), BpmnCbmcUnsupportedElementError)


@needs_cbmc
@pytest.mark.parametrize(
    "bpmn_factory", [linear, choice, two_processes], ids=lambda f: f.__name__
)
def test_generated_c_compiles(tmp_path, bpmn_factory):
    b = builder(bpmn_factory())
    code = b.build().unwrap()
    bound = b.unwind_bound().unwrap()

    run = compile_c(tmp_path, code, bound)

    assert "VERIFICATION SUCCESSFUL" in run.stdout, run.stdout + run.stderr


@needs_cbmc
def test_workflow_from_files_compiles(tmp_path):
    folder = RESOURCES / "face2face"
    state = State.from_str((folder / "state.txt").read_text()).unwrap()
    cwp = CwpXmlParser.from_xml(parse(folder / "cwp.xml").getroot(), state).unwrap()
    bpmn = bpmnmethods.from_xml(
        parse(folder / "workflow.bpmn").getroot(), state
    ).unwrap()
    b = CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn)

    code = b.build()
    if isinstance(code, Failure) and isinstance(
        code.failure(), BpmnCbmcUnsupportedElementError
    ):
        pytest.skip("workflow uses elements the C visitor does not support yet")
    run = compile_c(tmp_path, code.unwrap(), b.unwind_bound().unwrap())

    assert "PARSING ERROR" not in run.stdout + run.stderr, run.stderr
    assert "CONVERSION ERROR" not in run.stdout + run.stderr, run.stderr
