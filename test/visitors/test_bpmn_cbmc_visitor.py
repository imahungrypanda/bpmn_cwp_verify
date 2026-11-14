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
    ParallelGatewayNode,
    Process,
    SequenceFlow,
    StartEvent,
    Task,
)
from bpmncwpverify.core.error import BpmnUnsupportedForCError
from bpmncwpverify.visitors.bpmn_cbmc_visitor import CbmcBpmnGenVisitor


def flow(bpmn_proc, fid, source, target, expression=""):
    f = SequenceFlow(fid, fid)
    f.source_node = source
    f.target_node = target
    f.expression = expression
    source.add_out_flow(f)
    target.add_in_flow(f)
    bpmn_proc[fid] = f
    return f


def make(pid="P1"):
    bpmn = Bpmn()
    proc = Process(pid, pid)
    bpmn.processes[pid] = proc
    return bpmn, proc


def node(proc, cls, nid, *args):
    n = cls(nid, nid, *args)
    proc[nid] = n
    return n


def generate(bpmn):
    visitor = CbmcBpmnGenVisitor()
    bpmn.accept(visitor)
    return visitor


def linear():
    bpmn, proc = make()
    start = node(proc, StartEvent, "S", "", "")
    task = node(proc, Task, "T", "")
    end = node(proc, EndEvent, "E", "", "")
    flow(proc, "F1", start, task)
    flow(proc, "F2", task, end)
    return bpmn


def test_linear_places_and_transitions():
    v = generate(linear())
    assert not v.errors
    defs = repr(v.defs)
    for place in ["tok_S", "tok_F1", "tok_F2", "ended_P1"]:
        assert f"static bool {place} = false;" in defs
    assert [t.label for t in v.transitions] == ["S", "T", "E"]
    assert repr(v.init) == "tok_S = true;\n"
    assert v.all_ended == "ended_P1"


def test_enable_clear_set():
    v = generate(linear())
    start, task, end = v.transitions
    assert start.enable == "!ended_P1 && (tok_S)"
    assert start.clear == ["tok_S"] and start.sets == ["tok_F1"]
    assert task.enable == "!ended_P1 && (tok_F1)"
    assert task.clear == ["tok_F1"] and task.sets == ["tok_F2"]
    assert end.sets == [] and end.ends_process


def test_step_is_one_choice_without_loops():
    step = repr(generate(linear()).step)
    assert step.count("nondet_uint()") == 1
    assert "__CPROVER_assume(bpmn_choice < 3);" in step
    assert step.count("switch") == 1
    for kw in ["for (", "while", "do {"]:
        assert kw not in step
    # each transition assumes it is enabled and checks occupancy once
    assert step.count("__CPROVER_assume(!ended_P1") == 3
    assert step.count("already-occupied") == 2
    assert "ended_P1 = true;" in step


def test_empty_behavior_has_no_cwp_update():
    v = generate(linear())
    assert "cwp_update" not in repr(v.step)


def test_intermediate_event():
    bpmn, proc = make()
    start = node(proc, StartEvent, "S", "", "")
    ev = node(proc, IntermediateEvent, "I", "", "", "catch")
    end = node(proc, EndEvent, "E", "", "")
    flow(proc, "F1", start, ev)
    flow(proc, "F2", ev, end)
    v = generate(bpmn)
    assert not v.errors
    assert [t.label for t in v.transitions] == ["S", "I", "E"]


def test_exclusive_gateway_one_transition_per_flow():
    bpmn, proc = make()
    start = node(proc, StartEvent, "S", "", "")
    gw = node(proc, ExclusiveGatewayNode, "G")
    e1 = node(proc, EndEvent, "E1", "", "")
    e2 = node(proc, EndEvent, "E2", "", "")
    flow(proc, "F0", start, gw)
    flow(proc, "Fa", gw, e1, "x ==\n 1")
    flow(proc, "Fb", gw, e2, "x != 1")
    v = generate(bpmn)
    assert not v.errors
    gw_ts = [t for t in v.transitions if t.label.startswith("G")]
    assert len(gw_ts) == 3
    assert gw_ts[0].enable == "!ended_P1 && (tok_F0) && (x == 1)"
    assert gw_ts[0].sets == ["tok_Fa"]
    assert gw_ts[1].sets == ["tok_Fb"]
    # no expression holds: SPIN asserts, so C asserts too
    assert gw_ts[2].enable.endswith("!(x == 1) && !(x != 1)")
    assert "No viable path to take" in repr(v.step)


def test_exclusive_gateway_join_enabled_by_any_incoming():
    bpmn, proc = make()
    start = node(proc, StartEvent, "S", "", "")
    t1 = node(proc, Task, "T1", "")
    t2 = node(proc, Task, "T2", "")
    gw = node(proc, ExclusiveGatewayNode, "G")
    end = node(proc, EndEvent, "E", "", "")
    flow(proc, "Fa", start, t1)
    flow(proc, "Fb", t1, gw)
    flow(proc, "Fc", t2, gw)
    flow(proc, "Fd", gw, end)
    node(proc, StartEvent, "S2", "", "")
    v = generate(bpmn)
    gw_t = next(t for t in v.transitions if t.label.startswith("G"))
    assert gw_t.enable == "!ended_P1 && (tok_Fb || tok_Fc)"
    assert gw_t.clear == ["tok_Fb", "tok_Fc"]


def test_joined_node_is_visited_once():
    bpmn, proc = make()
    start = node(proc, StartEvent, "S", "", "")
    gw = node(proc, ExclusiveGatewayNode, "G")
    t = node(proc, Task, "T", "")
    end = node(proc, EndEvent, "E", "", "")
    flow(proc, "F0", start, gw)
    flow(proc, "Fa", gw, t, "a")
    flow(proc, "Fb", gw, t, "b")
    flow(proc, "F1", t, end)
    v = generate(bpmn)
    assert [x.label for x in v.transitions].count("T") == 1


def test_message_flow():
    bpmn = Bpmn()
    p1, p2 = Process("P1", "P1"), Process("P2", "P2")
    bpmn.processes = {"P1": p1, "P2": p2}
    s1 = node(p1, StartEvent, "S1", "", "")
    send = node(p1, IntermediateEvent, "Send", "", "", "send")
    e1 = node(p1, EndEvent, "E1", "", "")
    s2 = node(p2, StartEvent, "S2", "", "")
    recv = node(p2, IntermediateEvent, "Recv", "", "", "catch")
    e2 = node(p2, EndEvent, "E2", "", "")
    flow(p1, "A1", s1, send)
    flow(p1, "A2", send, e1)
    flow(p2, "B1", s2, recv)
    flow(p2, "B2", recv, e2)
    m = MessageFlow("M", "M")
    m.source_node, m.target_node = send, recv
    send.add_out_msg(m)
    recv.add_in_msg(m)
    v = generate(bpmn)
    assert not v.errors
    send_t = next(t for t in v.transitions if t.label == "Send")
    recv_t = next(t for t in v.transitions if t.label == "Recv")
    assert send_t.sets == ["tok_A2", "msg_M"]
    assert recv_t.enable == "!ended_P2 && (tok_B1) && (msg_M)"
    assert recv_t.clear == ["tok_B1", "msg_M"]
    assert v.all_ended == "ended_P1 && ended_P2"
    assert "static bool msg_M = false;" in repr(v.defs)


@pytest.mark.parametrize("kind", ["boundary", "start_with_in"])
def test_unsupported_elements_give_error(kind):
    bpmn, proc = make()
    start = node(proc, StartEvent, "S", "", "")
    end = node(proc, EndEvent, "E", "", "")
    if kind == "boundary":
        mid = node(proc, Task, "T", "")
        mid.add_boundary_event(Task.BoundaryEvent("B", "B", "", "", "T"))
    else:
        mid = node(proc, Task, "T", "")
        flow(proc, "Fback", mid, start)
    flow(proc, "F1", start, mid)
    flow(proc, "F2", mid, end)
    v = generate(bpmn)
    assert v.errors
    assert all(isinstance(e, BpmnUnsupportedForCError) for e in v.errors)
    assert isinstance(v.result(), Failure)


def test_unsupported_behavior_gives_error():
    bpmn, proc = make()
    start = node(proc, StartEvent, "S", "", "")
    task = node(proc, Task, "T", "do\n:: x = 1\nod")
    end = node(proc, EndEvent, "E", "", "")
    flow(proc, "F1", start, task)
    flow(proc, "F2", task, end)
    v = generate(bpmn)
    assert isinstance(v.result(), Failure)
    assert isinstance(v.errors[0], BpmnUnsupportedForCError)


def test_result_success():
    assert isinstance(generate(linear()).result(), Success)


def test_no_transitions_blocks():
    v = generate(Bpmn())
    assert "__CPROVER_assume(0);" in repr(v.step)
    assert v.all_ended == "true"


@pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc not installed")
def test_generated_c_runs_in_cbmc(tmp_path):
    def run(bpmn):
        v = generate(bpmn)
        src = (
            "#include <stdbool.h>\n"
            f"{v.defs}\nint main(void) {{\n{v.init}\n"
            f"for (int i = 0; i < 10 && !({v.all_ended}); i++)\n{v.step}\n"
            f'__CPROVER_assert({v.all_ended}, "ended");\nreturn 0;\n}}\n'
        )
        path = tmp_path / "m.c"
        path.write_text(src)
        return subprocess.run(
            ["cbmc", str(path), "--unwind", "11"], capture_output=True, text=True
        )

    assert "VERIFICATION SUCCESSFUL" in run(linear()).stdout

    bpmn, proc = make()
    start = node(proc, StartEvent, "S", "", "")
    gw = node(proc, ExclusiveGatewayNode, "G")
    end = node(proc, EndEvent, "E", "", "")
    flow(proc, "F0", start, gw)
    flow(proc, "Fa", gw, end, "0")
    assert "VERIFICATION FAILED" in run(bpmn).stdout


##########################
# Parallel gateways
##########################


def fork_join():
    bpmn, proc = make()
    start = node(proc, StartEvent, "S", "", "")
    fork = node(proc, ParallelGatewayNode, "Fork")
    a = node(proc, Task, "A", "")
    b = node(proc, Task, "B", "")
    join = node(proc, ParallelGatewayNode, "Join")
    end = node(proc, EndEvent, "E", "", "")
    flow(proc, "F0", start, fork)
    flow(proc, "Fa", fork, a)
    flow(proc, "Fb", fork, b)
    flow(proc, "Ga", a, join)
    flow(proc, "Gb", b, join)
    flow(proc, "H", join, end)
    return bpmn


def by_label(v, label):
    return next(t for t in v.transitions if t.label == label)


def test_fork_starts_every_branch():
    v = generate(fork_join())
    assert not v.errors
    fork = by_label(v, "Fork")
    assert fork.enable == "!ended_P1 && (tok_F0)"
    assert fork.clear == ["tok_F0"]
    assert fork.sets == ["tok_Fa", "tok_Fb"]


def test_join_waits_for_every_incoming_flow():
    join = by_label(generate(fork_join()), "Join")
    assert join.enable == "!ended_P1 && (tok_Ga && tok_Gb)"
    assert join.clear == ["tok_Ga", "tok_Gb"]
    assert join.sets == ["tok_H"]


def loop_fork():
    bpmn, proc = make()
    start = node(proc, StartEvent, "S", "", "")
    fork = node(proc, ParallelGatewayNode, "Fork")
    a = node(proc, Task, "A", "")
    b = node(proc, Task, "B", "")
    gw = node(proc, ExclusiveGatewayNode, "G")
    end = node(proc, EndEvent, "E", "", "")
    flow(proc, "F0", start, fork)
    flow(proc, "Fa", fork, a)
    flow(proc, "Fb", fork, b)
    flow(proc, "Ga", a, gw)
    flow(proc, "Fend", b, end)
    flow(proc, "Back", gw, fork, "again")
    flow(proc, "Out", gw, end, "!again")
    return bpmn


def test_fork_with_loop_back_is_enabled_by_any_incoming():
    v = generate(loop_fork())
    assert not v.errors
    fork = by_label(v, "Fork")
    assert fork.enable == "!ended_P1 && (tok_F0 || tok_Back)"
    assert fork.clear == ["tok_F0", "tok_Back"]
    assert fork.sets == ["tok_Fa", "tok_Fb"]


def test_nested_parallel_gateways():
    bpmn, proc = make()
    start = node(proc, StartEvent, "S", "", "")
    outer = node(proc, ParallelGatewayNode, "Outer")
    inner = node(proc, ParallelGatewayNode, "Inner")
    a = node(proc, Task, "A", "")
    b = node(proc, Task, "B", "")
    c = node(proc, Task, "C", "")
    ijoin = node(proc, ParallelGatewayNode, "InnerJoin")
    ojoin = node(proc, ParallelGatewayNode, "OuterJoin")
    end = node(proc, EndEvent, "E", "", "")
    flow(proc, "F0", start, outer)
    flow(proc, "O1", outer, inner)
    flow(proc, "O2", outer, c)
    flow(proc, "I1", inner, a)
    flow(proc, "I2", inner, b)
    flow(proc, "J1", a, ijoin)
    flow(proc, "J2", b, ijoin)
    flow(proc, "K1", ijoin, ojoin)
    flow(proc, "K2", c, ojoin)
    flow(proc, "H", ojoin, end)
    v = generate(bpmn)
    assert not v.errors
    assert by_label(v, "Outer").sets == ["tok_O1", "tok_O2"]
    assert by_label(v, "Inner").enable == "!ended_P1 && (tok_O1)"
    assert by_label(v, "Inner").sets == ["tok_I1", "tok_I2"]
    assert by_label(v, "InnerJoin").enable == "!ended_P1 && (tok_J1 && tok_J2)"
    assert by_label(v, "OuterJoin").enable == "!ended_P1 && (tok_K1 && tok_K2)"
    assert len(v.transitions) == 9


def test_parallel_gateway_visited_once_and_checks_occupancy():
    v = generate(fork_join())
    assert [t.label for t in v.transitions].count("Join") == 1
    assert "already-occupied" in repr(v.step)


##########################
# Task behaviors
##########################


def one_task(behavior):
    bpmn, proc = make()
    start = node(proc, StartEvent, "S", "", "")
    task = node(proc, Task, "T", behavior)
    end = node(proc, EndEvent, "E", "", "")
    flow(proc, "F1", start, task)
    flow(proc, "F2", task, end)
    return generate(bpmn)


def test_assignment_then_cwp_update():
    v = one_task("x = 1\ny = z")
    assert not v.errors
    assert by_label(v, "T").behavior == ["x = 1;", "y = z;", "cwp_update();"]
    step = repr(v.step)
    assert step.index("y = z;") < step.index("cwp_update();")
    # behavior runs before the outgoing place is filled
    assert step.index("cwp_update();") < step.index("tok_F2 = true;")


def test_skip_only_behavior_still_updates_cwp():
    assert by_label(one_task("skip"), "T").behavior == ["cwp_update();"]


def test_assert_and_compare():
    v = one_task("assert(sevNeed != discharge)\nx = (a == b)")
    lines = by_label(v, "T").behavior
    assert lines[0].startswith("__CPROVER_assert(sevNeed != discharge, ")
    assert lines[1] == "x = (a == b);"
    assert lines[-1] == "cwp_update();"


def test_if_options_are_nondeterministic_choices():
    v = one_task("if\n:: true -> terms = agreed\n:: true -> terms = failed\nfi")
    assert not v.errors
    text = "\n".join(by_label(v, "T").behavior)
    assert "nondet_uint()" in text
    assert "bpmn_if_0 < 2" in text
    assert text.count("__CPROVER_assume((true));") == 2
    assert "terms = agreed;" in text and "terms = failed;" in text
    assert text.endswith("cwp_update();")


def test_if_else_and_guard_without_arrow():
    v = one_task(
        "if\n:: sevNeed == discharge\n:: else ->\n  if\n  :: true -> a = 1\n"
        "  :: true -> a = 2\n  fi\nfi"
    )
    assert not v.errors
    text = "\n".join(by_label(v, "T").behavior)
    assert "__CPROVER_assume((sevNeed == discharge));" in text
    assert "__CPROVER_assume(!((sevNeed == discharge)));" in text
    assert "bpmn_if_0" in text and "bpmn_if_1" in text


def test_statement_after_if_and_semicolons():
    v = one_task("if\n:: x > 1 -> y = 1; z = 2\nfi\nw = 3;")
    text = by_label(v, "T").behavior
    assert "\t\ty = 1;" in text and "\t\tz = 2;" in text
    assert text[-2:] == ["w = 3;", "cwp_update();"]


@pytest.mark.parametrize(
    "behavior", ["do\n:: x = 1\nod", "goto end", "if\n:: x = 1", "fi", "printf(1)"]
)
def test_unsupported_behaviors(behavior):
    v = one_task(behavior)
    assert isinstance(v.result(), Failure)


def c_program(v, cwp_stub=""):
    return (
        "#include <stdbool.h>\n"
        f"{v.defs}\n{cwp_stub}int main(void) {{\n{v.init}\n"
        f"for (int i = 0; i < 12 && !({v.all_ended}); i++)\n{v.step}\n"
        f'__CPROVER_assert({v.all_ended}, "ended");\nreturn 0;\n}}\n'
    )


def run_cbmc(tmp_path, src):
    path = tmp_path / "m.c"
    path.write_text(src)
    return subprocess.run(
        ["cbmc", str(path), "--unwind", "13"], capture_output=True, text=True
    ).stdout


@pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc not installed")
def test_behaviors_and_parallel_in_cbmc(tmp_path):
    # x is set by one branch, y by the other, and they must both be set at the join
    bpmn, proc = make()
    start = node(proc, StartEvent, "S", "", "")
    fork = node(proc, ParallelGatewayNode, "Fork")
    a = node(proc, Task, "A", "x = 1")
    b = node(proc, Task, "B", "if\n:: true -> y = 1\n:: true -> y = 2\nfi")
    join = node(proc, ParallelGatewayNode, "Join")
    end = node(proc, EndEvent, "E", "", "")
    flow(proc, "F0", start, fork)
    flow(proc, "Fa", fork, a)
    flow(proc, "Fb", fork, b)
    flow(proc, "Ga", a, join)
    flow(proc, "Gb", b, join)
    flow(proc, "H", join, end)
    v = generate(bpmn)
    stub = (
        "int x = 0, y = 0; int updates = 0;\n"
        "unsigned int nondet_uint(void);\n"
        "void cwp_update(void) { updates++; }\n"
    )

    def program(check):
        src = c_program(v, stub)
        return src.replace(
            "return 0;", f'__CPROVER_assert({check}, "check");\nreturn 0;'
        )

    assert "VERIFICATION SUCCESSFUL" in run_cbmc(
        tmp_path, program("x == 1 && (y == 1 || y == 2) && updates == 2")
    )
    assert "VERIFICATION FAILED" in run_cbmc(tmp_path, program("y == 1"))
