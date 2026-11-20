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
from bpmncwpverify.visitors.bpmn_cbmc_visitor import CWP_CHANGED_VAR, CbmcBpmnGenVisitor
from bpmncwpverify.visitors.cwp_cbmc_visitor import UPDATE_FUNC


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


def enabled(visitor: CbmcBpmnGenVisitor, label: str) -> str:
    lines = repr(visitor).splitlines()
    return lines[lines.index(f"/* {label} */") + 1]


def case_of(visitor: CbmcBpmnGenVisitor, label: str) -> str:
    lines = repr(visitor.transitions).splitlines()
    start = next(
        i for i, ln in enumerate(lines) if ln.strip().endswith(f"/* {label} */")
    )
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == "break;")
    return "\n".join(lines[start : end + 1])


def fork_join() -> CbmcBpmnGenVisitor:
    start = StartEvent("s", "s", "", "")
    fork = ParallelGatewayNode("fork", "fork")
    a = Task("a", "a", "")
    b = Task("b", "b", "")
    join = ParallelGatewayNode("join", "join")
    end = EndEvent("e", "e", "", "")
    flows = [
        connect(start, fork, "f1"),
        connect(fork, a, "f2"),
        connect(fork, b, "f3"),
        connect(a, join, "f4"),
        connect(b, join, "f5"),
        connect(join, end, "f6"),
    ]
    return run(make_process("p", [start, fork, a, b, join, end], flows))


def test_fork_starts_every_branch():
    visitor = fork_join()
    assert visitor.result() == Success(visitor)
    case = case_of(visitor, "fork")
    assert "tok_f1 = 0;" in case
    assert "tok_f2 = 1;" in case
    assert "tok_f3 = 1;" in case


def test_join_waits_for_every_incoming_flow():
    visitor = fork_join()
    assert "(tok_f4 && tok_f5)" in enabled(visitor, "join")
    case = case_of(visitor, "join")
    assert "tok_f4 = 0;" in case and "tok_f5 = 0;" in case
    assert "tok_f6 = 1;" in case


def test_fork_with_loop_back_is_enabled_by_any_incoming_flow():
    start = StartEvent("s", "s", "", "")
    fork = ParallelGatewayNode("fork", "fork")
    a = Task("a", "a", "")
    b = Task("b", "b", "")
    xor = ExclusiveGatewayNode("x", "x")
    end = EndEvent("e", "e", "", "")
    flows = [
        connect(start, fork, "f1"),
        connect(fork, a, "f2"),
        connect(fork, b, "f3"),
        connect(a, xor, "f4"),
        connect(xor, fork, "f5", "again == 1"),
        connect(xor, end, "f6", "again == 0"),
    ]
    flows.append(connect(b, end, "f7"))
    visitor = run(make_process("p", [start, fork, a, b, xor, end], flows))

    assert visitor.result() == Success(visitor)
    assert fork.is_fork
    assert "(tok_f1 || tok_f5)" in enabled(visitor, "fork")
    assert "&&" not in enabled(visitor, "fork")


def test_nested_parallel_gateways():
    start = StartEvent("s", "s", "", "")
    outer = ParallelGatewayNode("outer", "outer")
    inner = ParallelGatewayNode("inner", "inner")
    a = Task("a", "a", "")
    b = Task("b", "b", "")
    c = Task("c", "c", "")
    inner_join = ParallelGatewayNode("inner_join", "inner_join")
    outer_join = ParallelGatewayNode("outer_join", "outer_join")
    end = EndEvent("e", "e", "", "")
    flows = [
        connect(start, outer, "f1"),
        connect(outer, inner, "f2"),
        connect(outer, c, "f3"),
        connect(inner, a, "f4"),
        connect(inner, b, "f5"),
        connect(a, inner_join, "f6"),
        connect(b, inner_join, "f7"),
        connect(inner_join, outer_join, "f8"),
        connect(c, outer_join, "f9"),
        connect(outer_join, end, "f10"),
    ]
    visitor = run(
        make_process(
            "p",
            [start, outer, inner, a, b, c, inner_join, outer_join, end],
            flows,
        )
    )

    assert visitor.result() == Success(visitor)
    assert visitor.num_transitions == 9
    text = repr(visitor)
    assert "(tok_f6 && tok_f7)" in text
    assert "(tok_f8 && tok_f9)" in text


def test_parallel_gateway_without_outgoing_flow_is_an_error():
    start = StartEvent("s", "s", "", "")
    gw = ParallelGatewayNode("pg", "pg")
    visitor = run(make_process("p", [start, gw], [connect(start, gw, "f1")]))

    result = visitor.result()
    assert isinstance(result, Failure)
    error = result.failure()
    assert isinstance(error, BpmnCbmcUnsupportedElementError)
    assert error.element_id == "pg"


def task_with(behavior: str) -> CbmcBpmnGenVisitor:
    process, _, task, _ = start_task_end()
    task.behavior = behavior
    return run(process)


def task_case(visitor: CbmcBpmnGenVisitor) -> str:
    body = repr(visitor.transitions)
    return body[body.index("case 1:") : body.index("case 2:")]


def test_empty_behavior_does_not_update_cwp():
    visitor = task_with("")
    assert CWP_CHANGED_VAR + " = 1" not in task_case(visitor)


def test_assignment_behavior():
    case = task_case(task_with("backpackOwner = sellerName\npaymentOwner = buyerName"))
    assert "backpackOwner = sellerName;" in case
    assert "paymentOwner = buyerName;" in case
    assert case.index("paymentOwner") < case.index("tok_f2 = 1;")


def test_semicolon_and_skip():
    case = task_case(task_with("x = 1;\nskip\ny = 2; z = 3"))
    assert "x = 1;" in case and "y = 2;" in case and "z = 3;" in case
    assert "skip" not in case


def test_if_behavior_is_nondeterministic_choice_on_guards():
    case = task_case(
        task_with(
            "if\n:: true -> terms = agreed\n:: terms == pending -> terms = failed\nfi"
        )
    )
    assert "nondet_uint()" in case
    assert "__CPROVER_assume(1);" in case
    assert "__CPROVER_assume(terms == pending);" in case
    assert "terms = agreed;" in case and "terms = failed;" in case
    assert "for" not in case and "while" not in case


def test_comparisons_and_else():
    case = task_case(
        task_with("if\n:: sevNeed == discharge -> alert = yes\n:: else -> skip\nfi")
    )
    assert "__CPROVER_assume(sevNeed == discharge);" in case
    assert "__CPROVER_assume(!((sevNeed == discharge)));" in case
    assert "alert = yes;" in case


def test_guard_with_body_on_following_lines_and_nesting():
    case = task_case(
        task_with(
            "if\n"
            ":: a == 1 ->\n"
            "    if\n"
            "    :: true -> b = 1\n"
            "    :: true -> b = 2\n"
            "    fi\n"
            "    c = 3\n"
            ":: else -> d = 4\n"
            "fi"
        )
    )
    assert "b = 1;" in case and "b = 2;" in case
    assert "c = 3;" in case and "d = 4;" in case
    assert "choice_0" in case and "choice_1" in case


def test_assert_in_behavior():
    case = task_case(task_with("assert(sevNeed != expired)"))
    assert '__CPROVER_assert((sevNeed != expired), "assertion in t");' in case


def test_cwp_update_follows_behavior_once_per_pass():
    visitor = task_with("x = 1")
    case = task_case(visitor)
    assert f"{CWP_CHANGED_VAR} = 1;" in case
    assert case.index("x = 1;") < case.index(f"{CWP_CHANGED_VAR} = 1;")
    assert "cwp_update" not in case

    code = visitor.pass_code
    assert code.count(f"{UPDATE_FUNC}()") == 1
    assert code.index("switch") < code.index(f"if ({CWP_CHANGED_VAR}) {UPDATE_FUNC}();")


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
