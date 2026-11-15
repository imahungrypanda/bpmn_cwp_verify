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
from bpmncwpverify.visitors.bpmn_cbmc_visitor import (
    CbmcGenVisitor,
    ended_flag,
    token_place,
)


def _flow(bpmn_id: str, src: Node, dst: Node, expression: str = "") -> SequenceFlow:
    flow = SequenceFlow(bpmn_id, bpmn_id)
    flow.source_node = src
    flow.target_node = dst
    flow.expression = expression
    src.add_out_flow(flow)
    dst.add_in_flow(flow)
    return flow


def _msg(bpmn_id: str, src: Node, dst: Node) -> MessageFlow:
    msg = MessageFlow(bpmn_id, bpmn_id)
    msg.source_node = src
    msg.target_node = dst
    src.add_out_msg(msg)
    dst.add_in_msg(msg)
    return msg


def _start(bpmn_id: str = "S") -> StartEvent:
    return StartEvent(bpmn_id, bpmn_id, "", "")


def _end(bpmn_id: str = "E") -> EndEvent:
    return EndEvent(bpmn_id, bpmn_id, "", "")


def _process(pid: str, start: StartEvent) -> Process:
    process = Process(pid, pid)
    process[start.id] = start
    return process


def _run(*processes: Process) -> CbmcGenVisitor:
    bpmn = Bpmn()
    for process in processes:
        bpmn.processes[process.id] = process
    visitor = CbmcGenVisitor()
    bpmn.accept(visitor)
    return visitor


def _by_id(visitor: CbmcGenVisitor, element_id: str):
    return [t for t in visitor.transitions if t.element_id == element_id]


@pytest.fixture
def linear() -> CbmcGenVisitor:
    start, task, end = _start(), Task("T", "T", "x = 1"), _end()
    _flow("f1", start, task)
    _flow("f2", task, end)
    return _run(_process("P", start))


def test_start_event_has_initial_token(linear):
    assert f"static bool {token_place('S')} = 1;" in linear.declarations()
    assert f"static bool {token_place('f1')} = 0;" in linear.declarations()
    (t,) = _by_id(linear, "S")
    assert t.enable == f"!{ended_flag('P')} && ({token_place('S')})"
    assert t.body == [f"{token_place('S')} = 0;"] + [
        f"token_clash = {token_place('f1')};",
        f"{token_place('f1')} = 1;",
    ]


def test_task_clears_incoming_sets_outgoing(linear):
    (t,) = _by_id(linear, "T")
    assert t.enable == "!ended_P && (tok_f1)"
    assert t.body[0] == "tok_f1 = 0;"
    assert t.body[-1] == "tok_f2 = 1;"
    assert any("behavior of T" in line for line in t.body)


def test_end_event_ends_process(linear):
    (t,) = _by_id(linear, "E")
    assert t.body == ["tok_f2 = 0;", "ended_P = 1;"]
    assert linear.all_ended_expr() == "ended_P"
    assert "static bool ended_P = 0;" in linear.declarations()


def test_intermediate_event():
    start, mid, end = _start(), IntermediateEvent("I", "I", "", "", "catch"), _end()
    _flow("f1", start, mid)
    _flow("f2", mid, end)
    visitor = _run(_process("P", start))
    (t,) = _by_id(visitor, "I")
    assert t.enable == "!ended_P && (tok_f1)"
    assert t.body[-1] == "tok_f2 = 1;"
    assert visitor.result() == Success(visitor)


def test_exclusive_gateway_one_transition_per_flow():
    start, gw = _start(), ExclusiveGatewayNode("G", "G")
    a, b = _end("A"), _end("B")
    _flow("f0", start, gw)
    _flow("fa", gw, a, "x > 5")
    _flow("fb", gw, b, "x <= 5\n && y")
    visitor = _run(_process("P", start))
    ts = _by_id(visitor, "G")
    assert [t.enable for t in ts] == [
        "!ended_P && (tok_f0) && (x > 5)",
        "!ended_P && (tok_f0) && (x <= 5 && y)",
    ]
    assert ts[0].body == [
        "tok_f0 = 0;",
        "token_clash = tok_fa;",
        "tok_fa = 1;",
    ]
    assert ts[1].body[-1] == "tok_fb = 1;"


def test_exclusive_gateway_flow_without_expression_has_no_extra_condition():
    start, gw, end = _start(), ExclusiveGatewayNode("G", "G"), _end()
    _flow("f0", start, gw)
    _flow("f1", gw, end)
    (t,) = _by_id(_run(_process("P", start)), "G")
    assert t.enable == "!ended_P && (tok_f0)"


def test_merge_enabled_by_any_incoming_and_clears_all():
    start, gw, task, end = (
        _start(),
        ExclusiveGatewayNode("G", "G"),
        Task("T", "T", ""),
        _end(),
    )
    loop = ExclusiveGatewayNode("L", "L")
    _flow("f0", start, loop)
    _flow("f1", loop, task, "c")
    _flow("f2", task, gw)
    _flow("f3", gw, loop, "d")
    _flow("f4", gw, end, "!d")
    visitor = _run(_process("P", start))
    (t,) = _by_id(visitor, "L")[:1]
    assert t.enable.startswith("!ended_P && (tok_f0 || tok_f3)")
    assert t.body[:2] == ["tok_f0 = 0;", "tok_f3 = 0;"]
    # the loop is visited once
    assert len(_by_id(visitor, "L")) == 1


def test_message_flow_between_processes():
    s1, t1, e1 = _start("S1"), Task("T1", "T1", ""), _end("E1")
    s2, t2, e2 = _start("S2"), Task("T2", "T2", ""), _end("E2")
    _flow("a1", s1, t1)
    _flow("a2", t1, e1)
    _flow("b1", s2, t2)
    _flow("b2", t2, e2)
    _msg("m", t1, t2)
    visitor = _run(_process("P1", s1), _process("P2", s2))
    (sender,) = _by_id(visitor, "T1")
    (receiver,) = _by_id(visitor, "T2")
    assert "tok_m = 1;" in sender.body
    assert receiver.enable == "!ended_P2 && (tok_b1) && (tok_m)"
    assert receiver.body[:2] == ["tok_b1 = 0;", "tok_m = 0;"]
    assert "static bool tok_m = 0;" in visitor.declarations()
    assert visitor.all_ended_expr() == "ended_P1 && ended_P2"
    assert visitor.declarations().count("tok_m ") == 1


def test_message_only_start_event_waits_for_message():
    s1, t1, e1 = _start("S1"), Task("T1", "T1", ""), _end("E1")
    s2, e2 = _start("S2"), _end("E2")
    _flow("a1", s1, t1)
    _flow("a2", t1, e1)
    _flow("b", s2, e2)
    _msg("m", t1, s2)
    visitor = _run(_process("P1", s1), _process("P2", s2))
    (t,) = _by_id(visitor, "S2")
    assert t.enable == "!ended_P2 && (tok_m)"
    assert "static bool tok_m = 0;" in visitor.declarations()
    assert "tok_S2" not in visitor.declarations()


def test_pass_picks_exactly_one_transition(linear):
    code = linear.pass_code()
    assert code.count("nondet_uint()") == 1
    assert "__CPROVER_assume(transition < 3u);" in code
    assert code.count("switch (transition)") == 1
    for i in range(3):
        assert f"case {i}u:" in code
    assert code.count("__CPROVER_assume(!ended_P") == 3
    assert "for" not in code and "while" not in code
    assert code.count("__CPROVER_assert(") == 1


def test_any_enabled_expr(linear):
    expr = linear.any_enabled_expr()
    assert expr.count("||") == 2
    assert CbmcGenVisitor().any_enabled_expr() == "false"
    assert CbmcGenVisitor().all_ended_expr() == "true"


def test_parallel_gateway_is_an_error():
    start, gw, end = _start(), ParallelGatewayNode("PG", "PG"), _end()
    _flow("f0", start, gw)
    _flow("f1", gw, end)
    visitor = _run(_process("P", start))
    match visitor.result():
        case Failure(BpmnCbmcUnsupportedElementError(element_id="PG")):
            pass
        case other:
            pytest.fail(f"unexpected {other}")


def test_boundary_event_is_an_error():
    start, task, end = _start(), Task("T", "T", ""), _end()
    boundary = Task.BoundaryEvent("B", "B", "", "", "T")
    task.add_boundary_event(boundary)
    _flow("f0", start, task)
    _flow("f1", task, end)
    visitor = _run(_process("P", start))
    match visitor.result():
        case Failure(BpmnCbmcUnsupportedElementError(element_id="B")):
            pass
        case other:
            pytest.fail(f"unexpected {other}")


@pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc not installed")
def test_generated_c_runs_through_cbmc(tmp_path, linear):
    program = (
        repr(linear).split("\n\n", 1)[0]
        + "\n"
        + linear.declarations()
        + "\nint main(void) {\n"
        + "  for (unsigned i = 0; i < 3; i++) {\n"
        + "    if (ended_P) break;\n"
        + linear.pass_code()
        + '  }\n  __CPROVER_assert(ended_P, "finished");\n  return 0;\n}\n'
    )
    source = tmp_path / "m.c"
    source.write_text(program)
    run = subprocess.run(
        ["cbmc", str(source), "--unwind", "5"], capture_output=True, text=True
    )
    assert run.returncode == 0, run.stdout
    assert "VERIFICATION SUCCESSFUL" in run.stdout
