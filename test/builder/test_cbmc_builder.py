# type: ignore
import subprocess
from pathlib import Path

import pytest
from defusedxml import ElementTree
from returns.result import Failure, Success

from bpmncwpverify.builder.cbmc_bound import compute_bound
from bpmncwpverify.builder.cbmc_builder import BOUND_MACRO, CbmcBuilder
from bpmncwpverify.core.accessmethods import bpmnmethods, cwpmethods
from bpmncwpverify.core.bpmn import (
    Bpmn,
    EndEvent,
    ExclusiveGatewayNode,
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
from bpmncwpverify.visitors.bpmn_cbmc_visitor import STEP_FUNC
from bpmncwpverify.visitors.cwp_cbmc_visitor import CALCULATE_FUNC, UPDATE_FUNC

RESOURCES = Path(__file__).parent.parent / "resources" / "face2face"

STATE_TXT = """
enum Mode { idle busy }
const limit: byte = 5
var x: byte = 0 {0 1 2}
var flag: bool = false
var mode: Mode = idle
"""


@pytest.fixture
def state() -> State:
    return State.from_str(STATE_TXT).unwrap()


@pytest.fixture
def cwp() -> Cwp:
    cwp = Cwp()
    for name in ["Start", "Done"]:
        cwp.states[name] = CwpState(name, name)
    s = cwp.states
    init = CwpEdge("Init_Edge", "Init_Edge")
    init.expression = "x == 0"
    init.set_dest(s["Start"])
    s["Start"].in_edges.append(init)
    edge = CwpEdge("e1", "e1")
    edge.expression = "x == 1"
    edge.set_source(s["Start"])
    edge.set_dest(s["Done"])
    s["Start"].out_edges.append(edge)
    s["Done"].in_edges.append(edge)
    cwp.edges["e1"] = edge
    cwp.start_state = s["Start"]
    cwp.end_states = [s["Done"]]
    return cwp


def link(process, source, target, flow_id, expression=""):
    flow = SequenceFlow(flow_id, flow_id)
    flow.expression = expression
    flow.source_node, flow.target_node = source, target
    source.add_out_flow(flow)
    target.add_in_flow(flow)
    process[flow_id] = flow


def linear_bpmn() -> Bpmn:
    process = Process("P1", "P1")
    start = StartEvent("S", "S", "", "")
    task = Task("T", "T", "")
    end = EndEvent("E", "E", "", "")
    for node in (start, task, end):
        process[node.id] = node
    link(process, start, task, "F1")
    link(process, task, end, "F2")
    bpmn = Bpmn()
    bpmn.processes["P1"] = process
    return bpmn


def choice_bpmn() -> Bpmn:
    process = Process("P1", "P1")
    start = StartEvent("S", "S", "", "")
    gw = ExclusiveGatewayNode("G", "G")
    e1 = EndEvent("E1", "E1", "", "")
    e2 = EndEvent("E2", "E2", "", "")
    for node in (start, gw, e1, e2):
        process[node.id] = node
    link(process, start, gw, "F0")
    link(process, gw, e1, "F1", "x > 5")
    link(process, gw, e2, "F2", "x <= 5")
    bpmn = Bpmn()
    bpmn.processes["P1"] = process
    return bpmn


def build(state, cwp, bpmn):
    return CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn).build()


def compile_c(tmp_path, code):
    source = tmp_path / "model.c"
    source.write_text(code)
    return subprocess.run(
        ["cbmc", str(source), "--unwind", "50"],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("make_bpmn", [linear_bpmn, choice_bpmn])
def test_small_workflows_compile(tmp_path, state, cwp, make_bpmn):
    code = build(state, cwp, make_bpmn()).unwrap()
    result = compile_c(tmp_path, code)
    assert "PARSING ERROR" not in result.stdout + result.stderr
    assert "CONVERSION ERROR" not in result.stdout + result.stderr
    assert result.returncode in (0, 10), result.stdout + result.stderr


def test_state_is_declared(state, cwp):
    code = build(state, cwp, linear_bpmn()).unwrap()
    assert "#define limit 5" in code
    assert "typedef enum { idle, busy } Mode;" in code
    assert "unsigned char x = 0;" in code
    assert "bool flag = false;" in code
    assert "Mode mode = idle;" in code
    assert code.index("unsigned char x = 0;") < code.index("cwp_state")


def test_main_calculates_cwp_state_before_the_loop(state, cwp):
    code = build(state, cwp, linear_bpmn()).unwrap()
    main = code.split("int main(void) {")[1]
    assert main.index(f"{CALCULATE_FUNC}();") < main.index("while")
    assert f"{STEP_FUNC}();" in main
    assert f"{UPDATE_FUNC}();" in main
    assert main.count("while") == 1 and "for (" not in main


def test_bound_is_in_the_program_and_available(state, cwp):
    bpmn = linear_bpmn()
    code = build(state, cwp, bpmn).unwrap()
    bound = compute_bound(bpmn)
    assert f"#define {BOUND_MACRO} {bound}" in code
    builder = CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn)
    assert builder.bound() == Success(bound)


def test_cwp_starts_in_initial_state(tmp_path, state, cwp):
    # Asserting the CWP sits in its start state straight after the setup would
    # fail if main() did not calculate the state first.
    code = build(state, cwp, linear_bpmn()).unwrap()
    code = code.replace(f"{UPDATE_FUNC}();\n", "", 1)
    code = code.replace(
        "while (!bpmn_all_processes_done())",
        '__CPROVER_assert(cwp_state == CWP_STATE_Start, "start state");\n'
        "\twhile (!bpmn_all_processes_done())",
        1,
    )
    result = compile_c(tmp_path, code)
    assert result.returncode == 0, result.stdout


def test_missing_inputs(state, cwp):
    result = CbmcBuilder().with_cwp(cwp).with_bpmn(linear_bpmn()).build()
    assert isinstance(result.failure(), NotInitializedError)
    result = CbmcBuilder().with_state(state).with_bpmn(linear_bpmn()).build()
    assert isinstance(result.failure(), NotInitializedError)
    result = CbmcBuilder().with_state(state).with_cwp(cwp).build()
    assert isinstance(result.failure(), NotInitializedError)
    assert isinstance(CbmcBuilder().bound(), Failure)


def test_unsupported_variable_type(cwp, mocker):
    state = State.from_str(STATE_TXT).unwrap()
    mocker.patch.object(state.vars[0], "type_", "float")
    error = build(state, cwp, linear_bpmn()).failure()
    assert isinstance(error, CbmcBuildError)


def test_bpmn_visitor_error_is_returned(state, cwp, mocker):
    expected = BpmnCbmcUnsupportedElementError("G", "parallel gateway")
    mocker.patch(
        "bpmncwpverify.builder.cbmc_builder.BpmnCbmcVisitor.get_result",
        return_value=Failure(expected),
    )
    assert build(state, cwp, linear_bpmn()).failure() is expected


def load_face2face(name):
    state = State.from_str((RESOURCES / "state.txt").read_text()).unwrap()
    cwp_root = ElementTree.fromstring((RESOURCES / "cwp.xml").read_text())
    cwp = cwpmethods.CwpXmlParser.from_xml(cwp_root, state).unwrap()
    root = ElementTree.fromstring((RESOURCES / name).read_text())
    return state, cwp, bpmnmethods.from_xml(root, state).unwrap()


@pytest.mark.parametrize("name", ["workflow.bpmn", "face2face_open.bpmn"])
def test_face2face_builds_c_that_cbmc_runs(tmp_path, name):
    state, cwp, bpmn = load_face2face(name)
    result = build(state, cwp, bpmn)
    if isinstance(
        result.failure() if isinstance(result, Failure) else None,
        BpmnCbmcUnsupportedElementError,
    ):
        pytest.skip("parallel gateways are not generated yet")
    code = result.unwrap()
    source = tmp_path / "f2f.c"
    source.write_text(code)
    run = subprocess.run(
        [
            "cbmc",
            str(source),
            "--unwind",
            str(compute_bound(bpmn) + 1),
            "--unwinding-assertions",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert run.returncode == 0, run.stdout[-2000:]
