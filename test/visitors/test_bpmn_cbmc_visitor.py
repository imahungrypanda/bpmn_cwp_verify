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
from bpmncwpverify.core.error import BpmnCbmcUnsupportedElementError
from bpmncwpverify.visitors.bpmn_cbmc_visitor import CbmcBpmnVisitor


def connect(source, target, flow_id, expr=""):
    flow = SequenceFlow(flow_id, flow_id)
    flow.source_node, flow.target_node = source, target
    flow.expression = expr
    source.add_out_flow(flow)
    target.add_in_flow(flow)
    return flow


def start(i):
    return StartEvent(i, i, "", "")


def end(i):
    return EndEvent(i, i, "", "")


def make_bpmn(*processes):
    bpmn = Bpmn()
    for process in processes:
        bpmn.processes[process.id] = process
    return bpmn


def add(process, *nodes):
    for node in nodes:
        process[node.id] = node


def linear():
    s, t, e = start("S"), Task("T", "T", ""), end("E")
    p = Process("P", "P")
    add(p, s, t, e)
    connect(s, t, "f1")
    connect(t, e, "f2")
    return make_bpmn(p)


def generate(bpmn):
    visitor = CbmcBpmnVisitor()
    bpmn.accept(visitor)
    return visitor


def test_places_declared_for_start_events_and_flows():
    out = repr(generate(linear()))
    assert "_Bool start_S = 1;" in out
    assert "_Bool flow_f1 = 0;" in out
    assert "_Bool flow_f2 = 0;" in out
    assert "_Bool ended_P = 0;" in out


def test_one_transition_per_non_gateway_element():
    v = generate(linear())
    assert [t.element_id for t in v.transitions] == ["S", "T", "E"]


def test_start_event_transition():
    t = generate(linear()).transitions[0]
    assert t.enable == "!ended_P && (start_S)"
    assert t.body[0] == "start_S = 0;"
    assert "flow_f1 = 1;" in t.body


def test_task_transition_consumes_and_produces():
    t = generate(linear()).transitions[1]
    assert t.enable == "!ended_P && (flow_f1)"
    assert t.body[0] == "flow_f1 = 0;"
    assert t.body[-1] == "flow_f2 = 1;"


def test_end_event_sets_ended_flag():
    v = generate(linear())
    t = v.transitions[2]
    assert t.body == ["flow_f2 = 0;", "ended_P = 1;"]
    assert v.all_ended == "ended_P"


def test_all_ended_with_two_processes():
    procs = []
    for n in ("A", "B"):
        s, e = start(f"S{n}"), end(f"E{n}")
        p = Process(n, n)
        add(p, s, e)
        connect(s, e, f"f{n}")
        procs.append(p)
    v = generate(make_bpmn(*procs))
    assert v.all_ended == "ended_A && ended_B"


def test_intermediate_event():
    s, i, e = start("S"), IntermediateEvent("I", "I", "", "", "catch"), end("E")
    p = Process("P", "P")
    add(p, s, i, e)
    connect(s, i, "f1")
    connect(i, e, "f2")
    v = generate(make_bpmn(p))
    assert [t.element_id for t in v.transitions] == ["S", "I", "E"]


def test_occupied_check_once_per_transition():
    s, t, e = start("S"), Task("T", "T", ""), end("E")
    t2 = Task("T2", "T2", "")
    p = Process("P", "P")
    add(p, s, t, t2, e)
    connect(s, t, "f1")
    connect(t, t2, "f2")
    connect(t2, e, "f3")
    v = generate(make_bpmn(p))
    for tr in v.transitions[:-1]:
        assert sum("__CPROVER_assert" in line for line in tr.body) == 1


def test_exclusive_gateway_one_transition_per_flow():
    s, g = start("S"), ExclusiveGatewayNode("G", "G")
    t1, t2 = Task("T1", "T1", ""), Task("T2", "T2", "")
    e1, e2 = end("E1"), end("E2")
    p = Process("P", "P")
    add(p, s, g, t1, t2, e1, e2)
    connect(s, g, "f0")
    connect(g, t1, "fa", "x > 5")
    connect(g, t2, "fb")
    connect(t1, e1, "f3")
    connect(t2, e2, "f4")
    v = generate(make_bpmn(p))
    gw = [t for t in v.transitions if t.element_id.startswith("G->")]
    assert [t.element_id for t in gw] == ["G->fa", "G->fb"]
    assert gw[0].enable == "!ended_P && (flow_f0) && ((x > 5))"
    # default flow: taken only if the other condition fails
    assert gw[1].enable == "!ended_P && (flow_f0) && (!(x > 5))"
    assert gw[0].body[-1] == "flow_fa = 1;"
    assert gw[1].body[-1] == "flow_fb = 1;"


def test_exclusive_gateway_merge_uses_any_incoming():
    s, g1 = start("S"), ExclusiveGatewayNode("G1", "G1")
    t, m = Task("T", "T", ""), ExclusiveGatewayNode("M", "M")
    e = end("E")
    p = Process("P", "P")
    add(p, s, g1, t, m, e)
    connect(s, g1, "f0")
    connect(g1, t, "a", "x")
    connect(g1, m, "b", "!x")
    connect(t, m, "c")
    connect(m, e, "d")
    v = generate(make_bpmn(p))
    merge = [t for t in v.transitions if t.element_id == "M->d"][0]
    assert merge.enable == "!ended_P && (flow_b || flow_c)"
    assert merge.body[:2] == ["flow_b = 0;", "flow_c = 0;"]


def test_message_flow_places_and_guard():
    s1, t1, e1 = start("S1"), Task("T1", "T1", ""), end("E1")
    p1 = Process("P1", "P1")
    add(p1, s1, t1, e1)
    connect(s1, t1, "a")
    connect(t1, e1, "b")
    s2, c, e2 = start("S2"), IntermediateEvent("C", "C", "", "", "catch"), end("E2")
    p2 = Process("P2", "P2")
    add(p2, s2, c, e2)
    connect(s2, c, "c")
    connect(c, e2, "d")
    msg = MessageFlow("M", "M")
    msg.source_node, msg.target_node = t1, c
    t1.add_out_msg(msg)
    c.add_in_msg(msg)
    v = generate(make_bpmn(p1, p2))
    out = repr(v)
    assert "_Bool msg_M = 0;" in out
    task = [t for t in v.transitions if t.element_id == "T1"][0]
    assert task.body[-1] == "msg_M = 1;"
    assert any("__CPROVER_assert" in ln and "msg_M" in ln for ln in task.body)
    catch = [t for t in v.transitions if t.element_id == "C"][0]
    assert catch.enable == "!ended_P2 && (flow_c) && msg_M"
    assert "msg_M = 0;" in catch.body


def test_step_is_one_switch_without_loops():
    out = repr(generate(linear()))
    assert "void bpmn_step(void)" in out
    assert out.count("nondet_uint()") == 1
    assert "switch (choice)" in out
    assert "for (" not in out and "while" not in out
    assert out.count("__CPROVER_assume(choice < 3u);") == 1
    assert out.count("case ") == 3


def test_get_result_success():
    result = generate(linear()).get_result()
    assert isinstance(result, Success)
    assert "bpmn_step" in result.unwrap()


def test_parallel_gateway_is_an_error():
    s, g, e = start("S"), ParallelGatewayNode("G", "G"), end("E")
    p = Process("P", "P")
    add(p, s, g, e)
    connect(s, g, "f1")
    connect(g, e, "f2")
    result = generate(make_bpmn(p)).get_result()
    assert isinstance(result, Failure)
    err = result.failure()
    assert isinstance(err, BpmnCbmcUnsupportedElementError)
    assert err.element_id == "G"


def test_boundary_event_is_an_error():
    s, t, e = start("S"), Task("T", "T", ""), end("E")
    b = Task.BoundaryEvent("B", "B", "", "", "T")
    t.add_boundary_event(b)
    p = Process("P", "P")
    add(p, s, t, e)
    connect(s, t, "f1")
    connect(t, e, "f2")
    result = generate(make_bpmn(p)).get_result()
    assert isinstance(result, Failure)
    assert result.failure().element_id == "T"


@pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc not installed")
def test_generated_c_runs_through_cbmc(tmp_path):
    v = generate(linear())
    main = (
        "int main(void) {\n"
        "  for (unsigned i = 0; i < 3; i++) {\n"
        "    if (ended_P) break;\n"
        "    bpmn_step();\n"
        "  }\n"
        '  __CPROVER_assert(ended_P, "ends within 3 passes");\n'
        "  return 0;\n}\n"
    )
    src = tmp_path / "m.c"
    src.write_text(repr(v) + main)
    proc = subprocess.run(
        ["cbmc", str(src), "--unwind", "4"], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stdout
    assert "VERIFICATION SUCCESSFUL" in proc.stdout
