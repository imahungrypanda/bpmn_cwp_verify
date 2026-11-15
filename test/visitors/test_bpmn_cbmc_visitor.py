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
from bpmncwpverify.core.error import BpmnCbmcUnsupportedElementError
from bpmncwpverify.visitors.bpmn_cbmc_visitor import CbmcGenVisitor


def start(id="Start"):
    return StartEvent(id, id, "", "")


def end(id="End"):
    return EndEvent(id, id, "", "")


def inter(id, type_="catch"):
    return IntermediateEvent(id, id, "", "", type_)


def task(id):
    return Task(id, id, "")


def connect(src: Node, dst: Node, expression="") -> SequenceFlow:
    flow = SequenceFlow(f"Flow_{src.id}_{dst.id}", "")
    flow.source_node = src
    flow.target_node = dst
    flow.expression = expression
    src.add_out_flow(flow)
    dst.add_in_flow(flow)
    return flow


def message(src: Node, dst: Node) -> MessageFlow:
    flow = MessageFlow(f"Msg_{src.id}_{dst.id}", "")
    flow.source_node = src
    flow.target_node = dst
    src.add_out_msg(flow)
    dst.add_in_msg(flow)
    return flow


def make_process(id, nodes) -> Process:
    process = Process(id, id)
    for node in nodes:
        process[node.id] = node
    return process


def generate(*processes) -> CbmcGenVisitor:
    bpmn = Bpmn()
    for process in processes:
        bpmn.processes[process.id] = process
    visitor = CbmcGenVisitor()
    bpmn.accept(visitor)
    return visitor


def linear():
    s, t, e = start(), task("Task"), end()
    connect(s, t)
    connect(t, e)
    return make_process("P", [s, t, e])


def labels(visitor):
    return [t.label for t in visitor.transitions]


def test_start_event_place_is_initially_marked():
    out = repr(generate(linear()))
    assert "bool Start = 1;" in out
    assert "bool Task_FROM_Start = 0;" in out
    assert "bool End_FROM_Task = 0;" in out


def test_one_transition_per_element():
    visitor = generate(linear())
    assert labels(visitor) == ["Start", "Task", "End"]
    assert visitor.transitions[0].enable == "(Start)"
    assert visitor.transitions[1].enable == "(Task_FROM_Start)"
    assert visitor.transitions[1].body[0] == "Task_FROM_Start = 0;"
    assert "Task_FROM_Start = 1;" in visitor.transitions[0].body


def test_task_behavior_placeholder():
    visitor = generate(linear())
    assert "/* behavior of Task */" in visitor.transitions[1].body


def test_end_event_ends_process():
    visitor = generate(linear())
    assert "P_ended = 1;" in visitor.transitions[2].body
    assert visitor.all_ended == "P_ended"
    assert "bool P_ended = 0;" in repr(visitor)


def test_all_ended_covers_every_process():
    def proc(id):
        s, e = start(f"S{id}"), end(f"E{id}")
        connect(s, e)
        return make_process(id, [s, e])

    assert generate(proc("A"), proc("B")).all_ended == "A_ended && B_ended"


def test_intermediate_event():
    s, i, e = start(), inter("Catch"), end()
    connect(s, i)
    connect(i, e)
    visitor = generate(make_process("P", [s, i, e]))
    assert labels(visitor) == ["Start", "Catch", "End"]


def test_merge_of_flows_uses_or():
    s, a, b, t, e = start(), task("A"), task("B"), task("T"), end()
    g = ExclusiveGatewayNode("G", "G")
    connect(s, g)
    connect(g, a, "x > 1")
    connect(g, b, "x <= 1")
    connect(a, t)
    connect(b, t)
    connect(t, e)
    visitor = generate(make_process("P", [s, g, a, b, t, e]))
    join = next(t for t in visitor.transitions if t.label == "T")
    assert join.enable == "(T_FROM_A || T_FROM_B)"
    assert "T_FROM_A = 0;" in join.body
    assert "T_FROM_B = 0;" in join.body
    # each node is generated once even though it is reached twice
    assert labels(visitor).count("T") == 1


def test_exclusive_gateway_transition_per_flow():
    s, a, b, e = start(), task("A"), task("B"), end()
    g = ExclusiveGatewayNode("G", "G")
    connect(s, g)
    connect(g, a, "x > 1")
    connect(g, b, "x <= 1")
    connect(a, e)
    connect(b, e)
    visitor = generate(make_process("P", [s, g, a, b, e]))
    by_label = {t.label: t for t in visitor.transitions}
    to_a = by_label["G -> Flow_G_A"]
    assert to_a.enable == "(G_FROM_Start) && (x > 1)"
    assert "G_FROM_Start = 0;" in to_a.body
    assert "A_FROM_G = 1;" in to_a.body
    assert "B_FROM_G = 1;" not in to_a.body
    assert by_label["G -> Flow_G_B"].enable == "(G_FROM_Start) && (x <= 1)"


def test_exclusive_gateway_stuck_token_fails():
    s, a, b, e = start(), task("A"), task("B"), end()
    g = ExclusiveGatewayNode("G", "G")
    connect(s, g)
    connect(g, a, "x > 1")
    connect(g, b, "x <= 1")
    connect(a, e)
    connect(b, e)
    visitor = generate(make_process("P", [s, g, a, b, e]))
    stuck = next(t for t in visitor.transitions if t.label == "G stuck")
    assert stuck.enable == "(G_FROM_Start) && !((x > 1) || (x <= 1))"
    assert "__CPROVER_assert(0," in stuck.body[0]


def test_exclusive_gateway_flow_without_condition_is_open():
    s, a, e = start(), task("A"), end()
    g = ExclusiveGatewayNode("G", "G")
    connect(s, g)
    connect(g, a)
    connect(a, e)
    visitor = generate(make_process("P", [s, g, a, e]))
    assert visitor.transitions[1].enable == "(G_FROM_Start) && (1)"


def test_message_flow():
    s1, t1, e1 = start("S1"), task("T1"), end("E1")
    connect(s1, t1)
    connect(t1, e1)
    s2, c2, e2 = start("S2"), inter("C2"), end("E2")
    connect(s2, c2)
    connect(c2, e2)
    message(t1, c2)
    visitor = generate(make_process("A", [s1, t1, e1]), make_process("B", [s2, c2, e2]))
    by_label = {t.label: t for t in visitor.transitions}
    assert by_label["C2"].enable == "(C2_FROM_S2) && (C2_FROM_T1)"
    assert "C2_FROM_T1 = 0;" in by_label["C2"].body
    assert "C2_FROM_T1 = 1;" in by_label["T1"].body
    assert "bool C2_FROM_T1 = 0;" in repr(visitor)


def test_token_clash_checked_once_per_pass():
    s, t, e = start(), task("T"), end()
    a, b = task("A"), task("B")
    connect(s, t)
    connect(t, a)
    connect(t, b)
    connect(a, e)
    connect(b, e)
    visitor = generate(make_process("P", [s, t, a, b, e]))
    t_body = next(t for t in visitor.transitions if t.label == "T").body
    assert "token_clash = A_FROM_T || B_FROM_T;" in t_body
    assert repr(visitor).count("__CPROVER_assert(!token_clash") == 1


def test_step_is_a_single_dispatch_without_loop():
    out = repr(generate(linear()))
    assert "nondet_uint()" in out
    assert "__CPROVER_assume(transition < 3u);" in out
    assert "switch (transition)" in out
    for keyword in ("for (", "while", "do {"):
        assert keyword not in out
    assert out.count("__CPROVER_assume(") == 4  # bound + one per transition


def test_parallel_gateway_is_an_error():
    s, g, e = start(), ParallelGatewayNode("PG", "PG"), end()
    connect(s, g)
    connect(g, e)
    visitor = generate(make_process("P", [s, g, e]))
    result = visitor.result()
    assert isinstance(result, Failure)
    err = result.failure()
    assert isinstance(err, BpmnCbmcUnsupportedElementError)
    assert err.element_id == "PG"


def test_boundary_event_is_an_error():
    s, t, e = start(), task("T"), end()
    connect(s, t)
    connect(t, e)
    t.add_boundary_event(Task.BoundaryEvent("B", "B", "", "", "T"))
    visitor = generate(make_process("P", [s, t, e]))
    assert isinstance(visitor.result(), Failure)


def test_result_success():
    assert isinstance(generate(linear()).result(), Success)


@pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc not installed")
def test_generated_c_runs_in_cbmc(tmp_path):
    s, a, b, e = start(), task("A"), task("B"), end()
    g = ExclusiveGatewayNode("G", "G")
    connect(s, g)
    connect(g, a, "x > 1")
    connect(g, b, "x <= 1")
    connect(a, e)
    connect(b, e)
    visitor = generate(make_process("P", [s, g, a, b, e]))
    program = (
        "#include <stdbool.h>\nint x = 0;\n" + repr(visitor) + "int main(void) {\n"
        "  for (int i = 0; i < 6 && !(" + visitor.all_ended + "); i++) bpmn_step();\n"
        '  __CPROVER_assert(P_ended, "ended");\n}\n'
    )
    src = tmp_path / "model.c"
    src.write_text(program)
    run = subprocess.run(
        ["cbmc", str(src), "--unwind", "7"], capture_output=True, text=True
    )
    assert "VERIFICATION SUCCESSFUL" in run.stdout, run.stdout
