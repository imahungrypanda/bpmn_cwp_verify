# type: ignore
import subprocess
from pathlib import Path

import pytest
from defusedxml import ElementTree
from returns.result import Failure, Success

from bpmncwpverify.core.accessmethods import bpmnmethods
from bpmncwpverify.core.bpmn import (
    Bpmn,
    EndEvent,
    ExclusiveGatewayNode,
    IntermediateEvent,
    MessageFlow,
    ParallelGatewayNode,
    Process,
    SequenceFlow,
    StartEvent,
    Task,
)
from bpmncwpverify.core.error import BpmnCbmcUnsupportedElementError
from bpmncwpverify.core.state import State
from bpmncwpverify.visitors.bpmn_cbmc_visitor import (
    ALL_DONE_FUNC,
    STEP_FUNC,
    BpmnCbmcVisitor,
    done_name,
    place_name,
)

RESOURCES = Path(__file__).parent.parent / "resources" / "face2face"


def link(process, source, target, flow_id, expression=""):
    flow = SequenceFlow(flow_id, flow_id)
    flow.expression = expression
    flow.source_node, flow.target_node = source, target
    source.add_out_flow(flow)
    target.add_in_flow(flow)
    process[flow_id] = flow
    return flow


def message(source, target, msg_id):
    msg = MessageFlow(msg_id, msg_id)
    msg.source_node, msg.target_node = source, target
    source.add_out_msg(msg)
    target.add_in_msg(msg)
    return msg


def make_process(pid="P1"):
    process = Process(pid, pid)
    return process


def add(process, node):
    process[node.id] = node
    return node


def gen(*processes):
    bpmn = Bpmn()
    for process in processes:
        bpmn.processes[process.id] = process
    visitor = BpmnCbmcVisitor()
    bpmn.accept(visitor)
    return visitor


def linear():
    process = make_process()
    start = add(process, StartEvent("S", "S", "", ""))
    task = add(process, Task("T", "T", ""))
    end = add(process, EndEvent("E", "E", "", ""))
    link(process, start, task, "F1")
    link(process, task, end, "F2")
    return process


def test_places_and_initial_tokens():
    code = repr(gen(linear()))
    assert f"static bool {place_name('S')} = true;" in code
    assert f"static bool {place_name('F1')} = false;" in code
    assert f"static bool {place_name('F2')} = false;" in code
    assert f"static bool {done_name('P1')} = false;" in code


def test_start_task_end_transitions():
    visitor = gen(linear())
    assert visitor.transition_count == 3
    code = repr(visitor)
    assert f"static bool enabled_0(void) {{\n\treturn ({place_name('S')});" in code
    assert f"return ({place_name('F1')});" in code
    run0 = code.split("static void run_0(void) {")[1].split("}")[0]
    assert f"CONSUME_TOKEN({place_name('S')});" in run0
    assert f"PUT_TOKEN({place_name('F1')});" in run0
    run2 = code.split("static void run_2(void) {")[1].split("}")[0]
    assert f"CONSUME_TOKEN({place_name('F2')});" in run2
    assert f"{done_name('P1')} = true;" in run2
    assert "PUT_TOKEN" not in run2


def test_step_picks_one_transition_without_looping():
    visitor = gen(linear())
    step = repr(visitor.step)
    assert step.count("nondet_uint()") == 1
    for i in range(3):
        assert f"case {i}:" in step
        assert f"__CPROVER_assume(enabled_{i}());" in step
        assert step.count(f"run_{i}();") == 1
    assert "for (" not in step and "while" not in step
    assert step.count("__CPROVER_assert(") == 1
    assert "default:" in step


def test_all_processes_done():
    p1 = linear()
    p2 = make_process("P2")
    s = add(p2, StartEvent("S2", "S2", "", ""))
    e = add(p2, EndEvent("E2", "E2", "", ""))
    link(p2, s, e, "G1")
    code = repr(gen(p1, p2))
    assert (
        f"static bool {ALL_DONE_FUNC}(void) {{\n\treturn {done_name('P1')} && {done_name('P2')};"
        in code
    )


def test_exclusive_gateway_one_transition_per_flow():
    process = make_process()
    start = add(process, StartEvent("S", "S", "", ""))
    gw = add(process, ExclusiveGatewayNode("G", "G"))
    e1 = add(process, EndEvent("E1", "E1", "", ""))
    e2 = add(process, EndEvent("E2", "E2", "", ""))
    link(process, start, gw, "F0")
    link(process, gw, e1, "F1", "x > 5")
    link(process, gw, e2, "F2", "x <= 5")
    visitor = gen(process)
    code = repr(visitor)
    # start, gateway x2, end x2
    assert visitor.transition_count == 5
    assert f"return ({place_name('F0')}) && (x > 5);" in code
    assert f"return ({place_name('F0')}) && (x <= 5);" in code
    run1 = code.split("static void run_1(void) {")[1].split("}")[0]
    assert f"PUT_TOKEN({place_name('F1')});" in run1
    assert place_name("F2") not in run1


def test_gateway_with_multiple_incoming_flows():
    process = make_process()
    start = add(process, StartEvent("S", "S", "", ""))
    t = add(process, Task("T", "T", ""))
    gw = add(process, ExclusiveGatewayNode("G", "G"))
    end = add(process, EndEvent("E", "E", "", ""))
    link(process, start, t, "F0")
    link(process, t, gw, "F1")
    link(process, gw, t, "F2", "x > 0").is_leaf = True
    link(process, gw, end, "F3", "x <= 0")
    code = repr(gen(process))
    assert f"({place_name('F0')} || {place_name('F2')})" in code


def test_intermediate_event_and_message_flows():
    p1 = make_process("P1")
    s1 = add(p1, StartEvent("S1", "S1", "", ""))
    send = add(p1, IntermediateEvent("Send", "Send", "m", "", "throw"))
    e1 = add(p1, EndEvent("E1", "E1", "", ""))
    link(p1, s1, send, "A1")
    link(p1, send, e1, "A2")
    p2 = make_process("P2")
    s2 = add(p2, StartEvent("S2", "S2", "", ""))
    catch = add(p2, IntermediateEvent("Catch", "Catch", "m", "", "catch"))
    e2 = add(p2, EndEvent("E2", "E2", "", ""))
    link(p2, s2, catch, "B1")
    link(p2, catch, e2, "B2")
    message(send, catch, "M1")

    code = repr(gen(p1, p2))
    assert f"static bool {place_name('M1')} = false;" in code
    # sender puts the message token
    send_run = [
        r
        for r in code.split("static void ")[1:]
        if f"PUT_TOKEN({place_name('M1')})" in r
    ]
    assert len(send_run) == 1
    assert f"PUT_TOKEN({place_name('A2')});" in send_run[0]
    # receiver needs both a sequence token and a message token
    assert f"return ({place_name('B1')}) && {place_name('M1')};" in code
    assert f"CONSUME_TOKEN({place_name('M1')});" in code


def test_awkward_ids_become_identifiers():
    assert place_name("Flow-1.a") == "tok_Flow_x2d_1_x2e_a"
    assert place_name("a-b") != place_name("a_b")


@pytest.mark.parametrize(
    "node, kind",
    [
        (ParallelGatewayNode("G", "G"), "parallel gateway"),
    ],
)
def test_unsupported_element_is_an_error(node, kind):
    process = make_process()
    start = add(process, StartEvent("S", "S", "", ""))
    add(process, node)
    end = add(process, EndEvent("E", "E", "", ""))
    link(process, start, node, "F1")
    link(process, node, end, "F2")
    result = gen(process).get_result()
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, BpmnCbmcUnsupportedElementError)
    assert error.element_id == "G"
    assert error.element_type == kind


def test_boundary_event_is_an_error():
    process = make_process()
    start = add(process, StartEvent("S", "S", "", ""))
    task = add(process, Task("T", "T", ""))
    end = add(process, EndEvent("E", "E", "", ""))
    boundary = Task.BoundaryEvent("B", "B", "m", "", "T")
    task.add_boundary_event(boundary)
    link(process, start, task, "F1")
    link(process, task, end, "F2")
    result = gen(process).get_result()
    assert isinstance(result, Failure)
    assert result.failure().element_id == "B"


def test_success_result_is_the_code():
    visitor = gen(linear())
    result = visitor.get_result()
    assert isinstance(result, Success)
    assert result.unwrap() == repr(visitor)


def run_cbmc(tmp_path, visitor, decls, bound, setup=""):
    c_file = tmp_path / "model.c"
    c_file.write_text(
        f"{decls}\n{visitor}\nint main(void) {{\n"
        f"  {setup}\n"
        f"  for (int i = 0; i < {bound}; i++) {{\n"
        f"    if ({ALL_DONE_FUNC}()) break;\n"
        f"    {STEP_FUNC}();\n"
        f"  }}\n"
        f'  __CPROVER_assert({ALL_DONE_FUNC}(), "finished");\n'
        f"}}\n"
    )
    return subprocess.run(
        ["cbmc", str(c_file), "--unwind", str(bound + 1), "--unwinding-assertions"],
        capture_output=True,
        text=True,
    )


def test_generated_c_verifies_with_cbmc(tmp_path):
    visitor = gen(linear())
    proc = run_cbmc(tmp_path, visitor, "", 3)
    assert "VERIFICATION SUCCESSFUL" in proc.stdout, proc.stdout


def test_generated_c_stops_at_bound(tmp_path):
    visitor = gen(linear())
    proc = run_cbmc(tmp_path, visitor, "", 2)
    assert "VERIFICATION FAILED" in proc.stdout


def test_gateway_c_verifies_with_cbmc(tmp_path):
    process = make_process()
    start = add(process, StartEvent("S", "S", "", ""))
    gw = add(process, ExclusiveGatewayNode("G", "G"))
    e1 = add(process, EndEvent("E1", "E1", "", ""))
    e2 = add(process, EndEvent("E2", "E2", "", ""))
    link(process, start, gw, "F0")
    link(process, gw, e1, "F1", "x > 5")
    link(process, gw, e2, "F2", "x <= 5")
    visitor = gen(process)
    proc = run_cbmc(tmp_path, visitor, "int x;", 3)
    assert "VERIFICATION SUCCESSFUL" in proc.stdout, proc.stdout


def test_token_collision_is_detected(tmp_path):
    visitor = gen(linear())
    assert repr(visitor).count("__CPROVER_assert(!token_collision") == 1
    # F2 is already occupied when the task puts its token there.
    setup = f"{place_name('F2')} = true;"
    proc = run_cbmc(tmp_path, visitor, "", 3, setup)
    assert "token placed on an occupied place" in proc.stdout
    assert "VERIFICATION FAILED" in proc.stdout


def load_face2face(name):
    state = State.from_str((RESOURCES / "state.txt").read_text()).unwrap()
    root = ElementTree.fromstring((RESOURCES / name).read_text())
    return bpmnmethods.from_xml(root, state).unwrap()


def test_face2face_open_is_generated_up_to_parallel_gateways():
    bpmn = load_face2face("face2face_open.bpmn")
    visitor = BpmnCbmcVisitor()
    bpmn.accept(visitor)
    # face2face has parallel gateways, which are not handled here yet.
    assert isinstance(visitor.error, BpmnCbmcUnsupportedElementError)
    assert visitor.error.element_type == "parallel gateway"
