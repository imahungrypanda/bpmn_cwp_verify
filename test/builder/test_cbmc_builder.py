# type: ignore
import subprocess
import xml.etree.ElementTree as ET

import pytest
from returns.pipeline import is_successful

from bpmncwpverify.builder.cbmc_bound import compute_unwind_bound
from bpmncwpverify.builder.cbmc_builder import CbmcBuilder
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

SIMPLE = "./test/resources/simple_example/"
FACE2FACE = "./test/resources/face2face/"


def make_bpmn(nodes, edges):
    process = Process("p", "p")
    made = {}
    for id, kind in nodes.items():
        if kind == "start":
            node = StartEvent(id, id, "", "")
        elif kind == "end":
            node = EndEvent(id, id, "", "")
        elif kind == "task":
            node = Task(id, id, "")
        elif kind == "xor":
            node = ExclusiveGatewayNode(id, id)
        else:
            node = ParallelGatewayNode(id, id)
        made[id] = node
        process[id] = node
    for source, target in edges:
        flow = SequenceFlow(f"{source}_{target}", "")
        flow.source_node = made[source]
        flow.target_node = made[target]
        made[source].add_out_flow(flow)
        made[target].add_in_flow(flow)
        process[flow.id] = flow
    bpmn = Bpmn()
    bpmn.processes[process.id] = process
    return bpmn


def load(dir, cwp_file, bpmn_file):
    with open(dir + "state.txt") as f:
        state = State.from_str(f.read()).unwrap()
    cwp = CwpXmlParser.from_xml(ET.parse(dir + cwp_file).getroot(), state).unwrap()
    bpmn = bpmnmethods.from_xml(ET.parse(dir + bpmn_file).getroot(), state).unwrap()
    return state, cwp, bpmn


@pytest.fixture
def simple():
    return load(SIMPLE, "test_cwp.xml", "simple_open.bpmn")


def build(state, cwp, bpmn):
    return CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn).build()


def check_compiles(tmp_path, c):
    src = tmp_path / "model.c"
    src.write_text(c)
    # gcc doesn't know CBMC's builtins
    subprocess.run(
        [
            "gcc",
            "-fsyntax-only",
            "-D__CPROVER_assert(c,m)=",
            "-D__CPROVER_assume(c)=",
            str(src),
        ],
        check=True,
    )


def test_builds_and_compiles(tmp_path, simple):
    result = build(*simple)
    assert is_successful(result)
    c = result.unwrap()
    check_compiles(tmp_path, c)
    assert "int x = 0;" in c
    assert "int main(void)" in c


def test_main_calculates_cwp_state_before_loop(simple):
    c = build(*simple).unwrap()
    main = c[c.index("int main(void)") :]
    assert main.index("cwp_calculate_state();") < main.index("for (")
    assert main.index("for (") < main.index("cwp_update_state();")


def test_loop_runs_up_to_bound(simple):
    _, _, bpmn = simple
    c = build(*simple).unwrap()
    assert f"pass < {compute_unwind_bound(bpmn)};" in c


def test_unwind_is_bound_plus_one(simple):
    _, cwp, bpmn = simple
    builder = CbmcBuilder().with_bpmn(bpmn)
    assert builder.unwind().unwrap() == compute_unwind_bound(bpmn) + 1


def test_constants_and_enums_declared(tmp_path):
    with open(FACE2FACE + "state.txt") as f:
        state = State.from_str(f.read()).unwrap()
    bpmn = make_bpmn({"s": "start", "t": "task", "e": "end"}, [("s", "t"), ("t", "e")])
    cwp = load(SIMPLE, "test_cwp.xml", "simple_open.bpmn")[1]
    # the simple CWP doesn't use these variables, only declarations matter here
    c = build(state, cwp, bpmn).unwrap()
    assert "#define paymentAmount 253" in c
    assert "enum TermsType {" in c
    assert "enum TermsType terms = pending;" in c
    assert "unsigned char paymentOffered = pendingPayment;" in c


def test_small_workflow_verifies_with_cbmc(tmp_path, simple):
    c = build(*simple).unwrap()
    unwind = CbmcBuilder().with_bpmn(simple[2]).unwind().unwrap()
    src = tmp_path / "model.c"
    src.write_text(c)
    run = subprocess.run(
        ["cbmc", str(src), "--unwind", str(unwind)], capture_output=True, text=True
    )
    assert "VERIFICATION SUCCESSFUL" in run.stdout


def test_exclusive_gateway_without_condition_fails(simple):
    state, cwp, _ = simple
    bpmn = make_bpmn(
        {"s": "start", "x": "xor", "a": "end", "b": "end"},
        [("s", "x"), ("x", "a"), ("x", "b")],
    )
    result = build(state, cwp, bpmn)
    assert not is_successful(result)
    assert isinstance(result.failure(), CbmcBuildError)


def test_missing_inputs_give_errors(simple):
    state, cwp, bpmn = simple
    for builder in (
        CbmcBuilder().with_cwp(cwp).with_bpmn(bpmn),
        CbmcBuilder().with_state(state).with_bpmn(bpmn),
        CbmcBuilder().with_state(state).with_cwp(cwp),
    ):
        result = builder.build()
        assert not is_successful(result)
        assert isinstance(result.failure(), NotInitializedError)


def test_unwind_without_bpmn_is_error():
    result = CbmcBuilder().unwind()
    assert isinstance(result.failure(), NotInitializedError)
