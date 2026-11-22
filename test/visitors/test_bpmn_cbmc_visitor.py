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


def test_task_behavior_is_placeholder():
    s, t, e = start(), Task("T", "T", "x = 1"), end()
    seq(s, t, "a")
    seq(t, e, "b")
    v = generate(process("P", s, t, e))
    assert "behavior of T" in str(v.step)


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


def test_parallel_gateway_is_unsupported():
    s, g, e = start(), ParallelGatewayNode("G", "G"), end()
    seq(s, g, "a")
    seq(g, e, "b")
    assert assert_unsupported(process("P", s, g, e)).element_id == "G"


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
