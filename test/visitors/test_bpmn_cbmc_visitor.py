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
from bpmncwpverify.visitors.bpmn_cbmc_visitor import CbmcBpmnGenVisitor


def connect(src: Node, dst: Node, id: str, expr: str = "") -> SequenceFlow:
    flow = SequenceFlow(id, id)
    flow.source_node = src
    flow.target_node = dst
    flow.expression = expr
    src.add_out_flow(flow)
    dst.add_in_flow(flow)
    return flow


def message(src: Node, dst: Node, id: str) -> MessageFlow:
    msg = MessageFlow(id, id)
    msg.source_node = src
    msg.target_node = dst
    src.add_out_msg(msg)
    dst.add_in_msg(msg)
    return msg


def make_process(id: str, nodes: list[Node], flows: list[SequenceFlow]) -> Process:
    process = Process(id, id)
    for item in [*nodes, *flows]:
        process[item.id] = item
    return process


def run(*processes: Process) -> CbmcBpmnGenVisitor:
    bpmn = Bpmn()
    for process in processes:
        bpmn.processes[process.id] = process
    visitor = CbmcBpmnGenVisitor()
    bpmn.accept(visitor)
    return visitor


def start_task_end() -> tuple[Process, StartEvent, Task, EndEvent]:
    start = StartEvent("s", "s", "", "")
    task = Task("t", "t", "")
    end = EndEvent("e", "e", "", "")
    flows = [connect(start, task, "f1"), connect(task, end, "f2")]
    return make_process("p", [start, task, end], flows), start, task, end


def test_start_task_end_places_and_transitions():
    process, *_ = start_task_end()
    visitor = run(process)
    places = repr(visitor.places)

    assert "int tok_s = 1;" in places
    assert "int tok_f1 = 0;" in places
    assert "int tok_f2 = 0;" in places
    assert visitor.num_transitions == 3
    enables = repr(visitor.enables)
    assert "#define ENABLED_0 ((tok_s))" in enables
    assert "#define ENABLED_1 ((tok_f1))" in enables
    assert "#define ENABLED_2 ((tok_f2))" in enables
    assert visitor.result() == Success(visitor)


def test_transition_body_clears_incoming_and_sets_outgoing():
    process, *_ = start_task_end()
    body = repr(run(process).transitions)

    assert "case 1:" in body
    case1 = body[body.index("case 1:") : body.index("case 2:")]
    assert "__CPROVER_assume(ENABLED_1);" in case1
    assert "tok_f1 = 0;" in case1
    assert "occupied = tok_f2;" in case1
    assert "tok_f2 = 1;" in case1
    assert case1.index("tok_f1 = 0;") < case1.index("tok_f2 = 1;")
    assert "break;" in case1


def test_end_event_ends_process():
    process, *_ = start_task_end()
    visitor = run(process)
    body = repr(visitor.transitions)
    case2 = body[body.index("case 2:") :]

    assert "ended_p = 1;" in case2
    assert "int ended_p = 0;" in repr(visitor.ends)
    assert visitor.all_ended == "ended_p"


def test_all_ended_with_several_processes():
    p1, *_ = start_task_end()
    s = StartEvent("s2", "s2", "", "")
    e = EndEvent("e2", "e2", "", "")
    p2 = make_process("q", [s, e], [connect(s, e, "g1")])
    visitor = run(p1, p2)

    assert visitor.all_ended == "ended_p && ended_q"
    assert visitor.num_transitions == 5


def test_pass_picks_exactly_one_transition_without_loops():
    process, *_ = start_task_end()
    code = run(process).pass_code

    assert code.count("nondet_uint()") == 1
    assert "switch (choice)" in code
    assert code.count("case ") == 3
    assert "default:" in code
    assert "for (" not in code and "while" not in code
    # the occupied-place check happens once, after the switch
    assert code.count("__CPROVER_assert") == 1
    assert code.index("__CPROVER_assert") > code.rindex("break;")


def test_exclusive_gateway_has_transition_per_flow():
    start = StartEvent("s", "s", "", "")
    gw = ExclusiveGatewayNode("g", "g")
    a = EndEvent("a", "a", "", "")
    b = EndEvent("b", "b", "", "")
    flows = [
        connect(start, gw, "f0"),
        connect(gw, a, "fa", "x > 5"),
        connect(gw, b, "fb", "x <= 5"),
    ]
    visitor = run(make_process("p", [start, gw, a, b], flows))
    enables = repr(visitor.enables)

    assert visitor.num_transitions == 5
    assert "#define ENABLED_1 ((tok_f0) && (x > 5))" in enables
    assert "#define ENABLED_2 ((tok_f0) && (x <= 5))" in enables
    body = repr(visitor.transitions)
    case1 = body[body.index("case 1:") : body.index("case 2:")]
    assert "tok_fa = 1;" in case1 and "tok_fb" not in case1
    assert visitor.result() == Success(visitor)


def test_exclusive_gateway_merge_without_condition():
    start = StartEvent("s", "s", "", "")
    t = Task("t", "t", "")
    gw = ExclusiveGatewayNode("g", "g")
    end = EndEvent("e", "e", "", "")
    flows = [
        connect(start, gw, "f0"),
        connect(t, gw, "f1"),
        connect(gw, end, "f2"),
    ]
    t.add_in_flow(flows[0])
    visitor = run(make_process("p", [start, t, gw, end], flows))

    assert "(tok_f0 || tok_f1)" in repr(visitor.enables)


def test_exclusive_gateway_flow_without_condition_is_error():
    start = StartEvent("s", "s", "", "")
    gw = ExclusiveGatewayNode("g", "g")
    a = EndEvent("a", "a", "", "")
    b = EndEvent("b", "b", "", "")
    flows = [
        connect(start, gw, "f0"),
        connect(gw, a, "fa", "x > 5"),
        connect(gw, b, "fb"),
    ]
    visitor = run(make_process("p", [start, gw, a, b], flows))

    result = visitor.result()
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), BpmnCbmcUnsupportedElementError)


def test_intermediate_event_is_a_transition():
    start = StartEvent("s", "s", "", "")
    ev = IntermediateEvent("i", "i", "", "", "catch")
    end = EndEvent("e", "e", "", "")
    flows = [connect(start, ev, "f1"), connect(ev, end, "f2")]
    visitor = run(make_process("p", [start, ev, end], flows))

    assert visitor.num_transitions == 3
    assert "#define ENABLED_1 ((tok_f1))" in repr(visitor.enables)


def test_message_flow_is_a_place_and_must_be_present():
    s1 = StartEvent("s1", "s1", "", "")
    send = IntermediateEvent("send", "send", "", "", "send")
    e1 = EndEvent("e1", "e1", "", "")
    s2 = StartEvent("s2", "s2", "", "")
    catch = IntermediateEvent("catch", "catch", "", "", "catch")
    e2 = EndEvent("e2", "e2", "", "")
    p1 = make_process(
        "p1", [s1, send, e1], [connect(s1, send, "a1"), connect(send, e1, "a2")]
    )
    p2 = make_process(
        "p2", [s2, catch, e2], [connect(s2, catch, "b1"), connect(catch, e2, "b2")]
    )
    message(send, catch, "m1")
    visitor = run(p1, p2)

    assert "int tok_m1 = 0;" in repr(visitor.places)
    enables = repr(visitor.enables)
    assert "((tok_a1))" in enables
    assert "((tok_b1) && (tok_m1))" in enables
    body = repr(visitor.transitions)
    send_case = body[body.index("send") : body.index("case 3")]
    assert "tok_m1 = 1;" in send_case and "tok_a2 = 1;" in send_case
    catch_case = body[body.index("/* catch */") :]
    assert "tok_m1 = 0;" in catch_case.split("case")[0]


def test_ids_are_made_safe_for_c():
    start = StartEvent("1-s", "s", "", "")
    end = EndEvent("e", "e", "", "")
    visitor = run(make_process("p", [start, end], [connect(start, end, "f.1")]))

    assert "tok__1_s" in repr(visitor.places)
    assert "tok_f_1" in repr(visitor.places)


def test_node_reachable_twice_is_generated_once():
    start = StartEvent("s", "s", "", "")
    gw = ExclusiveGatewayNode("g", "g")
    t = Task("t", "t", "")
    end = EndEvent("e", "e", "", "")
    flows = [
        connect(start, gw, "f0"),
        connect(gw, t, "f1", "x > 0"),
        connect(gw, end, "f2", "x <= 0"),
        connect(t, gw, "f3"),
    ]
    flows[3].is_leaf = True
    visitor = run(make_process("p", [start, gw, t, end], flows))

    assert visitor.num_transitions == 5


def test_parallel_gateway_is_an_error():
    start = StartEvent("s", "s", "", "")
    gw = ParallelGatewayNode("pg", "pg")
    end = EndEvent("e", "e", "", "")
    flows = [connect(start, gw, "f1"), connect(gw, end, "f2")]
    visitor = run(make_process("p", [start, gw, end], flows))

    result = visitor.result()
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, BpmnCbmcUnsupportedElementError)
    assert error.element_id == "pg"


def test_boundary_event_is_an_error():
    start = StartEvent("s", "s", "", "")
    task = Task("t", "t", "")
    end = EndEvent("e", "e", "", "")
    boundary = Task.BoundaryEvent("b", "b", "", "", "t")
    task.add_boundary_event(boundary)
    flows = [connect(start, task, "f1"), connect(task, end, "f2")]
    visitor = run(make_process("p", [start, task, end], flows))

    result = visitor.result()
    assert isinstance(result, Failure)
    assert result.failure().element_id == "b"
