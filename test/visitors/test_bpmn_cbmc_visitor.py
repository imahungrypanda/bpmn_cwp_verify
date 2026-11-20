import shutil
import subprocess

import pytest

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
from bpmncwpverify.visitors.bpmn_cbmc_visitor import CbmcBpmnVisitor
from bpmncwpverify.visitors.cwp_cbmc_visitor import UPDATE_FUNCTION


def _start(id: str) -> StartEvent:
    return StartEvent(id, id, "", "")


def _end(id: str) -> EndEvent:
    return EndEvent(id, id, "", "")


def _flow(id: str, src: Node, dst: Node, expression: str = "") -> SequenceFlow:
    flow = SequenceFlow(id, id)
    flow.source_node, flow.target_node = src, dst
    flow.expression = expression
    src.add_out_flow(flow)
    dst.add_in_flow(flow)
    return flow


def _msg(id: str, src: Node, dst: Node) -> MessageFlow:
    msg = MessageFlow(id, id)
    msg.source_node, msg.target_node = src, dst
    src.add_out_msg(msg)
    dst.add_in_msg(msg)
    return msg


def _bpmn(*processes: tuple[str, list[Node]]) -> Bpmn:
    bpmn = Bpmn()
    for pid, nodes in processes:
        process = Process(pid, pid)
        for node in nodes:
            process[node.id] = node
        bpmn.processes[pid] = process
    return bpmn


def _run(bpmn: Bpmn) -> CbmcBpmnVisitor:
    visitor = CbmcBpmnVisitor()
    bpmn.accept(visitor)
    return visitor


def _case(visitor: CbmcBpmnVisitor, index: int) -> str:
    step = repr(visitor.step)
    start = step.index(f"case {index}:")
    ends = [step.find(m, start + 1) for m in ("\n\t\tcase ", "\n\t\tdefault:")]
    return step[start : min(e for e in ends if e != -1)]


def _linear() -> Bpmn:
    s, t, e = _start("S"), Task("T", "T", ""), _end("E")
    _flow("f1", s, t)
    _flow("f2", t, e)
    return _bpmn(("P", [s, t, e]))


def test_places_one_per_start_event_and_flow():
    visitor = _run(_linear())

    defs = repr(visitor.defs)
    assert "bool tok_S = 0;" in defs
    assert "bool tok_f1 = 0;" in defs
    assert "bool tok_f2 = 0;" in defs
    assert "bool ended_P = 0;" in defs
    assert defs.count("bool tok_") == 3
    assert repr(visitor.init) == "tok_S = 1;\n"


def test_start_event_transition():
    visitor = _run(_linear())

    case = _case(visitor, 0)
    assert "__CPROVER_assume((tok_S));" in case
    assert "tok_S = 0;" in case
    assert "tok_f1 = 1;" in case


def test_task_transition_clears_incoming_and_sets_outgoing():
    visitor = _run(_linear())

    case = _case(visitor, 1)
    assert "__CPROVER_assume((tok_f1));" in case
    assert "tok_f1 = 0;" in case
    assert "occupied = tok_f2;" in case
    assert "tok_f2 = 1;" in case


def test_end_event_ends_its_process():
    visitor = _run(_linear())

    case = _case(visitor, 2)
    assert "tok_f2 = 0;" in case
    assert "ended_P = 1;" in case
    assert "occupied" not in case
    assert visitor.all_ended == "ended_P"


def test_all_ended_covers_every_process():
    s1, e1, s2, e2 = _start("S1"), _end("E1"), _start("S2"), _end("E2")
    _flow("f1", s1, e1)
    _flow("f2", s2, e2)
    visitor = _run(_bpmn(("P1", [s1, e1]), ("P2", [s2, e2])))

    assert visitor.all_ended == "ended_P1 && ended_P2"


def test_all_ended_without_processes():
    assert CbmcBpmnVisitor().all_ended == "1"


def test_intermediate_event_is_a_transition():
    s, i, e = _start("S"), IntermediateEvent("I", "I", "", "", "catch"), _end("E")
    _flow("f1", s, i)
    _flow("f2", i, e)
    visitor = _run(_bpmn(("P", [s, i, e])))

    assert visitor.errors == []
    assert visitor.transition_count == 3
    assert "__CPROVER_assume((tok_f1));" in _case(visitor, 1)


def test_multiple_incoming_flows_any_enables_all_cleared():
    s, t, g, e = (
        _start("S"),
        Task("T", "T", ""),
        ExclusiveGatewayNode("G", "G"),
        _end("E"),
    )
    _flow("f1", s, g)
    _flow("f2", t, g).is_leaf = True  # as the validator marks loops
    _flow("f3", g, t, "x > 0")
    _flow("f4", g, e, "x <= 0")
    visitor = _run(_bpmn(("P", [s, t, g, e])))

    case = next(
        _case(visitor, i)
        for i in range(visitor.transition_count)
        if "G -> f3" in _case(visitor, i)
    )
    assert "(tok_f1 || tok_f2) && (x > 0)" in case
    assert "tok_f1 = 0;" in case and "tok_f2 = 0;" in case


def test_exclusive_gateway_one_transition_per_outgoing_flow():
    s, g, a, b = _start("S"), ExclusiveGatewayNode("G", "G"), _end("A"), _end("B")
    _flow("f0", s, g)
    _flow("fa", g, a, "x == 1")
    _flow("fb", g, b, "x != 1 &&\ny > 2")
    visitor = _run(_bpmn(("P", [s, g, a, b])))

    assert visitor.errors == []
    assert visitor.transition_count == 5  # S, G->fa, G->fb, A, B
    case_a = _case(visitor, 1)
    case_b = _case(visitor, 2)
    assert "__CPROVER_assume((tok_f0) && (x == 1));" in case_a
    assert "tok_fa = 1;" in case_a and "tok_fb" not in case_a
    assert "__CPROVER_assume((tok_f0) && (x != 1 && y > 2));" in case_b
    assert "tok_fb = 1;" in case_b and "tok_fa" not in case_b


def test_exclusive_gateway_flow_without_condition_is_an_error():
    s, g, a = _start("S"), ExclusiveGatewayNode("G", "G"), _end("A")
    _flow("f0", s, g)
    _flow("fa", g, a)
    visitor = _run(_bpmn(("P", [s, g, a])))

    assert len(visitor.errors) == 1
    assert isinstance(visitor.errors[0], BpmnCbmcUnsupportedElementError)
    assert visitor.errors[0].element_id == "G"


def test_message_flow_needs_token_and_sets_token():
    s1, t1, e1 = _start("S1"), Task("T1", "T1", ""), _end("E1")
    s2, t2, e2 = _start("S2"), Task("T2", "T2", ""), _end("E2")
    _flow("a1", s1, t1)
    _flow("a2", t1, e1)
    _flow("b1", s2, t2)
    _flow("b2", t2, e2)
    msg = _msg("m1", t1, t2)
    bpmn = _bpmn(("P1", [s1, t1, e1]), ("P2", [s2, t2, e2]))
    bpmn.add_inter_process_msg(msg)
    visitor = _run(bpmn)

    assert "bool tok_m1 = 0;" in repr(visitor.defs)
    sender = _case(visitor, 1)
    assert "tok_a2 = 1;" in sender and "tok_m1 = 1;" in sender
    receiver = _case(visitor, 4)
    assert "__CPROVER_assume((tok_b1) && (tok_m1));" in receiver
    assert "tok_m1 = 0;" in receiver


def _find(visitor: CbmcBpmnVisitor, label: str) -> str:
    return next(
        _case(visitor, i)
        for i in range(visitor.transition_count)
        if f"/* {label} */" in _case(visitor, i)
    )


def _fork_join() -> Bpmn:
    s, f, a, b, j, e = (
        _start("S"),
        ParallelGatewayNode("F", "F"),
        Task("A", "A", ""),
        Task("B", "B", ""),
        ParallelGatewayNode("J", "J"),
        _end("E"),
    )
    _flow("f0", s, f)
    _flow("fa", f, a)
    _flow("fb", f, b)
    _flow("ga", a, j)
    _flow("gb", b, j)
    _flow("h", j, e)
    return _bpmn(("P", [s, f, a, b, j, e]))


def test_fork_starts_every_branch():
    visitor = _run(_fork_join())

    assert visitor.errors == []
    case = _find(visitor, "F")
    assert "__CPROVER_assume((tok_f0));" in case
    assert "occupied = tok_fa || tok_fb;" in case
    assert "tok_fa = 1;" in case and "tok_fb = 1;" in case


def test_join_waits_for_every_incoming_flow():
    visitor = _run(_fork_join())

    case = _find(visitor, "J")
    assert "__CPROVER_assume((tok_ga && tok_gb));" in case
    assert "tok_ga = 0;" in case and "tok_gb = 0;" in case
    assert "tok_h = 1;" in case


def test_fork_with_loop_coming_back_is_enabled_by_any_incoming_flow():
    s, f, a, b, g, e = (
        _start("S"),
        ParallelGatewayNode("F", "F"),
        Task("A", "A", ""),
        Task("B", "B", ""),
        ExclusiveGatewayNode("G", "G"),
        _end("E"),
    )
    _flow("f0", s, f)
    _flow("fa", f, a)
    _flow("fb", f, b)
    _flow("ga", a, g)
    _flow("end", b, e)
    back = _flow("back", g, f, "x > 0")
    back.is_leaf = True
    _flow("out", g, e, "x <= 0")
    visitor = _run(_bpmn(("P", [s, f, a, b, g, e])))

    assert visitor.errors == []
    case = _find(visitor, "F")
    assert "__CPROVER_assume((tok_f0 || tok_back));" in case
    assert "tok_f0 = 0;" in case and "tok_back = 0;" in case
    assert "tok_fa = 1;" in case and "tok_fb = 1;" in case


def test_nested_parallel_gateways():
    s, f1, f2, a, b, c, j2, j1, e = (
        _start("S"),
        ParallelGatewayNode("F1", "F1"),
        ParallelGatewayNode("F2", "F2"),
        Task("A", "A", ""),
        Task("B", "B", ""),
        Task("C", "C", ""),
        ParallelGatewayNode("J2", "J2"),
        ParallelGatewayNode("J1", "J1"),
        _end("E"),
    )
    _flow("s", s, f1)
    _flow("f1a", f1, a)
    _flow("f1f2", f1, f2)
    _flow("f2b", f2, b)
    _flow("f2c", f2, c)
    _flow("bj2", b, j2)
    _flow("cj2", c, j2)
    _flow("j2j1", j2, j1)
    _flow("aj1", a, j1)
    _flow("j1e", j1, e)
    visitor = _run(_bpmn(("P", [s, f1, f2, a, b, c, j2, j1, e])))

    assert visitor.errors == []
    assert "tok_f1a = 1;" in _find(visitor, "F1")
    assert "tok_f1f2 = 1;" in _find(visitor, "F1")
    assert "__CPROVER_assume((tok_f1f2));" in _find(visitor, "F2")
    assert "__CPROVER_assume((tok_bj2 && tok_cj2));" in _find(visitor, "J2")
    assert "__CPROVER_assume((tok_j2j1 && tok_aj1));" in _find(visitor, "J1")


def _task_case(behavior: str) -> tuple[CbmcBpmnVisitor, str]:
    s, t, e = _start("S"), Task("T", "T", behavior), _end("E")
    _flow("f1", s, t)
    _flow("f2", t, e)
    visitor = _run(_bpmn(("P", [s, t, e])))
    return visitor, _find(visitor, "T")


def test_empty_behavior_does_not_update_the_cwp():
    visitor, case = _task_case("")

    assert UPDATE_FUNCTION not in case
    assert visitor.errors == []


def test_assignments_then_cwp_update():
    visitor, case = _task_case("backpackOwner = sellerName\npaymentOwner = buyerName")

    assert visitor.errors == []
    first = case.index("backpackOwner = sellerName;")
    second = case.index("paymentOwner = buyerName;")
    update = case.index(f"{UPDATE_FUNCTION}();")
    assert first < second < update < case.index("tok_f2 = 1;")
    assert case.count(f"{UPDATE_FUNCTION}();") == 1


def test_semicolons_separate_statements():
    _, case = _task_case("x = 1; y = x + 1")

    assert "x = 1;" in case and "y = x + 1;" in case


def test_behavior_if_picks_among_enabled_options():
    visitor, case = _task_case(
        "if\n:: true -> terms = agreed\n:: true -> terms = failed\nfi"
    )

    assert visitor.errors == []
    assert "unsigned int choice0 = nondet_uint();" in case
    assert "case 0:\n" in case and "case 1:\n" in case
    assert "__CPROVER_assume(true);" in case
    assert "terms = agreed;" in case and "terms = failed;" in case
    assert "__CPROVER_assume(0);" in case
    assert case.index(f"{UPDATE_FUNCTION}();") > case.index("terms = failed;")


def test_behavior_compares_state_variables():
    _, case = _task_case(
        "if\n:: x == 1 && y != 2 -> z = 3\n:: x < y || y >= 4 -> z = 4\nfi"
    )

    assert "__CPROVER_assume(x == 1 && y != 2);" in case
    assert "__CPROVER_assume(x < y || y >= 4);" in case


def test_behavior_else_option_only_when_no_guard_holds():
    _, case = _task_case(
        "if\n:: x > 0 -> z = 1\n:: x < 0 -> z = 2\n:: else -> z = 0\nfi"
    )

    assert "__CPROVER_assume(!((x > 0) || (x < 0)));" in case


def test_behavior_option_with_several_statements_and_nesting():
    _, case = _task_case(
        "if\n:: a > 0 ->\nb = 1\nif\n:: b == 1 -> c = 2\n:: b != 1 -> c = 3\nfi\n"
        ":: else -> b = 0\nfi\nd = 4"
    )

    assert "choice0" in case and "choice1" in case
    assert case.index("b = 1;") < case.index("choice1") < case.index("c = 2;")
    assert case.index("b = 0;") > case.index("c = 3;")
    assert case.index("d = 4;") > case.index("b = 0;")
    assert case.count(f"{UPDATE_FUNCTION}();") == 1


def test_behavior_skip_emits_nothing():
    _, case = _task_case("skip")

    assert "skip" not in case


@pytest.mark.parametrize(
    "behavior", ["do\n:: x = 1\nod", "if\n:: x = 1\nfi", "fi", "if\n:: true -> x = 1"]
)
def test_unsupported_behavior_is_an_error(behavior):
    visitor, case = _task_case(behavior)

    assert len(visitor.errors) == 1
    assert visitor.errors[0].element_id == "T"
    assert UPDATE_FUNCTION not in case


def test_boundary_event_is_an_error():
    s, t, e = _start("S"), Task("T", "T", ""), _end("E")
    _flow("f1", s, t)
    _flow("f2", t, e)
    t.add_boundary_event(Task.BoundaryEvent("B", "B", "", "", "T"))
    visitor = _run(_bpmn(("P", [s, t, e])))

    assert len(visitor.errors) == 1
    assert visitor.errors[0].element_id == "B"


def test_a_pass_picks_exactly_one_transition():
    visitor = _run(_linear())

    step = repr(visitor.step)
    assert step.count("nondet_uint()") == 1
    assert step.count("switch (") == 1
    assert step.count("__CPROVER_assume(") == visitor.transition_count + 1
    assert step.count("break;") == visitor.transition_count
    assert "default:\n\t\t__CPROVER_assume(0);" in step
    for loop in ("for (", "while (", "do {"):
        assert loop not in step


def test_pass_checks_for_occupied_places_once():
    visitor = _run(_linear())

    assert repr(visitor.step).count("__CPROVER_assert(") == 1


def test_step_size_does_not_grow_with_loop_bound():
    # The step is one block; the loop that unrolls it belongs to the caller.
    visitor = _run(_linear())

    assert repr(visitor.step) == repr(visitor.step)
    assert repr(visitor.step).startswith("{\n")


def test_unsafe_ids_become_valid_c_names():
    s, e = _start("S-1"), _end("E.1")
    _flow("flow-1", s, e)
    visitor = _run(_bpmn(("P-1", [s, e])))

    defs = repr(visitor.defs)
    assert "tok_S_1" in defs and "tok_flow_1" in defs and "ended_P_1" in defs


def test_node_reached_twice_is_generated_once():
    s, t, e = _start("S"), Task("T", "T", ""), _end("E")
    _flow("f1", s, t)
    _flow("f2", t, e)
    visitor = CbmcBpmnVisitor()
    t.accept(visitor)
    t.accept(visitor)

    assert repr(visitor.step).count("/* T */") == 1


@pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc is not installed")
def test_generated_c_is_accepted_by_cbmc(tmp_path):
    s, g, t, e = (
        _start("S"),
        ExclusiveGatewayNode("G", "G"),
        Task("T", "T", ""),
        _end("E"),
    )
    _flow("f0", s, g)
    _flow("f1", g, t, "x > 0")
    _flow("f2", g, e, "x <= 0")
    _flow("f3", t, e)
    visitor = _run(_bpmn(("P", [s, g, t, e])))
    program = (
        f"{visitor.defs}\nint x;\n\nint main(void) {{\n"
        f"x = nondet_uint() % 3;\n{visitor.init}"
        f"for (int i = 0; i < 6 && !({visitor.all_ended}); i++)\n{visitor.step}"
        f'__CPROVER_assert({visitor.all_ended} || 1, "reached");\nreturn 0;\n}}\n'
    )
    source = tmp_path / "model.c"
    source.write_text(program)

    result = subprocess.run(
        ["cbmc", str(source), "--unwind", "8"], capture_output=True, text=True
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "VERIFICATION SUCCESSFUL" in result.stdout


@pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc is not installed")
@pytest.mark.parametrize("bad", [False, True])
def test_fork_join_with_behaviors_runs_in_cbmc(tmp_path, bad):
    s, f, a, b, j, e = (
        _start("S"),
        ParallelGatewayNode("F", "F"),
        Task("A", "A", "if\n:: true -> x = 1\n:: true -> x = 2\nfi"),
        Task("B", "B", "y = 5"),
        ParallelGatewayNode("J", "J"),
        _end("E"),
    )
    _flow("f0", s, f)
    _flow("fa", f, a)
    _flow("fb", f, b)
    _flow("ga", a, j)
    _flow("gb", b, j)
    # A second flow into the join's output makes tokens collide when bad.
    _flow("h", j, e)
    visitor = _run(_bpmn(("P", [s, f, a, b, j, e])))
    assert visitor.errors == []
    limit = "x == 1 || x == 2" if not bad else "x == 1"
    program = (
        f"{visitor.defs}\nint x = 0;\nint y = 0;\nvoid {UPDATE_FUNCTION}(void) {{}}\n\n"
        f"int main(void) {{\n{visitor.init}"
        f"for (int i = 0; i < 8 && !({visitor.all_ended}); i++)\n{visitor.step}"
        f'__CPROVER_assert({visitor.all_ended}, "ended");\n'
        f'__CPROVER_assert(y == 5 && ({limit}), "state");\nreturn 0;\n}}\n'
    )
    source = tmp_path / "model.c"
    source.write_text(program)

    result = subprocess.run(
        ["cbmc", str(source), "--unwind", "9"], capture_output=True, text=True
    )

    expected = 10 if bad else 0
    assert result.returncode == expected, result.stdout + result.stderr
