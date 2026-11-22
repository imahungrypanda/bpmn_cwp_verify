import shutil
import subprocess

import pytest

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
from bpmncwpverify.visitors.bpmn_cbmc_visitor import CbmcBpmnGenVisitor
from bpmncwpverify.visitors.cwp_cbmc_visitor import UPDATE_FUNC


def seq(src, dst, id, expression=""):
    flow = SequenceFlow(id, id)
    flow.expression = expression
    flow.source_node = src
    flow.target_node = dst
    src.add_out_flow(flow)
    dst.add_in_flow(flow)
    return flow


def msg(src, dst, id):
    flow = MessageFlow(id, id)
    flow.source_node = src
    flow.target_node = dst
    src.add_out_msg(flow)
    dst.add_in_msg(flow)
    return flow


def start(id="S"):
    return StartEvent(id, id, "", "")


def end(id="E"):
    return EndEvent(id, id, "", "")


def process(id, *nodes):
    proc = Process(id, id)
    for node in nodes:
        proc[node.id] = node
    return proc


def bpmn_of(*processes):
    bpmn = Bpmn()
    for proc in processes:
        bpmn.processes[proc.id] = proc
    return bpmn


def generate(*processes):
    visitor = CbmcBpmnGenVisitor()
    bpmn_of(*processes).accept(visitor)
    return visitor


def linear():
    s, t, e = start(), Task("T", "T", ""), end()
    seq(s, t, "f1")
    seq(t, e, "f2")
    return process("P", s, t, e)


def assert_unsupported(*processes):
    with pytest.raises(Exception) as exc:
        generate(*processes)
    assert isinstance(exc.value.args[0], BpmnCbmcUnsupportedElementError)
    return exc.value.args[0]


def test_places_for_start_events_and_flows():
    v = generate(linear())
    defs = str(v.defs)
    for place in ["tok_S", "tok_f1", "tok_f2", "ended_P"]:
        assert f"static bool {place} = false;" in defs
    assert str(v.init) == "tok_S = true;\n"


def test_each_element_is_a_transition():
    v = generate(linear())
    assert [t.label for t in v.transitions] == [
        "start event S",
        "task T",
        "end event E",
    ]
    assert v.transitions[0].enabled == "(tok_S)"
    assert v.transitions[1].enabled == "(tok_f1)"
    assert v.transitions[2].enabled == "(tok_f2)"


def test_transition_body_clears_in_checks_once_and_sets_out():
    v = generate(linear())
    assert v.transitions[1].body == [
        "tok_f1 = false;",
        '__CPROVER_assert(!(tok_f2), "Attempting to place token in already-occupied place");',
        "tok_f2 = true;",
    ]


def test_end_event_ends_its_process():
    v = generate(linear())
    assert v.transitions[2].body == ["tok_f2 = false;", "ended_P = true;"]
    assert v.all_ended == "ended_P"


def test_all_ended_covers_every_process():
    s1, e1 = start("S1"), end("E1")
    seq(s1, e1, "a")
    s2, e2 = start("S2"), end("E2")
    seq(s2, e2, "b")
    v = generate(process("P1", s1, e1), process("P2", s2, e2))
    assert v.all_ended == "ended_P1 && ended_P2"


def test_task_with_two_incoming_flows_is_enabled_by_either():
    s1, s2, t, e = start("S1"), start("S2"), Task("T", "T", ""), end()
    seq(s1, t, "a")
    seq(s2, t, "b")
    seq(t, e, "c")
    v = generate(process("P", s1, s2, t, e))
    task = next(x for x in v.transitions if x.label == "task T")
    assert task.enabled == "(tok_a || tok_b)"
    assert "tok_a = false;" in task.body and "tok_b = false;" in task.body


def test_intermediate_event():
    s, ev, e = start(), IntermediateEvent("I", "I", "", "", "catch"), end()
    seq(s, ev, "a")
    seq(ev, e, "b")
    v = generate(process("P", s, ev, e))
    assert v.transitions[1].label == "intermediate event I"
    assert v.transitions[1].body[-1] == "tok_b = true;"


def test_exclusive_gateway_has_one_transition_per_flow():
    s, g = start(), ExclusiveGatewayNode("G", "G")
    e1, e2 = end("E1"), end("E2")
    seq(s, g, "in")
    seq(g, e1, "x", "a > 1")
    seq(g, e2, "y", "a <= 1")
    v = generate(process("P", s, g, e1, e2))
    gate = [t for t in v.transitions if t.label.startswith("exclusive")]
    assert [t.enabled for t in gate] == [
        "(tok_in) && (a > 1)",
        "(tok_in) && (a <= 1)",
    ]
    assert "tok_x = true;" in gate[0].body and "tok_y = true;" not in gate[0].body
    assert "tok_y = true;" in gate[1].body and "tok_x = true;" not in gate[1].body


def test_exclusive_gateway_merge_without_expression():
    s1, s2, g, e = start("S1"), start("S2"), ExclusiveGatewayNode("G", "G"), end()
    seq(s1, g, "a")
    seq(s2, g, "b")
    seq(g, e, "c")
    v = generate(process("P", s1, s2, g, e))
    gate = next(t for t in v.transitions if t.label.startswith("exclusive"))
    assert gate.enabled == "(tok_a || tok_b)"


def test_multiline_expression_is_flattened():
    s, g, e1, e2 = start(), ExclusiveGatewayNode("G", "G"), end("E1"), end("E2")
    seq(s, g, "in")
    seq(g, e1, "x", "a > 1\n&& b")
    seq(g, e2, "y", "!(a > 1)")
    v = generate(process("P", s, g, e1, e2))
    assert "(a > 1 && b)" in v.transitions[1].enabled


def test_message_flows():
    s1, t1, e1 = start("S1"), Task("T1", "T1", ""), end("E1")
    seq(s1, t1, "a")
    seq(t1, e1, "b")
    s2, t2, e2 = start("S2"), Task("T2", "T2", ""), end("E2")
    seq(s2, t2, "c")
    seq(t2, e2, "d")
    msg(t1, t2, "m")
    v = generate(process("P1", s1, t1, e1), process("P2", s2, t2, e2))
    send = next(t for t in v.transitions if t.label == "task T1")
    recv = next(t for t in v.transitions if t.label == "task T2")
    assert "static bool msg_m = false;" in str(v.defs)
    assert "msg_m = true;" in send.body
    assert recv.enabled == "(tok_c) && (msg_m)"
    assert "msg_m = false;" in recv.body


def test_step_picks_one_transition_without_looping():
    v = generate(linear())
    step = str(v.step)
    assert step.count("nondet_uint()") == 1
    assert "__CPROVER_assume(transition < 3u);" in step
    assert step.count("switch (") == 1
    for kw in ["for (", "while (", "do {"]:
        assert kw not in step
    # each case assumes its own enable condition
    assert step.count("__CPROVER_assume(") == 4
    assert step.count("break;") == 3
    assert "case 2: /* end event E */" in step


def test_shared_node_is_visited_once():
    s, g, e = start(), ExclusiveGatewayNode("G", "G"), end()
    seq(s, g, "a")
    seq(g, e, "b")
    v = generate(process("P", s, g, e))
    assert len(v.transitions) == 3
    # visiting the same node again adds nothing
    n = len(v.transitions)
    v.visit_end_event(e)
    assert len(v.transitions) == n


def test_boundary_event_is_unsupported():
    s, t, e = start(), Task("T", "T", ""), end()
    seq(s, t, "a")
    seq(t, e, "b")
    t.add_boundary_event(Task.BoundaryEvent("B", "B", "", "", "T"))
    assert assert_unsupported(process("P", s, t, e)).element_id == "T"


def test_boundary_event_visit_is_unsupported():
    with pytest.raises(Exception) as exc:
        CbmcBpmnGenVisitor().visit_boundary_event(
            Task.BoundaryEvent("B", "B", "", "", "T")
        )
    assert exc.value.args[0].element_id == "B"


def test_exclusive_gateway_flow_without_condition_is_unsupported():
    s, g, e1, e2 = start(), ExclusiveGatewayNode("G", "G"), end("E1"), end("E2")
    seq(s, g, "in")
    seq(g, e1, "x", "a > 1")
    seq(g, e2, "y")
    assert assert_unsupported(process("P", s, g, e1, e2)).element_id == "y"


def test_exclusive_gateway_without_out_flow_is_unsupported():
    s, g = start(), ExclusiveGatewayNode("G", "G")
    seq(s, g, "in")
    assert assert_unsupported(process("P", s, g)).element_id == "G"


def test_node_without_incoming_flow_is_unsupported():
    with pytest.raises(Exception) as exc:
        CbmcBpmnGenVisitor().visit_task(Task("T", "T", ""))
    assert isinstance(exc.value.args[0], BpmnCbmcUnsupportedElementError)
    assert exc.value.args[0].element_id == "T"


def test_end_event_with_outgoing_flow_is_unsupported():
    s, e, t = start(), end(), Task("T", "T", "")
    seq(s, e, "a")
    seq(e, t, "b")
    assert assert_unsupported(process("P", s, e, t)).element_id == "E"


def test_bad_identifier_is_unsupported():
    s, e = start("S-1"), end()
    seq(s, e, "a")
    assert assert_unsupported(process("P", s, e)).element_id == "S-1"


def test_gateway_with_messages_is_unsupported():
    s, g, e, o = start(), ExclusiveGatewayNode("G", "G"), end(), end("O")
    seq(s, g, "a")
    seq(g, e, "b")
    msg(g, o, "m")
    assert assert_unsupported(process("P", s, g, e), process("Q", o)).element_id == "G"


def test_no_transitions_assumes_false():
    v = generate(process("P"))
    assert str(v.step) == "__CPROVER_assume(false);\n"
    assert v.all_ended == "ended_P"


def test_no_processes_all_ended_is_true():
    assert generate().all_ended == "true"


def test_repr_contains_every_part():
    v = generate(linear())
    text = repr(v)
    assert str(v.defs) in text and str(v.init) in text and str(v.step) in text


@pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc not installed")
@pytest.mark.parametrize("bound,expected_ok", [(4, True), (2, False)])
def test_generated_c_runs_in_cbmc(tmp_path, bound, expected_ok):
    s, g = start(), ExclusiveGatewayNode("G", "G")
    t, e1, e2 = Task("T", "T", ""), end("E1"), end("E2")
    seq(s, g, "in")
    seq(g, t, "x", "a > 1")
    seq(g, e2, "y", "a <= 1")
    seq(t, e1, "z")
    v = generate(process("P", s, g, t, e1, e2))
    program = (
        f"{v.defs}\nint a;\nint main(void) {{\n{v.init}"
        f"unsigned int pass = 0;\nwhile (!({v.all_ended})) {{\n"
        f'__CPROVER_assert(pass < {bound}u, "bound");\npass++;\n{v.step}}}\nreturn 0;\n}}\n'
    )
    src = tmp_path / "w.c"
    src.write_text(program)
    result = subprocess.run(
        ["cbmc", str(src), "--unwind", str(bound + 1)],
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) == expected_ok, result.stdout


def enabled_of(v, label_part):
    return next(t for t in v.transitions if label_part in t.label).enabled


def body_of(v, label_part):
    return next(t for t in v.transitions if label_part in t.label).body


def fork_join():
    s, f, a, b = (
        start(),
        ParallelGatewayNode("F", "F"),
        Task("A", "A", ""),
        Task("B", "B", ""),
    )
    j, e = ParallelGatewayNode("J", "J"), end()
    seq(s, f, "i")
    seq(f, a, "fa")
    seq(f, b, "fb")
    seq(a, j, "aj")
    seq(b, j, "bj")
    seq(j, e, "je")
    return process("P", s, f, a, b, j, e)


def test_fork_starts_every_branch():
    v = generate(fork_join())
    assert "fork" in next(t.label for t in v.transitions if "F" in t.label)
    assert enabled_of(v, "(fork)") == "(tok_i)"
    body = body_of(v, "(fork)")
    assert "tok_i = false;" in body
    assert "tok_fa = true;" in body and "tok_fb = true;" in body


def test_join_waits_for_every_incoming_flow():
    v = generate(fork_join())
    assert enabled_of(v, "(join)") == "(tok_aj && tok_bj)"
    body = body_of(v, "(join)")
    assert "tok_aj = false;" in body and "tok_bj = false;" in body
    assert "tok_je = true;" in body


def test_fork_with_loop_back_is_enabled_by_any_incoming_flow():
    s, f, a, g, e = (
        start(),
        ParallelGatewayNode("F", "F"),
        Task("A", "A", ""),
        ExclusiveGatewayNode("G", "G"),
        end(),
    )
    b, j = Task("B", "B", ""), ParallelGatewayNode("J", "J")
    seq(s, f, "i")
    seq(g, f, "back", "x < 1")
    seq(f, a, "fa")
    seq(f, b, "fb")
    seq(a, j, "aj")
    seq(b, j, "bj")
    seq(j, g, "jg")
    seq(g, e, "out", "x >= 1")
    v = generate(process("P", s, f, a, b, j, g, e))
    assert enabled_of(v, "F (fork)") == "(tok_i || tok_back)"
    assert enabled_of(v, "J (join)") == "(tok_aj && tok_bj)"


def test_nested_parallel_gateways():
    s, f1, f2 = (
        start(),
        ParallelGatewayNode("F1", "F1"),
        ParallelGatewayNode("F2", "F2"),
    )
    a, b, c = Task("A", "A", ""), Task("B", "B", ""), Task("C", "C", "")
    j2, j1, e = ParallelGatewayNode("J2", "J2"), ParallelGatewayNode("J1", "J1"), end()
    seq(s, f1, "i")
    seq(f1, f2, "f1f2")
    seq(f1, c, "f1c")
    seq(f2, a, "f2a")
    seq(f2, b, "f2b")
    seq(a, j2, "aj2")
    seq(b, j2, "bj2")
    seq(j2, j1, "j2j1")
    seq(c, j1, "cj1")
    seq(j1, e, "out")
    v = generate(process("P", s, f1, f2, a, b, c, j2, j1, e))
    assert len(v.transitions) == 9
    assert enabled_of(v, "F1 (fork)") == "(tok_i)"
    assert enabled_of(v, "F2 (fork)") == "(tok_f1f2)"
    assert enabled_of(v, "J2 (join)") == "(tok_aj2 && tok_bj2)"
    assert enabled_of(v, "J1 (join)") == "(tok_j2j1 && tok_cj1)"
    assert "tok_f2a = true;" in body_of(v, "F2 (fork)")


def test_parallel_gateway_without_out_flow_is_unsupported():
    s, g = start(), ParallelGatewayNode("G", "G")
    seq(s, g, "a")
    assert assert_unsupported(process("P", s, g)).element_id == "G"


def test_parallel_gateway_with_messages_is_unsupported():
    s, g, e, o = start(), ParallelGatewayNode("G", "G"), end(), start("O")
    seq(s, g, "a")
    seq(g, e, "b")
    msg(g, o, "m")
    assert assert_unsupported(process("P", s, g, e), process("Q", o)).element_id == "G"


def behavior_body(code):
    s, t, e = start(), Task("T", "T", code), end()
    seq(s, t, "a")
    seq(t, e, "b")
    v = generate(process("P", s, t, e))
    return body_of(v, "task T")


def test_empty_behavior_has_no_update():
    assert not any(UPDATE_FUNC in x for x in behavior_body(""))


def test_assignment_behavior_then_cwp_update():
    body = behavior_body("a = b\npaymentOwner = sellerName")
    assert body.index("a = b;") < body.index("paymentOwner = sellerName;")
    assert (
        body[body.index("paymentOwner = sellerName;") + 1 :][0] == f"{UPDATE_FUNC}();"
    )
    # behavior runs after the token is cleared and before the output is set
    assert body.index("tok_a = false;") < body.index("a = b;")
    assert body.index(f"{UPDATE_FUNC}();") < body.index("tok_b = true;")


def test_semicolons_and_skip():
    body = behavior_body("x = 1; y = 2\nskip")
    assert "x = 1;" in body and "y = 2;" in body and "skip;" not in body


def test_if_behavior_compares_and_assigns():
    body = "\n".join(
        behavior_body("if\n:: x == 1 -> y = 2\n:: x != 1 && true -> y = 3\nfi")
    )
    assert "__CPROVER_assume((x == 1));" in body
    assert "__CPROVER_assume((x != 1 && true));" in body
    assert "y = 2;" in body and "y = 3;" in body
    assert "nondet_uint()" in body and "< 2u" in body
    assert "->" not in body


def test_if_with_else_and_multiline_option():
    body = "\n".join(
        behavior_body("if\n:: x > 1 ->\n y = 1\n z = 1\n:: else -> y = 0\nfi")
    )
    assert "__CPROVER_assume(!((x > 1)));" in body
    assert "y = 1;" in body and "z = 1;" in body and "y = 0;" in body


def test_nested_if_uses_distinct_choices():
    body = "\n".join(behavior_body("if\n:: true -> if\n:: true -> y = 1\nfi\nfi"))
    assert "choice_0" in body and "choice_1" in body


def test_behavior_assert():
    body = "\n".join(behavior_body("assert(x == 1)"))
    assert "__CPROVER_assert((x == 1)" in body


@pytest.mark.parametrize(
    "code", ["if\n:: true y = 1\nfi", "if\n:: true -> y = 1", "fi", ":: true -> y = 1"]
)
def test_malformed_behavior_is_unsupported(code):
    s, t, e = start(), Task("T", "T", code), end()
    seq(s, t, "a")
    seq(t, e, "b")
    assert assert_unsupported(process("P", s, t, e)).element_id == "T"


def run_cbmc(tmp_path, v, decls, bound, extra_main=""):
    program = (
        f"{v.defs}\n{decls}\nstatic void {UPDATE_FUNC}(void) {{}}\n"
        f"int main(void) {{\n{v.init}"
        f"unsigned int pass = 0;\nwhile (!({v.all_ended})) {{\n"
        f'__CPROVER_assert(pass < {bound}u, "bound");\npass++;\n{v.step}}}\n'
        f"{extra_main}return 0;\n}}\n"
    )
    src = tmp_path / "w.c"
    src.write_text(program)
    return subprocess.run(
        ["cbmc", str(src), "--unwind", str(bound + 1)], capture_output=True, text=True
    )


@pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc not installed")
def test_fork_join_runs_in_cbmc(tmp_path):
    v = generate(fork_join())
    # start, fork, A, B, join, end
    assert run_cbmc(tmp_path, v, "", 6).returncode == 0
    assert run_cbmc(tmp_path, v, "", 5).returncode != 0


@pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc not installed")
def test_behavior_runs_in_cbmc(tmp_path):
    s, t, e = (
        start(),
        Task("T", "T", "if\n:: true -> x = 1\n:: true -> x = 2\nfi"),
        end(),
    )
    seq(s, t, "a")
    seq(t, e, "b")
    v = generate(process("P", s, t, e))
    decls = "static int x = 0;"
    assert (
        run_cbmc(
            tmp_path, v, decls, 3, '__CPROVER_assert(x == 1 || x == 2, "x");\n'
        ).returncode
        == 0
    )
    assert (
        run_cbmc(tmp_path, v, decls, 3, '__CPROVER_assert(x == 1, "x");\n').returncode
        != 0
    )
