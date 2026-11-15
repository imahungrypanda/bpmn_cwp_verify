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
    assert t.body[1:5] == ["{", "x = 1;", "}", "cwp_update_state();"]


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


def _body(visitor: CbmcGenVisitor, element_id: str) -> str:
    return "\n".join(_by_id(visitor, element_id)[0].body)


def test_fork_and_join():
    start, fork, join = (
        _start(),
        ParallelGatewayNode("F", "F", True),
        ParallelGatewayNode("J", "J"),
    )
    a, b, end = Task("A", "A", ""), Task("B", "B", ""), _end()
    _flow("f0", start, fork)
    _flow("fa", fork, a)
    _flow("fb", fork, b)
    _flow("ja", a, join)
    _flow("jb", b, join)
    _flow("f9", join, end)
    visitor = _run(_process("P", start))
    (f,) = _by_id(visitor, "F")
    assert f.enable == "!ended_P && (tok_f0)"
    assert f.body == [
        "tok_f0 = 0;",
        "token_clash = tok_fa || tok_fb;",
        "tok_fa = 1;",
        "tok_fb = 1;",
    ]
    (j,) = _by_id(visitor, "J")
    assert j.enable == "!ended_P && (tok_ja && tok_jb)"
    assert j.body[:2] == ["tok_ja = 0;", "tok_jb = 0;"]
    assert j.body[-1] == "tok_f9 = 1;"
    assert visitor.result() == Success(visitor)


def test_fork_with_loop_back_is_enabled_by_any_incoming():
    start, fork = _start(), ParallelGatewayNode("F", "F", True)
    a, b, end = Task("A", "A", ""), Task("B", "B", ""), _end()
    loop = ExclusiveGatewayNode("L", "L")
    _flow("f0", start, fork)
    _flow("fa", fork, a)
    _flow("fb", fork, b)
    _flow("fl", a, loop)
    _flow("back", loop, fork, "again")
    _flow("out", loop, end, "!again")
    visitor = _run(_process("P", start))
    (f,) = _by_id(visitor, "F")
    assert f.enable == "!ended_P && (tok_f0 || tok_back)"
    assert f.body[:2] == ["tok_f0 = 0;", "tok_back = 0;"]
    assert len(_by_id(visitor, "F")) == 1


def test_nested_parallel_gateways():
    start = _start()
    f1, f2 = (
        ParallelGatewayNode("F1", "F1", True),
        ParallelGatewayNode("F2", "F2", True),
    )
    j1, j2 = ParallelGatewayNode("J1", "J1"), ParallelGatewayNode("J2", "J2")
    a, b, c = Task("A", "A", ""), Task("B", "B", ""), Task("C", "C", "")
    end = _end()
    _flow("s", start, f1)
    _flow("o1", f1, f2)
    _flow("o2", f1, c)
    _flow("i1", f2, a)
    _flow("i2", f2, b)
    _flow("ja", a, j1)
    _flow("jb", b, j1)
    _flow("j1o", j1, j2)
    _flow("jc", c, j2)
    _flow("e", j2, end)
    visitor = _run(_process("P", start))
    assert _by_id(visitor, "F1")[0].enable == "!ended_P && (tok_s)"
    assert "tok_o1 = 1;" in _body(visitor, "F1") and "tok_o2 = 1;" in _body(
        visitor, "F1"
    )
    assert _by_id(visitor, "F2")[0].enable == "!ended_P && (tok_o1)"
    assert _by_id(visitor, "J1")[0].enable == "!ended_P && (tok_ja && tok_jb)"
    assert _by_id(visitor, "J2")[0].enable == "!ended_P && (tok_j1o && tok_jc)"
    assert visitor.result() == Success(visitor)


def _task_body(behavior: str) -> list[str]:
    start, task, end = _start(), Task("T", "T", behavior), _end()
    _flow("f1", start, task)
    _flow("f2", task, end)
    visitor = _run(_process("P", start))
    assert visitor.result() == Success(visitor)
    return _by_id(visitor, "T")[0].body


def test_behavior_assignments_then_cwp_update():
    body = _task_body("backpackOwner = sellerName\npaymentOwner = buyerName")
    assert body == [
        "tok_f1 = 0;",
        "{",
        "backpackOwner = sellerName;",
        "paymentOwner = buyerName;",
        "}",
        "cwp_update_state();",
        "token_clash = tok_f2;",
        "tok_f2 = 1;",
    ]


def test_empty_behavior_has_no_update():
    assert _task_body("") == ["tok_f1 = 0;", "token_clash = tok_f2;", "tok_f2 = 1;"]


def test_behavior_choice_assumes_guard_and_updates_after():
    body = _task_body(
        "if\n:: true -> terms = agreed\n:: x == 1 && y != 2 -> terms = failed\nfi"
    )
    text = "\n".join(body)
    assert "unsigned int choice_0 = nondet_uint();" in text
    assert "__CPROVER_assume(choice_0 < 2u);" in text
    assert "if (choice_0 == 0u) {\n__CPROVER_assume(true);\nterms = agreed;" in text
    assert "else if (choice_0 == 1u) {\n__CPROVER_assume(x == 1 && y != 2);" in text
    assert text.index("terms = failed;") < text.index("cwp_update_state();")
    assert text.count("nondet_uint()") == 1


def test_behavior_else_and_nested_if():
    body = "\n".join(
        _task_body(
            "if\n:: a > 1 -> if\n:: true -> x = 1\n:: true -> x = 2\nfi\n"
            ":: else -> x = 0\nfi"
        )
    )
    assert "choice_0" in body and "choice_1" in body
    assert body.count("nondet_uint()") == 2
    assert "__CPROVER_assume(!((a > 1)));" in body
    assert "x = 0;" in body and "x = 2;" in body


def test_behavior_unsupported_statement_is_an_error():
    start, task, end = _start(), Task("T", "T", "do\n:: true -> x = 1\nod"), _end()
    _flow("f1", start, task)
    _flow("f2", task, end)
    match _run(_process("P", start)).result():
        case Failure(BpmnCbmcUnsupportedElementError(element_id="T")):
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
        + "\nint x;\nvoid cwp_update_state(void) {}\n"
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


@pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc not installed")
def test_behavior_and_fork_run_through_cbmc(tmp_path):
    start, fork, join = (
        _start(),
        ParallelGatewayNode("F", "F", True),
        ParallelGatewayNode("J", "J"),
    )
    a = Task("A", "A", "if\n:: true -> x = 1\n:: true -> x = 2\nfi")
    b, end = Task("B", "B", "y = x"), _end()
    _flow("f0", start, fork)
    _flow("fa", fork, a)
    _flow("fb", fork, b)
    _flow("ja", a, join)
    _flow("jb", b, join)
    _flow("f9", join, end)
    visitor = _run(_process("P", start))
    program = (
        visitor.declarations().join(
            [
                "#include <stdbool.h>\nunsigned int nondet_uint(void);\n"
                "int x = 0, y = 0; int updates = 0;\n"
                "void cwp_update_state(void) { updates++; }\n",
                "",
            ]
        )
        + "int main(void) {\n  for (unsigned i = 0; i < 6; i++) {\n"
        + "    if (ended_P) break;\n"
        + visitor.pass_code()
        + '  }\n  __CPROVER_assert(ended_P, "finished");\n'
        + '  __CPROVER_assert(x >= 1 && x <= 2 && updates == 2, "state");\n'
        + "  return 0;\n}\n"
    )
    source = tmp_path / "m.c"
    source.write_text(program)
    run = subprocess.run(
        ["cbmc", str(source), "--unwind", "8"], capture_output=True, text=True
    )
    assert "VERIFICATION SUCCESSFUL" in run.stdout, run.stdout[-1500:]
