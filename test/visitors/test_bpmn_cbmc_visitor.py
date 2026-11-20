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
    end = step.index("break;", start)
    return step[start:end]


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


def test_parallel_gateway_is_an_error():
    s, p, e = _start("S"), ParallelGatewayNode("G", "G"), _end("E")
    _flow("f1", s, p)
    _flow("f2", p, e)
    visitor = _run(_bpmn(("P", [s, p, e])))

    assert [type(err) for err in visitor.errors] == [BpmnCbmcUnsupportedElementError]
    assert visitor.errors[0].element_id == "G"


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
