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
from bpmncwpverify.core.error import BpmnCbmcUnsupportedElementError
from bpmncwpverify.visitors.bpmn_cbmc_visitor import (
    HELPER_DEFS_STR,
    CbmcBpmnGenVisitor,
    ended_name,
    place_name,
)


def connect(src: Node, dst: Node, fid: str, expr: str = "") -> SequenceFlow:
    flow = SequenceFlow(fid, fid)
    flow.source_node = src
    flow.target_node = dst
    flow.expression = expr
    src.add_out_flow(flow)
    dst.add_in_flow(flow)
    return flow


def message(src: Node, dst: Node, mid: str) -> MessageFlow:
    msg = MessageFlow(mid, mid)
    msg.source_node = src
    msg.target_node = dst
    src.add_out_msg(msg)
    dst.add_in_msg(msg)
    return msg


def start(i: str = "s") -> StartEvent:
    return StartEvent(i, i, "", "")


def end(i: str = "e") -> EndEvent:
    return EndEvent(i, i, "", "")


def task(i: str = "t") -> Task:
    return Task(i, i, "")


def run(*processes: tuple[str, list[Node]]) -> CbmcBpmnGenVisitor:
    bpmn = Bpmn()
    for pid, nodes in processes:
        process = Process(pid, pid)
        for node in nodes:
            process[node.id] = node
        bpmn.processes[pid] = process
    visitor = CbmcBpmnGenVisitor()
    bpmn.accept(visitor)
    return visitor


def linear() -> CbmcBpmnGenVisitor:
    s, t, e = start(), task(), end()
    connect(s, t, "f1")
    connect(t, e, "f2")
    return run(("p", [s, t, e]))


def test_places_one_per_start_event_and_flow():
    v = linear()
    assert v.places == {
        place_name("s"): True,
        place_name("f1"): False,
        place_name("f2"): False,
    }


def test_start_task_end_transitions():
    v = linear()
    assert [t.label for t in v.transitions] == ["s", "t", "e"]
    start_t, task_t, end_t = v.transitions
    assert start_t.enable == "tok_s"
    assert start_t.body == [
        "tok_s = false;",
        "bpmn_occupied = tok_f1;",
        "tok_f1 = true;",
    ]
    assert task_t.enable == "(tok_f1)"
    assert task_t.body[0] == "tok_f1 = false;"
    assert "tok_f2 = true;" in task_t.body
    assert end_t.enable == "(tok_f2)"
    assert end_t.body == ["tok_f2 = false;", f"{ended_name('p')} = true;"]


def test_all_ended_expression_covers_every_process():
    s1, e1, s2, e2 = start("s1"), end("e1"), start("s2"), end("e2")
    connect(s1, e1, "f1")
    connect(s2, e2, "f2")
    v = run(("p1", [s1, e1]), ("p2", [s2, e2]))
    assert v.all_ended_expr() == "ended_p1 && ended_p2"
    assert "bool ended_p1 = false;" in v.gen_defs()


def test_defs_initialise_tokens():
    defs = linear().gen_defs()
    assert "bool tok_s = true;" in defs
    assert "bool tok_f1 = false;" in defs


def test_intermediate_event():
    s, i, e = start(), IntermediateEvent("i", "i", "", "", "catch"), end()
    connect(s, i, "f1")
    connect(i, e, "f2")
    v = run(("p", [s, i, e]))
    assert [t.label for t in v.transitions] == ["s", "i", "e"]
    assert v.transitions[1].enable == "(tok_f1)"


def gateway_visitor() -> CbmcBpmnGenVisitor:
    s, g, a, b, e = start(), ExclusiveGatewayNode("g", "g"), task("a"), task("b"), end()
    connect(s, g, "f1")
    connect(g, a, "fa", "x > 5")
    connect(g, b, "fb", "x <= 5")
    connect(a, e, "fa2")
    connect(b, e, "fb2")
    return run(("p", [s, g, a, b, e]))


def test_exclusive_gateway_has_one_transition_per_out_flow():
    v = gateway_visitor()
    by_label = {t.label: t for t in v.transitions}
    ta, tb = by_label["g -> fa"], by_label["g -> fb"]
    assert ta.enable == "(tok_f1) && (x > 5)"
    assert tb.enable == "(tok_f1) && (x <= 5)"
    assert ta.body == ["tok_f1 = false;", "bpmn_occupied = tok_fa;", "tok_fa = true;"]
    assert tb.body[-1] == "tok_fb = true;"


def test_exclusive_gateway_without_viable_path_is_a_violation():
    v = gateway_visitor()
    stuck = next(t for t in v.transitions if "no viable path" in t.label)
    assert stuck.enable == "(tok_f1) && !(x > 5) && !(x <= 5)"
    assert stuck.body[0].startswith("__CPROVER_assert(false")


def test_merging_flows_enable_on_any_incoming_place():
    v = gateway_visitor()
    end_t = next(t for t in v.transitions if t.label == "e")
    assert end_t.enable == "(tok_fa2 || tok_fb2)"
    assert end_t.body[:2] == ["tok_fa2 = false;", "tok_fb2 = false;"]


def test_message_flow_places_and_guards():
    s1, t1, e1 = start("s1"), task("t1"), end("e1")
    s2, c, e2 = start("s2"), IntermediateEvent("c", "c", "", "", "catch"), end("e2")
    connect(s1, t1, "f1")
    connect(t1, e1, "f2")
    connect(s2, c, "g1")
    connect(c, e2, "g2")
    message(t1, c, "m1")
    v = run(("p1", [s1, t1, e1]), ("p2", [s2, c, e2]))
    assert v.places["tok_m1"] is False
    send = next(t for t in v.transitions if t.label == "t1")
    assert "tok_m1 = true;" in send.body
    catch = next(t for t in v.transitions if t.label == "c")
    assert catch.enable == "(tok_g1) && (tok_m1)"
    assert "tok_m1 = false;" in catch.body


def test_pass_picks_one_enabled_transition_without_looping():
    v = gateway_visitor()
    code = v.gen_pass()
    n = len(v.transitions)
    assert f"__CPROVER_assume(bpmn_choice < {n}u);" in code
    assert code.count("nondet_uint()") == 1
    assert code.count("switch (") == 1
    assert code.count("__CPROVER_assume(") == n + 2  # bound, every case, default
    for keyword in ("for (", "while (", "do {"):
        assert keyword not in code
    for i in range(n):
        assert f"case {i}:" in code
    # token overflow is checked once per pass
    assert code.count("__CPROVER_assert(!bpmn_occupied") == 1


def test_get_result_success():
    result = linear().get_result()
    assert isinstance(result, Success)
    assert "switch (bpmn_choice)" in result.unwrap()


def test_boundary_event_is_an_error():
    s, t, e, b, e2 = start(), task(), end(), None, end("e2")
    b = Task.BoundaryEvent("b", "b", "", "", "t")
    t.add_boundary_event(b)
    connect(s, t, "f1")
    connect(t, e, "f2")
    connect(b, e2, "f3")
    result = run(("p", [s, t, e, e2])).get_result()
    assert isinstance(result, Failure)
    assert result.failure().element_id == "b"


def test_gateway_with_message_flow_is_an_error():
    s, g, e, o = start(), ExclusiveGatewayNode("g", "g"), end(), end("o")
    connect(s, g, "f1")
    connect(g, e, "f2", "true")
    message(g, o, "m")
    assert isinstance(run(("p", [s, g, e])).get_result(), Failure)


@pytest.mark.parametrize("workflow_name", ["linear", "gateway"])
def test_generated_c_runs_in_cbmc(tmp_path, workflow_name):
    v = linear() if workflow_name == "linear" else gateway_visitor()
    program = (
        f"{HELPER_DEFS_STR}\nint x;\n{v.gen_defs()}\n"
        "int main(void) {\n"
        "  x = nondet_uint() % 10;\n"
        f"  for (int i = 0; i < 6 && !({v.all_ended_expr()}); i++)\n"
        f"{v.gen_pass()}"
        f'  __CPROVER_assert({v.all_ended_expr()}, "ends");\n'
        "  return 0;\n}\n"
    )
    src = tmp_path / "m.c"
    src.write_text(program)
    out = subprocess.run(
        ["cbmc", str(src), "--unwind", "7"], capture_output=True, text=True
    )
    assert "VERIFICATION SUCCESSFUL" in out.stdout, out.stdout[-2000:] + out.stderr


def test_cbmc_finds_gateway_without_viable_path(tmp_path):
    v = gateway_visitor()
    program = (
        f"{HELPER_DEFS_STR}\nint x;\n{v.gen_defs()}\n"
        "int main(void) {\n"
        "  x = nondet_uint() % 10;\n"
        "  __CPROVER_assume(x == 5);\n"
        "  for (int i = 0; i < 6; i++)\n"
        f"{v.gen_pass()}"
        "  return 0;\n}\n"
    ).replace("x <= 5", "x < 5")
    src = tmp_path / "m.c"
    src.write_text(program)
    out = subprocess.run(
        ["cbmc", str(src), "--unwind", "7"], capture_output=True, text=True
    )
    assert "VERIFICATION FAILED" in out.stdout
    assert "no viable path from g" in out.stdout


def pg(i: str) -> ParallelGatewayNode:
    return ParallelGatewayNode(i, i)


def by_label(v: CbmcBpmnGenVisitor, label: str):
    return next(t for t in v.transitions if t.label == label)


def fork_join() -> CbmcBpmnGenVisitor:
    s, fork, a, b, join, e = (
        start(),
        pg("fork"),
        task("a"),
        task("b"),
        pg("join"),
        end(),
    )
    connect(s, fork, "f1")
    connect(fork, a, "fa")
    connect(fork, b, "fb")
    connect(a, join, "ja")
    connect(b, join, "jb")
    connect(join, e, "f2")
    return run(("p", [s, fork, a, b, join, e]))


def test_fork_starts_every_branch():
    v = fork_join()
    fork = by_label(v, "fork")
    assert fork.enable == "(tok_f1)"
    assert fork.body == [
        "tok_f1 = false;",
        "bpmn_occupied = tok_fa || tok_fb;",
        "tok_fa = true;",
        "tok_fb = true;",
    ]


def test_join_waits_for_every_incoming_flow():
    v = fork_join()
    join = by_label(v, "join")
    assert join.enable == "(tok_ja && tok_jb)"
    assert join.body[:2] == ["tok_ja = false;", "tok_jb = false;"]
    assert "tok_f2 = true;" in join.body


def loop_fork() -> CbmcBpmnGenVisitor:
    s, fork, a, g, b, e = (
        start(),
        pg("fork"),
        task("a"),
        ExclusiveGatewayNode("g", "g"),
        task("b"),
        end(),
    )
    connect(s, fork, "f1")
    connect(fork, a, "fa")
    connect(fork, b, "fb")
    connect(a, g, "fg")
    connect(g, fork, "back", "x > 5")
    connect(g, e, "fe", "x <= 5")
    connect(b, e, "fb2")
    return run(("p", [s, fork, a, g, b, e]))


def test_fork_with_loop_back_is_enabled_by_any_incoming_flow():
    fork = by_label(loop_fork(), "fork")
    assert fork.enable == "(tok_f1 || tok_back)"
    assert fork.body[:2] == ["tok_f1 = false;", "tok_back = false;"]


def test_nested_parallel_gateways():
    s, f1, f2, a, b, c, j1, j2, e = (
        start(),
        pg("f1"),
        pg("f2"),
        task("a"),
        task("b"),
        task("c"),
        pg("j1"),
        pg("j2"),
        end(),
    )
    connect(s, f1, "x0")
    connect(f1, f2, "x1")
    connect(f1, c, "x2")
    connect(f2, a, "x3")
    connect(f2, b, "x4")
    connect(a, j1, "x5")
    connect(b, j1, "x6")
    connect(j1, j2, "x7")
    connect(c, j2, "x8")
    connect(j2, e, "x9")
    v = run(("p", [s, f1, f2, a, b, c, j1, j2, e]))
    assert by_label(v, "f2").enable == "(tok_x1)"
    assert by_label(v, "f1").body.count("tok_x1 = true;") == 1
    assert by_label(v, "j1").enable == "(tok_x5 && tok_x6)"
    assert by_label(v, "j2").enable == "(tok_x7 && tok_x8)"
    assert v.get_result().__class__ is Success


def test_parallel_gateway_with_message_flow_is_an_error():
    s, g, e, o = start(), pg("g"), end(), end("o")
    connect(s, g, "f1")
    connect(g, e, "f2")
    message(g, o, "m")
    result = run(("p", [s, g, e])).get_result()
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), BpmnCbmcUnsupportedElementError)


def behavior_body(code: str) -> list[str]:
    s, t, e = start(), Task("t", "t", code), end()
    connect(s, t, "f1")
    connect(t, e, "f2")
    return by_label(run(("p", [s, t, e])), "t").body


def test_empty_behavior_does_not_update_the_cwp():
    assert not any("cwp_update" in line for line in behavior_body(""))


def test_assignments_are_followed_by_cwp_update():
    body = behavior_body("a = b\nc = 1; d = a + 2\nskip")
    assert body[1:5] == ["a = b;", "c = 1;", "d = a + 2;", "cwp_update();"]
    # the CWP update comes before the tokens move on
    assert body.index("cwp_update();") < body.index("tok_f2 = true;")


def test_skip_behavior_still_updates_the_cwp():
    assert behavior_body("skip")[1] == "cwp_update();"


def test_if_behavior_is_a_nondeterministic_choice():
    body = "\n".join(
        behavior_body("if\n:: true -> t = agreed\n:: x == 1 -> t = failed; u = 2\nfi")
    )
    assert "__CPROVER_assume(bpmn_alt_0 < 2u);" in body
    assert "__CPROVER_assume(true);" in body
    assert "__CPROVER_assume(x == 1);" in body
    assert "t = failed;" in body and "u = 2;" in body
    assert body.index("t = failed;") < body.index("cwp_update();")


def test_else_option_negates_the_other_guards():
    body = "\n".join(
        behavior_body("if\n:: x > 1 -> t = 1\n:: x < 0 -> t = 2\n:: else -> t = 3\nfi")
    )
    assert "__CPROVER_assume(!(x > 1) && !(x < 0));" in body


def test_nested_if_behavior():
    body = "\n".join(
        behavior_body("if\n:: true ->\nif\n:: true -> a = 1\nfi\nb = 2\nfi")
    )
    assert "bpmn_alt_0" in body and "bpmn_alt_1" in body
    assert body.index("a = 1;") < body.index("b = 2;")


@pytest.mark.parametrize("code", ["do\n:: true -> a = 1\nod", "foo(1)", "if\nfi"])
def test_unsupported_behavior_is_an_error(code):
    s, t, e = start(), Task("t", "t", code), end()
    connect(s, t, "f1")
    connect(t, e, "f2")
    result = run(("p", [s, t, e])).get_result()
    assert isinstance(result, Failure)
    assert result.failure().element_id == "t"


def cbmc(tmp_path, v, decls, init, extra="", bound=8):
    program = (
        f"{HELPER_DEFS_STR}\n{decls}\n{v.gen_defs()}\n"
        "int updates = 0;\nstatic void cwp_update(void) { updates++; }\n"
        "int main(void) {\n"
        f"  {init}\n"
        f"  for (int i = 0; i < {bound} && !({v.all_ended_expr()}); i++)\n"
        f"{v.gen_pass()}"
        f"{extra}"
        "  return 0;\n}\n"
    )
    src = tmp_path / "m.c"
    src.write_text(program)
    out = subprocess.run(
        ["cbmc", str(src), "--unwind", str(bound + 1)], capture_output=True, text=True
    )
    return out.stdout


def test_cbmc_fork_join_completes(tmp_path):
    v = fork_join()
    extra = '  __CPROVER_assert(ended_p, "ends");\n'
    assert "VERIFICATION SUCCESSFUL" in cbmc(tmp_path, v, "", "", extra)


def test_cbmc_fork_join_does_not_run_a_join_early(tmp_path):
    v = fork_join()
    # with a single pass past the fork, the join cannot have fired
    extra = '  __CPROVER_assert(!tok_f2 && !ended_p, "no early join");\n'
    assert "VERIFICATION SUCCESSFUL" in cbmc(tmp_path, v, "", "", extra, bound=3)


def test_cbmc_loop_back_into_fork_does_not_deadlock(tmp_path):
    v = loop_fork()
    extra = '  __CPROVER_assert(ended_p, "ends");\n'
    out = cbmc(
        tmp_path,
        v,
        "int x;",
        "x = nondet_uint() % 10; __CPROVER_assume(x <= 5);",
        extra,
        bound=12,
    )
    assert "VERIFICATION SUCCESSFUL" in out, out[-1500:]


def test_cbmc_behavior_updates_state_and_cwp(tmp_path):
    code = "if\n:: true -> a = 1\n:: true -> a = 2\nfi\nb = a + 1"
    s, t, e = start(), Task("t", "t", code), end()
    connect(s, t, "f1")
    connect(t, e, "f2")
    v = run(("p", [s, t, e]))
    extra = (
        '  __CPROVER_assert(updates == 1, "one update");\n'
        '  __CPROVER_assert(b == a + 1 && (a == 1 || a == 2), "assigned");\n'
    )
    out = cbmc(tmp_path, v, "int a = 0; int b = 0;", "", extra, bound=5)
    assert "VERIFICATION SUCCESSFUL" in out, out[-1500:]


def test_cbmc_behavior_guard_blocks_when_false(tmp_path):
    code = "if\n:: a == 1 -> b = 5\nfi"
    s, t, e = start(), Task("t", "t", code), end()
    connect(s, t, "f1")
    connect(t, e, "f2")
    v = run(("p", [s, t, e]))
    # the guard is false, so the task can never run and the process never ends
    extra = '  __CPROVER_assert(!ended_p, "blocked");\n'
    out = cbmc(tmp_path, v, "int a = 0; int b = 0;", "", extra, bound=5)
    assert "VERIFICATION SUCCESSFUL" in out, out[-1500:]
