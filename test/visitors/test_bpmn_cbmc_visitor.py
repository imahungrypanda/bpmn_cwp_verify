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
from bpmncwpverify.core.error import BpmnCbmcUnsupportedError
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


def test_parallel_gateway_is_an_error():
    s, g, a, b = _start(), ParallelGatewayNode("G", "G"), _end("A"), _end("B")
    _link(s, g, "F1")
    _link(g, a, "Fa")
    _link(g, b, "Fb")
    result = _visit(_bpmn(("P", [s, g, a, b]))).result()
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, BpmnCbmcUnsupportedError)
    assert error.element_id == "G"


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
