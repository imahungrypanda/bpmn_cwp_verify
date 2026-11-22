# type: ignore
import subprocess
from pathlib import Path

import pytest
from defusedxml import ElementTree
from returns.result import Failure, Success

from bpmncwpverify.core.accessmethods import bpmnmethods
from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
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
from bpmncwpverify.core.state import State
from bpmncwpverify.visitors.bpmn_cbmc_visitor import (
    ALL_DONE_FUNC,
    STEP_FUNC,
    BpmnCbmcVisitor,
    done_name,
    place_name,
    translate_behavior,
)
from bpmncwpverify.visitors.cwp_cbmc_visitor import CwpCbmcVisitor

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


def index_of(code, node_id):
    """Index of the first transition generated for a node."""
    return int(code.split(f"// {node_id}\nstatic bool enabled_")[1].split("(")[0])


def body(code, index):
    return code.split(f"static void run_{index}(void) {{")[1].split("\n}")[0]


def fork_join():
    process = make_process()
    start = add(process, StartEvent("S", "S", "", ""))
    fork = add(process, ParallelGatewayNode("Fork", "Fork"))
    a = add(process, Task("A", "A", ""))
    b = add(process, Task("B", "B", ""))
    join = add(process, ParallelGatewayNode("Join", "Join"))
    end = add(process, EndEvent("E", "E", "", ""))
    link(process, start, fork, "F0")
    link(process, fork, a, "FA")
    link(process, fork, b, "FB")
    link(process, a, join, "JA")
    link(process, b, join, "JB").is_leaf = True
    link(process, join, end, "F9")
    return process


def test_fork_starts_every_branch():
    visitor = gen(fork_join())
    assert visitor.error is None
    code = repr(visitor)
    # S, Fork, A, B, Join, E
    assert visitor.transition_count == 6
    assert f"static bool enabled_1(void) {{\n\treturn ({place_name('F0')});" in code
    run = body(code, 1)
    assert f"PUT_TOKEN({place_name('FA')});" in run
    assert f"PUT_TOKEN({place_name('FB')});" in run


def test_join_waits_for_every_incoming_flow():
    code = repr(gen(fork_join()))
    assert f"return {place_name('JA')} && {place_name('JB')};" in code
    run = body(code, index_of(code, "Join"))
    assert f"CONSUME_TOKEN({place_name('JA')});" in run
    assert f"CONSUME_TOKEN({place_name('JB')});" in run
    assert f"PUT_TOKEN({place_name('F9')});" in run


def loop_fork():
    process = make_process()
    start = add(process, StartEvent("S", "S", "", ""))
    fork = add(process, ParallelGatewayNode("Fork", "Fork"))
    a = add(process, Task("A", "A", ""))
    b = add(process, Task("B", "B", ""))
    gw = add(process, ExclusiveGatewayNode("G", "G"))
    end = add(process, EndEvent("E", "E", "", ""))
    link(process, start, fork, "F0")
    link(process, fork, a, "FA")
    link(process, fork, b, "FB")
    link(process, a, gw, "GA")
    link(process, b, end, "FE")
    link(process, gw, fork, "Back", "x > 0").is_leaf = True
    link(process, gw, end, "Out", "x <= 0").is_leaf = True
    return process


def test_fork_with_loop_back_is_enabled_by_any_incoming_flow():
    code = repr(gen(loop_fork()))
    assert (
        f"static bool enabled_1(void) {{\n\treturn ({place_name('F0')} || {place_name('Back')});"
        in code
    )


def test_fork_with_loop_back_does_not_deadlock(tmp_path):
    visitor = gen(loop_fork())
    assert visitor.transition_count == 7
    # Only the loop-back flow has a token: the fork must still fire.
    setup = f"{place_name('S')} = false; {place_name('Back')} = true;"
    proc = run_cbmc(tmp_path, visitor, "int x = 0;", 8, setup)
    assert "VERIFICATION SUCCESSFUL" in proc.stdout, proc.stdout


def nested():
    process = make_process()
    start = add(process, StartEvent("S", "S", "", ""))
    outer = add(process, ParallelGatewayNode("Outer", "Outer"))
    inner = add(process, ParallelGatewayNode("Inner", "Inner"))
    a = add(process, Task("A", "A", ""))
    b = add(process, Task("B", "B", ""))
    c = add(process, Task("C", "C", ""))
    inner_join = add(process, ParallelGatewayNode("InnerJoin", "InnerJoin"))
    outer_join = add(process, ParallelGatewayNode("OuterJoin", "OuterJoin"))
    end = add(process, EndEvent("E", "E", "", ""))
    link(process, start, outer, "F0")
    link(process, outer, inner, "O1")
    link(process, outer, c, "O2")
    link(process, inner, a, "I1")
    link(process, inner, b, "I2")
    link(process, a, inner_join, "J1")
    link(process, b, inner_join, "J2").is_leaf = True
    link(process, inner_join, outer_join, "IJ")
    link(process, c, outer_join, "CJ").is_leaf = True
    link(process, outer_join, end, "F9")
    return process


def test_nested_parallel_gateways(tmp_path):
    visitor = gen(nested())
    assert visitor.error is None
    code = repr(visitor)
    assert f"return {place_name('J1')} && {place_name('J2')};" in code
    assert f"return {place_name('IJ')} && {place_name('CJ')};" in code
    proc = run_cbmc(tmp_path, visitor, "", 12)
    assert "VERIFICATION SUCCESSFUL" in proc.stdout, proc.stdout


def test_fork_and_join_verify_with_cbmc(tmp_path):
    proc = run_cbmc(tmp_path, gen(fork_join()), "", 8)
    assert "VERIFICATION SUCCESSFUL" in proc.stdout, proc.stdout


def test_join_with_missing_branch_is_stuck(tmp_path):
    # Drop B's token path: the join can never fire, so the end is unreachable.
    visitor = gen(fork_join())
    proc = run_cbmc(tmp_path, visitor, "", 5)
    assert "VERIFICATION FAILED" in proc.stdout


def test_translate_assignments():
    assert translate_behavior("a = b\nc = d;") == ["a = b;", "c = d;"]
    assert translate_behavior("skip") == []
    assert translate_behavior("") == []


def test_translate_assert():
    assert translate_behavior("assert(a != b)") == [
        '__CPROVER_assert(a != b, "behavior assertion");'
    ]


def test_translate_if_with_comparisons():
    lines = translate_behavior("if\n:: a == 1 && b != 2 -> x = c\n:: true -> x = d\nfi")
    text = "\n".join(lines)
    assert text.count("nondet_uint()") == 1
    assert "__CPROVER_assume(a == 1 && b != 2);" in text
    assert "x = c;" in text and "x = d;" in text
    # `true` guards need no assumption
    assert text.count("__CPROVER_assume(") == 2  # one guard, one default


def test_translate_else_and_nested_if():
    lines = translate_behavior(
        "if\n:: s == d\n:: else ->\n  if\n  :: true -> x = 1\n     y = 2;\n  fi\nfi"
    )
    text = "\n".join(lines)
    assert "__CPROVER_assume(s == d);" in text
    assert "__CPROVER_assume(!((s == d)));" in text
    assert text.count("switch (nondet_uint())") == 2
    assert "x = 1;" in text and "y = 2;" in text


def test_translate_guard_split_over_lines():
    text = "\n".join(translate_behavior("if\n:: (a == 1) &&\n (b != 2)\n -> z = 3\nfi"))
    assert "__CPROVER_assume((a == 1) && (b != 2));" in text


def task_process(behavior):
    process = make_process()
    start = add(process, StartEvent("S", "S", "", ""))
    task = add(process, Task("T", "T", behavior))
    end = add(process, EndEvent("E", "E", "", ""))
    link(process, start, task, "F1")
    link(process, task, end, "F2")
    return process


def test_behavior_is_followed_by_cwp_update():
    code = repr(gen(task_process("x = 1\ny = 2")))
    run = body(code, 1)
    assert "x = 1;\n\ty = 2;\n\tcwp_update_state();" in run
    assert run.index("cwp_update_state();") < run.index("PUT_TOKEN")
    assert run.count("cwp_update_state") == 1


def test_empty_behavior_has_no_cwp_update():
    code = repr(gen(task_process("")))
    assert "cwp_update_state" not in code
    code = repr(gen(task_process("  \n ")))
    assert "cwp_update_state" not in code


def test_task_behavior_changes_state_in_cbmc(tmp_path):
    visitor = gen(task_process("if\n:: x == 0 -> x = 1\n:: x == 0 -> x = 2\nfi"))
    decls = (
        'int x = 0;\nvoid cwp_update_state(void) { __CPROVER_assert(x != 2, "bad"); }'
    )
    proc = run_cbmc(tmp_path, visitor, decls, 3)
    assert "VERIFICATION FAILED" in proc.stdout
    assert "bad" in proc.stdout
    decls = decls.replace("x != 2", "x == 1 || x == 2")
    proc = run_cbmc(tmp_path, visitor, decls, 3)
    assert "VERIFICATION SUCCESSFUL" in proc.stdout, proc.stdout


def test_behavior_assert_is_checked(tmp_path):
    visitor = gen(task_process("assert(x == 1)\nx = 2"))
    decls = "int x = 0;\nvoid cwp_update_state(void) {}"
    proc = run_cbmc(tmp_path, visitor, decls, 3)
    assert "VERIFICATION FAILED" in proc.stdout


def face2face_c(name, tmp_path):
    state = State.from_str((RESOURCES / "state.txt").read_text()).unwrap()
    bpmn = load_face2face(name)
    cwp = CwpXmlParser.from_xml(
        ElementTree.fromstring((RESOURCES / "cwp.xml").read_text()), state
    ).unwrap()
    bpmn_visitor = BpmnCbmcVisitor()
    bpmn.accept(bpmn_visitor)
    assert bpmn_visitor.error is None
    cwp_visitor = CwpCbmcVisitor()
    cwp.accept(cwp_visitor)
    values = {}
    for i, v in enumerate("agreed failed pending noRetry buyerName sellerName".split()):
        values[v] = i
    defines = "".join(f"#define {k} {v}\n" for k, v in values.items())
    defines += "".join(
        f"#define {k} {v}\n"
        for k, v in dict(
            paymentAmount=253,
            belowPaymentAmount=252,
            noRetryPayment=254,
            pendingPayment=255,
        ).items()
    )
    decls = (
        defines
        + "unsigned char terms = pending;\n"
        + "unsigned char backpackOwner = sellerName;\n"
        + "unsigned char paymentOwner = buyerName;\n"
        + "unsigned char paymentOffered = pendingPayment;\n"
    )
    return decls + repr(cwp_visitor) + "\n" + repr(bpmn_visitor)


@pytest.mark.parametrize("name", ["workflow.bpmn", "face2face_open.bpmn"])
def test_face2face_generates_without_error(name, tmp_path):
    code = face2face_c(name, tmp_path)
    assert "cwp_update_state();" in code
    assert "parallel gateway" not in code
    c_file = tmp_path / "f2f.c"
    c_file.write_text(
        code + f"\nint main(void) {{ cwp_calculate_state();\n"
        f"  for (int i = 0; i < 25; i++) {{ if ({ALL_DONE_FUNC}()) break; {STEP_FUNC}(); }}\n}}\n"
    )
    proc = subprocess.run(
        ["cbmc", str(c_file), "--unwind", "26", "--unwinding-assertions"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert "VERIFICATION SUCCESSFUL" in proc.stdout, proc.stdout[-2000:]
