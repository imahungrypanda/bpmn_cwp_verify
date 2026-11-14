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


def test_task_behavior_placeholder():
    v = generate(linear())
    assert "/* behavior of T */" in repr(v.step)


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


@pytest.mark.parametrize("kind", ["parallel", "boundary", "start_with_in"])
def test_unsupported_elements_give_error(kind):
    bpmn, proc = make()
    start = node(proc, StartEvent, "S", "", "")
    end = node(proc, EndEvent, "E", "", "")
    if kind == "parallel":
        mid = node(proc, ParallelGatewayNode, "PG")
    elif kind == "boundary":
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
