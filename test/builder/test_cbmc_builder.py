# type: ignore
import subprocess
import xml.etree.ElementTree as ET

import pytest
from returns.pipeline import is_successful

from bpmncwpverify.builder.cbmc_bound import compute_bound
from bpmncwpverify.builder.cbmc_builder import (
    BOUND_MACRO,
    CbmcBuilder,
    _generate_state_c,
)
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

SIMPLE = "test/resources/simple_example/"
FACE2FACE = "test/resources/face2face/"


def _read(path):
    with open(path) as f:
        return f.read()


def _simple_state_cwp():
    state = State.from_str(_read(SIMPLE + "state.txt")).unwrap()
    cwp = CwpXmlParser.from_xml(
        ET.fromstring(_read(SIMPLE + "test_cwp.xml")), state
    ).unwrap()
    return state, cwp


def _bpmn(nodes, edges, expressions=None):
    """
    nodes: list of (kind, id) with kind in s, t, e, x.
    edges: list of (source id, target id).
    expressions: flow id -> condition, for flows out of exclusive gateways.
    """
    makers = {
        "s": lambda i: StartEvent(i, i, "", ""),
        "e": lambda i: EndEvent(i, i, "", ""),
        "t": lambda i: Task(i, i, ""),
        "x": lambda i: ExclusiveGatewayNode(i, i),
    }
    process = Process("proc", "proc")
    by_id = {}
    for kind, id in nodes:
        by_id[id] = makers[kind](id)
        process[id] = by_id[id]
    for source, target in edges:
        flow = SequenceFlow(f"{source}->{target}", "")
        flow.expression = (expressions or {}).get(flow.id, "")
        flow.source_node = by_id[source]
        flow.target_node = by_id[target]
        by_id[source].add_out_flow(flow)
        by_id[target].add_in_flow(flow)
        process[flow.id] = flow
    bpmn = Bpmn()
    bpmn.processes["proc"] = process
    return bpmn


STRAIGHT = ([("s", "s"), ("t", "t"), ("e", "e")], [("s", "t"), ("t", "e")])
LOOP = (
    [("s", "s"), ("t", "t"), ("x", "g"), ("e", "e")],
    [("s", "t"), ("t", "g"), ("g", "t"), ("g", "e")],
    {"g->t": "x <= 5", "g->e": "x > 5"},
)
BRANCH = (
    [("s", "s"), ("x", "g"), ("t", "a"), ("t", "b"), ("e", "e")],
    [("s", "g"), ("g", "a"), ("g", "b"), ("a", "e"), ("b", "e")],
    {"g->a": "x == 0", "g->b": "x != 0"},
)


def _build(workflow):
    state, cwp = _simple_state_cwp()
    builder = CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(_bpmn(*workflow))
    return builder, builder.build()


def _run_cbmc(tmp_path, c_code, unwind):
    source = tmp_path / "model.c"
    source.write_text(c_code)
    return subprocess.run(
        ["cbmc", str(source), "--unwind", str(unwind)],
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize("workflow", [STRAIGHT, LOOP, BRANCH])
def test_build_compiles_and_verifies(tmp_path, workflow):
    builder, result = _build(workflow)
    assert is_successful(result)
    unwind = builder.unwind().unwrap()
    assert unwind == compute_bound(_bpmn(*workflow)) + 1
    run = _run_cbmc(tmp_path, result.unwrap(), unwind)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "VERIFICATION SUCCESSFUL" in run.stdout


def test_cbmc_finds_no_viable_path(tmp_path):
    # x stays 0, so the only flow condition (x > 5) fails at the gateway
    workflow = (
        [("s", "s"), ("t", "t"), ("x", "g"), ("e", "e")],
        [("s", "t"), ("t", "g"), ("g", "e")],
        {"g->e": "x > 5"},
    )
    builder, result = _build(workflow)
    run = _run_cbmc(tmp_path, result.unwrap(), builder.unwind().unwrap())
    assert run.returncode != 0
    assert "No viable path to take" in run.stdout


def test_main_sets_cwp_state_before_loop():
    _, result = _build(STRAIGHT)
    c_code = result.unwrap()
    main = c_code[c_code.index("int main(void)") :]
    assert "cwp_init();" in main
    assert main.index("cwp_init();") < main.index("for (")
    assert main.index("cwp_init();") < main.index("cwp_update();")
    assert main.count("cwp_update();") == 1
    assert main.count("for (") == 1


def test_main_loop_is_bounded_by_the_bound():
    builder, result = _build(LOOP)
    bound = builder.bound().unwrap()
    c_code = result.unwrap()
    assert f"#define {BOUND_MACRO} {bound}" in c_code
    assert f"< {BOUND_MACRO};" in c_code


def test_declares_state_variables_before_use():
    _, result = _build(STRAIGHT)
    c_code = result.unwrap()
    assert c_code.index("int x = 0;") < c_code.index("cwp_compute_state")


def test_state_declarations():
    state = State.from_str(_read(FACE2FACE + "state.txt")).unwrap()
    c_code = _generate_state_c(state).unwrap()
    assert "#define paymentAmount 253" in c_code
    assert "typedef enum { agreed, failed, pending, noRetry } TermsType;" in c_code
    assert "TermsType terms = pending;" in c_code
    assert "unsigned char paymentOffered = pendingPayment;" in c_code


def test_unsupported_state_type_is_an_error():
    state = State.from_str(_read(SIMPLE + "state.txt")).unwrap()
    state.vars[0].type_ = "float"
    result = _generate_state_c(state)
    assert isinstance(result.failure(), CbmcBuildError)


def test_unsupported_bpmn_is_an_error():
    state, cwp = _simple_state_cwp()
    bpmn = _bpmn(*STRAIGHT)
    process = bpmn.processes["proc"]
    flow = SequenceFlow("back", "")
    flow.source_node = process["t"]
    flow.target_node = process["s"]
    process["s"].add_in_flow(flow)
    process["t"].add_out_flow(flow)
    result = CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn).build()
    assert not is_successful(result)


@pytest.mark.parametrize("missing", ["state", "cwp", "bpmn"])
def test_missing_input_is_an_error(missing):
    state, cwp = _simple_state_cwp()
    builder = CbmcBuilder()
    if missing != "state":
        builder.with_state(state)
    if missing != "cwp":
        builder.with_cwp(cwp)
    if missing != "bpmn":
        builder.with_bpmn(_bpmn(*STRAIGHT))
    result = builder.build()
    assert isinstance(result.failure(), NotInitializedError)


def test_bound_needs_bpmn():
    assert isinstance(CbmcBuilder().bound().failure(), NotInitializedError)
    assert isinstance(CbmcBuilder().unwind().failure(), NotInitializedError)
