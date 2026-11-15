import shutil
import subprocess

import pytest
from returns.result import Failure, Success

from bpmncwpverify.core.bpmn import (
    Bpmn,
    EndEvent,
    ExclusiveGatewayNode,
    IntermediateEvent,
    MessageFlow,
    Node,
    ParallelGatewayNode,
    Process,
    SequenceFlow,
    StartEvent,
    Task,
)
from bpmncwpverify.visitors.bpmn_cbmc_visitor import CbmcBpmnVisitor


def _start(id="S"):
    return StartEvent(id, id, "", "")


def _end(id="E"):
    return EndEvent(id, id, "", "")


def _task(id="T", behavior=""):
    return Task(id, id, behavior)


def _link(src: Node, tgt: Node, id: str, expr: str = "") -> SequenceFlow:
    flow = SequenceFlow(id, id)
    flow.source_node, flow.target_node = src, tgt
    flow.expression = expr
    src.add_out_flow(flow)
    tgt.add_in_flow(flow)
    return flow


def _message(src: Node, tgt: Node, id: str) -> MessageFlow:
    msg = MessageFlow(id, id)
    msg.source_node, msg.target_node = src, tgt
    src.add_out_msg(msg)
    tgt.add_in_msg(msg)
    return msg


def _bpmn(*processes: tuple[str, list[Node]]) -> Bpmn:
    bpmn = Bpmn()
    for pid, nodes in processes:
        process = Process(pid, pid)
        for node in nodes:
            process[node.id] = node
        bpmn.processes[pid] = process
    return bpmn


def _visit(bpmn: Bpmn) -> CbmcBpmnVisitor:
    visitor = CbmcBpmnVisitor()
    bpmn.accept(visitor)
    return visitor


def _linear():
    s, t, e = _start(), _task(), _end()
    _link(s, t, "F1")
    _link(t, e, "F2")
    return _bpmn(("P", [s, t, e]))


def test_places_one_per_start_event_and_flow():
    v = _visit(_linear())
    decl = repr(v.declarations)
    assert "bool tok_S = true;" in decl
    assert "bool tok_F1 = false;" in decl
    assert "bool tok_F2 = false;" in decl
    assert "bool ended_P = false;" in decl
    assert decl.count("bool tok_") == 3


def test_linear_has_one_transition_per_element():
    v = _visit(_linear())
    assert v.num_transitions == 3
    assert isinstance(v.result(), Success)


def test_start_event_transition():
    decl = repr(_visit(_linear()).declarations)
    assert "return !ended_P && (tok_S);" in decl
    assert "tok_S = false;" in decl


def test_task_transition_consumes_and_produces():
    decl = repr(_visit(_linear()).declarations)
    assert "return !ended_P && (tok_F1);" in decl
    body = decl.split("/* task T */")[1].split("}")[1]
    assert "tok_F1 = false;" in body
    assert "tok_F2 = true;" in body


def test_end_event_ends_process():
    decl = repr(_visit(_linear()).declarations)
    body = decl.split("/* end event E */")[1]
    assert "ended_P = true;" in body


def test_all_ended_covers_every_process():
    s1, e1, s2, e2 = _start("S1"), _end("E1"), _start("S2"), _end("E2")
    _link(s1, e1, "A")
    _link(s2, e2, "B")
    v = _visit(_bpmn(("P1", [s1, e1]), ("P2", [s2, e2])))
    assert v.all_ended == "ended_P1 && ended_P2"


def test_intermediate_event():
    s, i, e = _start(), IntermediateEvent("I", "I", "", "", "catch"), _end()
    _link(s, i, "F1")
    _link(i, e, "F2")
    v = _visit(_bpmn(("P", [s, i, e])))
    assert v.num_transitions == 3
    assert "/* intermediate event I */" in repr(v.declarations)


def test_task_with_multiple_incoming_flows_is_enabled_by_any():
    s1, s2, t, e = _start("S1"), _start("S2"), _task(), _end()
    _link(s1, t, "A")
    _link(s2, t, "B")
    _link(t, e, "C")
    decl = repr(_visit(_bpmn(("P", [s1, s2, t, e]))).declarations)
    assert "return !ended_P && (tok_A || tok_B);" in decl
    body = decl.split("/* task T */")[1].split("}")[1]
    assert "tok_A = false;" in body and "tok_B = false;" in body


def test_message_flow_is_a_place_set_by_sender_and_required_by_receiver():
    s1, send, e1 = _start("S1"), _task("Send"), _end("E1")
    s2, recv, e2 = (
        _start("S2"),
        IntermediateEvent("R", "R", "", "", "catch"),
        _end("E2"),
    )
    _link(s1, send, "A")
    _link(send, e1, "B")
    _link(s2, recv, "C")
    _link(recv, e2, "D")
    _message(send, recv, "M")
    v = _visit(_bpmn(("P1", [s1, send, e1]), ("P2", [s2, recv, e2])))
    decl = repr(v.declarations)
    assert "bool tok_M = false;" in decl
    send_body = decl.split("/* task Send */")[1].split("}")[1]
    assert "tok_M = true;" in send_body
    assert "return !ended_P2 && (tok_C) && (tok_M);" in decl
    recv_body = decl.split("/* intermediate event R */")[1].split("}")[1]
    assert "tok_M = false;" in recv_body


def test_message_start_event_needs_its_message():
    s1, send, e1 = _start("S1"), _task("Send"), _end("E1")
    s2, e2 = _start("S2"), _end("E2")
    _link(s1, send, "A")
    _link(send, e1, "B")
    _link(s2, e2, "C")
    _message(send, s2, "M")
    decl = repr(_visit(_bpmn(("P1", [s1, send, e1]), ("P2", [s2, e2]))).declarations)
    assert "return !ended_P2 && (tok_S2) && (tok_M);" in decl


def _gateway():
    s, g, a, b = _start(), ExclusiveGatewayNode("G", "G"), _end("A"), _end("B")
    _link(s, g, "F1")
    _link(g, a, "Fa", "x > 5")
    _link(g, b, "Fb", "x <= 5")
    return _bpmn(("P", [s, g, a, b]))


def test_exclusive_gateway_has_one_transition_per_flow_plus_no_path():
    v = _visit(_gateway())
    decl = repr(v.declarations)
    # start, 3 for the gateway, 2 end events
    assert v.num_transitions == 6
    assert "return !ended_P && (tok_F1) && (x > 5);" in decl
    assert "return !ended_P && (tok_F1) && (x <= 5);" in decl
    assert "return !ended_P && (tok_F1) && (!((x > 5) || (x <= 5)));" in decl
    assert "No viable path" in decl


def test_exclusive_gateway_flow_only_sets_its_own_place():
    decl = repr(_visit(_gateway()).declarations)
    body = decl.split("/* exclusive gateway G to Fa */")[1].split("}")[1]
    assert "tok_Fa = true;" in body
    assert "tok_Fb" not in body
    assert "tok_F1 = false;" in body


def test_pass_picks_exactly_one_transition_without_looping():
    v = _visit(_gateway())
    step = repr(v.step)
    assert "nondet_int()" in step
    assert f"transition_choice < {v.num_transitions}" in step
    assert step.count("switch (") == 1
    for i in range(v.num_transitions):
        assert f"case {i}:" in step
        assert step.count(f"__CPROVER_assume(enabled_{i}());") == 1
        assert step.count(f"fire_{i}();") == 1
    for loop in ("for (", "while (", "do {"):
        assert loop not in step
        assert loop not in repr(v.declarations)


def test_collision_checked_once_per_pass():
    step = repr(_visit(_linear()).step)
    assert step.count("__CPROVER_assert(") == 1
    assert "token_collision" in step


def test_task_with_two_outgoing_flows_sets_both():
    s, t, a, b = _start(), _task(), _end("A"), _end("B")
    _link(s, t, "F1")
    _link(t, a, "Fa")
    _link(t, b, "Fb")
    decl = repr(_visit(_bpmn(("P", [s, t, a, b]))).declarations)
    body = decl.split("/* task T */")[1].split("}")[1]
    assert "token_collision = tok_Fa || tok_Fb;" in body
    assert "tok_Fa = true;" in body and "tok_Fb = true;" in body


def test_join_reached_twice_is_generated_once():
    s, g, a, b, j, e = (
        _start(),
        ExclusiveGatewayNode("G", "G"),
        _task("A"),
        _task("B"),
        ExclusiveGatewayNode("J", "J"),
        _end(),
    )
    _link(s, g, "F1")
    _link(g, a, "Fa", "x > 5")
    _link(g, b, "Fb", "x <= 5")
    fa = _link(a, j, "Fja")
    fb = _link(b, j, "Fjb")
    fa.is_leaf = False
    fb.is_leaf = True
    _link(j, e, "Fe", "true")
    v = _visit(_bpmn(("P", [s, g, a, b, j, e])))
    assert repr(v.declarations).count("/* end event E */") == 1


def test_multiline_expression_is_flattened():
    s, g, a = _start(), ExclusiveGatewayNode("G", "G"), _end("A")
    _link(s, g, "F1")
    _link(g, a, "Fa", "x > 5 &&\ny < 3")
    decl = repr(_visit(_bpmn(("P", [s, g, a]))).declarations)
    assert "(x > 5 && y < 3)" in decl


def test_ids_are_made_into_c_identifiers():
    s, e = _start("Start-1"), _end("End.1")
    _link(s, e, "Flow-1")
    decl = repr(_visit(_bpmn(("Process-1", [s, e]))).declarations)
    assert "bool tok_Start_1 = true;" in decl
    assert "bool tok_Flow_1 = false;" in decl
    assert "ended_Process_1" in decl


def _fork_join():
    s, f, a, b, j, e = (
        _start(),
        ParallelGatewayNode("F", "F", is_fork=True),
        _task("A"),
        _task("B"),
        ParallelGatewayNode("J", "J"),
        _end(),
    )
    _link(s, f, "F1")
    _link(f, a, "Fa")
    _link(f, b, "Fb")
    _link(a, j, "Fja")
    _link(b, j, "Fjb")
    _link(j, e, "Fe")
    return _bpmn(("P", [s, f, a, b, j, e]))


def test_fork_starts_every_branch():
    v = _visit(_fork_join())
    assert isinstance(v.result(), Success)
    decl = repr(v.declarations)
    assert "/* parallel gateway F */" in decl
    assert "return !ended_P && (tok_F1);" in decl
    body = decl.split("/* parallel gateway F */")[1].split("/* ")[0]
    assert "tok_F1 = false;" in body
    assert "token_collision = tok_Fa || tok_Fb;" in body
    assert "tok_Fa = true;" in body and "tok_Fb = true;" in body


def test_join_waits_for_every_incoming_flow():
    decl = repr(_visit(_fork_join()).declarations)
    assert "return !ended_P && (tok_Fja && tok_Fjb);" in decl
    body = decl.split("/* parallel gateway J */")[1].split("/* ")[0]
    assert "tok_Fja = false;" in body and "tok_Fjb = false;" in body
    assert "tok_Fe = true;" in body


def test_fork_with_loop_back_is_enabled_by_any_incoming_flow():
    s, f, a, b, g, e = (
        _start(),
        ParallelGatewayNode("F", "F", is_fork=True),
        _task("A"),
        _task("B"),
        ExclusiveGatewayNode("G", "G"),
        _end(),
    )
    _link(s, f, "F1")
    _link(f, a, "Fa")
    _link(f, b, "Fb")
    _link(a, g, "Fga")
    _link(b, g, "Fgb")
    _link(g, f, "Floop", "x > 0")
    _link(g, e, "Fe", "x <= 0")
    v = _visit(_bpmn(("P", [s, f, a, b, g, e])))
    assert isinstance(v.result(), Success)
    decl = repr(v.declarations)
    assert "return !ended_P && (tok_F1 || tok_Floop);" in decl
    body = decl.split("/* parallel gateway F */")[1].split("/* ")[0]
    assert "tok_F1 = false;" in body and "tok_Floop = false;" in body


def test_nested_parallel_gateways():
    s, f1, f2, a, b, c, j2, j1, e = (
        _start(),
        ParallelGatewayNode("F1", "F1", is_fork=True),
        ParallelGatewayNode("F2", "F2", is_fork=True),
        _task("A"),
        _task("B"),
        _task("C"),
        ParallelGatewayNode("J2", "J2"),
        ParallelGatewayNode("J1", "J1"),
        _end(),
    )
    _link(s, f1, "S1")
    _link(f1, f2, "Fo")
    _link(f1, c, "Fc")
    _link(f2, a, "Fa")
    _link(f2, b, "Fb")
    _link(a, j2, "Ja")
    _link(b, j2, "Jb")
    _link(j2, j1, "Jo")
    _link(c, j1, "Jc")
    _link(j1, e, "Fe")
    v = _visit(_bpmn(("P", [s, f1, f2, a, b, c, j2, j1, e])))
    assert isinstance(v.result(), Success)
    decl = repr(v.declarations)
    assert v.num_transitions == 9
    assert "return !ended_P && (tok_Ja && tok_Jb);" in decl
    assert "return !ended_P && (tok_Jo && tok_Jc);" in decl
    assert decl.count("/* parallel gateway J1 */") == 1
    assert "return !ended_P && (tok_Fo);" in decl


def test_join_with_one_incoming_flow_just_passes_the_token():
    s, g, e = _start(), ParallelGatewayNode("G", "G"), _end()
    _link(s, g, "F1")
    _link(g, e, "F2")
    decl = repr(_visit(_bpmn(("P", [s, g, e]))).declarations)
    assert "return !ended_P && (tok_F1);" in decl


def _behavior_body(behavior: str) -> str:
    s, t, e = _start(), _task("T", behavior), _end()
    _link(s, t, "F1")
    _link(t, e, "F2")
    v = _visit(_bpmn(("P", [s, t, e])))
    assert isinstance(v.result(), Success), v.result()
    return repr(v.declarations).split("/* task T */")[1].split("/* ")[0]


def test_empty_behavior_does_not_update_the_cwp():
    assert "cwp_update_state" not in _behavior_body("")
    assert "cwp_update_state" not in _behavior_body("  \n ")


def test_assignment_is_followed_by_cwp_update():
    body = _behavior_body("x = 5\ny = x")
    assert "x = 5;" in body and "y = x;" in body
    assert body.index("y = x;") < body.index("cwp_update_state();")
    # the update comes after the behavior and before the tokens move on
    assert body.index("cwp_update_state();") < body.index("tok_F2 = true;")
    assert body.count("cwp_update_state();") == 1


def test_assignment_of_enum_value_and_semicolons():
    body = _behavior_body("uuvComms = sent;\nrisk = acceptable;")
    assert "uuvComms = sent;" in body and "risk = acceptable;" in body


def test_comparison_and_assert():
    body = _behavior_body("assert(sevNeed != discharge)\nok = a == b && c <= 3")
    assert '__CPROVER_assert((sevNeed != discharge), "' in body
    assert "ok = a == b && c <= 3;" in body


def test_skip_only_behavior_still_updates_the_cwp():
    body = _behavior_body("skip")
    assert "cwp_update_state();" in body


def test_if_with_guarded_options_and_else():
    body = _behavior_body(
        "if\n:: x == 1 -> y = 2\n:: x == 2 ->\n  y = 3;\n  z = 4;\n:: else -> skip\nfi"
    )
    assert "int behavior_choice_0 = nondet_int();" in body
    assert "behavior_choice_0 >= 0 && behavior_choice_0 < 3" in body
    assert "__CPROVER_assume(x == 1);" in body
    assert "__CPROVER_assume(x == 2);" in body
    assert "__CPROVER_assume(!((x == 1) || (x == 2)));" in body
    assert "y = 2;" in body and "y = 3;" in body and "z = 4;" in body


def test_if_with_guard_only_option_has_no_body():
    body = _behavior_body("if\n:: true -> a = 1\n:: true\nfi")
    assert "a = 1;" in body
    assert body.count("__CPROVER_assume(true);") == 2


def test_single_option_if_is_not_a_choice():
    body = _behavior_body("if\n:: true -> examTime = now\nfi")
    assert "nondet_int" not in body
    assert "examTime = now;" in body


def test_nested_if_gets_its_own_choice():
    body = _behavior_body(
        "if\n:: a == 1\n:: else ->\n if\n :: true -> b = 1\n :: true -> b = 2\n fi\nfi"
    )
    assert "behavior_choice_0" in body and "behavior_choice_1" in body


def test_choice_variables_are_unique_across_tasks():
    s, t1, t2, e = _start(), _task("T1", ""), _task("T2", ""), _end()
    choice = "if\n:: true -> a = 1\n:: true -> a = 2\nfi"
    t1.behavior = t2.behavior = choice
    _link(s, t1, "F1")
    _link(t1, t2, "F2")
    _link(t2, e, "F3")
    decl = repr(_visit(_bpmn(("P", [s, t1, t2, e]))).declarations)
    assert "int behavior_choice_0 =" in decl and "int behavior_choice_1 =" in decl


def test_multiline_guard_is_flattened():
    body = _behavior_body("if\n:: x > 5 &&\n y < 3 -> a = 1\n:: else -> a = 2\nfi")
    assert "__CPROVER_assume(x > 5 && y < 3);" in body


def test_behavior_comments_are_ignored():
    body = _behavior_body("/* note */ a = 1 // trailing\n")
    assert "a = 1;" in body


@pytest.mark.parametrize(
    "behavior",
    [
        "do\n:: a == 1 -> break\nod",
        "printf(1)",
        "a == 1",
        "if\n:: a == 1 -> b = 1",
        "a = ",
    ],
)
def test_unsupported_behavior_is_an_error(behavior):
    s, t, e = _start(), _task("T", behavior), _end()
    _link(s, t, "F1")
    _link(t, e, "F2")
    result = _visit(_bpmn(("P", [s, t, e]))).result()
    assert isinstance(result, Failure)
    assert result.failure().element_id == "T"


def test_task_with_boundary_event_is_an_error():
    s, t, e = _start(), _task(), _end()
    _link(s, t, "F1")
    _link(t, e, "F2")
    be = Task.BoundaryEvent("B", "B", "", "", "T")
    t.add_boundary_event(be)
    result = _visit(_bpmn(("P", [s, t, e]))).result()
    assert isinstance(result, Failure)
    assert result.failure().element_id == "T"


def test_exclusive_gateway_flow_without_condition_is_an_error():
    s, g, a = _start(), ExclusiveGatewayNode("G", "G"), _end("A")
    _link(s, g, "F1")
    _link(g, a, "Fa")
    result = _visit(_bpmn(("P", [s, g, a]))).result()
    assert isinstance(result, Failure)
    assert result.failure().element_id == "G"


def test_node_without_incoming_flow_is_an_error():
    visitor = CbmcBpmnVisitor()
    visitor.visit_process(Process("P", "P"))
    assert visitor.visit_task(_task("Bare")) is False
    result = visitor.result()
    assert isinstance(result, Failure)
    assert result.failure().element_id == "Bare"


@pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc is not installed")
def test_generated_c_runs_under_cbmc(tmp_path):
    v = _visit(_gateway())
    program = (
        "int x = 0;\n"
        + repr(v.declarations)
        + "int main(void) {\n"
        + "x = nondet_int();\n"
        + "for (int i = 0; i < 4; i++) {\n"
        + f"if ({v.all_ended}) break;\n"
        + repr(v.step)
        + "}\n"
        + f'__CPROVER_assert({v.all_ended}, "ended");\n'
        + "return 0;\n}\n"
    )
    path = tmp_path / "model.c"
    path.write_text(program)
    run = subprocess.run(
        ["cbmc", str(path), "--unwind", "5", "--unwinding-assertions"],
        capture_output=True,
        text=True,
    )
    assert "VERIFICATION SUCCESSFUL" in run.stdout, run.stdout[-2000:]


def _cbmc(tmp_path, v, prelude, bound):
    program = (
        prelude
        + repr(v.declarations)
        + "int main(void) {\n"
        + "for (int i = 0; i < "
        + str(bound)
        + "; i++) {\n"
        + f"if ({v.all_ended}) break;\n"
        + repr(v.step)
        + "}\n"
        + f'__CPROVER_assert({v.all_ended}, "ended");\n'
        + "return 0;\n}\n"
    )
    path = tmp_path / "model.c"
    path.write_text(program)
    return subprocess.run(
        ["cbmc", str(path), "--unwind", str(bound + 1), "--unwinding-assertions"],
        capture_output=True,
        text=True,
    ).stdout


@pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc is not installed")
def test_fork_and_join_run_under_cbmc(tmp_path):
    out = _cbmc(tmp_path, _visit(_fork_join()), "", 8)
    assert "VERIFICATION SUCCESSFUL" in out, out[-2000:]


@pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc is not installed")
def test_behavior_and_cwp_update_run_under_cbmc(tmp_path):
    s, t, e = (
        _start(),
        _task("T", "x = 3\nif\n:: x == 3 -> y = 1\n:: else -> y = 2\nfi"),
        _end(),
    )
    _link(s, t, "F1")
    _link(t, e, "F2")
    v = _visit(_bpmn(("P", [s, t, e])))
    prelude = (
        "int x = 0; int y = 0; int updates = 0;\n"
        'static void cwp_update_state(void) { updates++; __CPROVER_assert(y == 1, "y"); }\n'
    )
    out = _cbmc(tmp_path, v, prelude, 5)
    assert "VERIFICATION SUCCESSFUL" in out, out[-2000:]
    # a behavior that breaks the property is caught
    prelude = prelude.replace("y == 1", "y == 2")
    out = _cbmc(tmp_path, v, prelude, 5)
    assert "VERIFICATION FAILED" in out
