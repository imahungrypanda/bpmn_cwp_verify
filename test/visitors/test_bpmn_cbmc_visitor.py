import shutil
import subprocess
from pathlib import Path

import pytest
from returns.result import Failure, Success
from returns.unsafe import unsafe_perform_io

from bpmncwpverify.builder.cbmc_builder import CbmcBuilder
from bpmncwpverify.core.accessmethods import bpmnmethods
from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
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
from bpmncwpverify.core.error import (
    BpmnCbmcUnsupportedElementError,
    BpmnSeqFlowNoExprError,
    FeelCbmcUnsupportedError,
)
from bpmncwpverify.core.feel import parse_behavior, parse_expression
from bpmncwpverify.core.state import State
from bpmncwpverify.util.file import element_tree_from_string
from bpmncwpverify.visitors.bpmn_cbmc_visitor import CbmcBpmnGenVisitor

FEEL = "./test/resources/feel/"


def seq(src: Node, dst: Node, expr: str = "") -> SequenceFlow:
    flow = SequenceFlow(f"{src.id}_{dst.id}", "flow")
    flow.source_node, flow.target_node = src, dst
    flow.expression = expr
    src.add_out_flow(flow)
    dst.add_in_flow(flow)
    return flow


def msg(src: Node, dst: Node) -> MessageFlow:
    flow = MessageFlow(f"m_{src.id}_{dst.id}", "msg")
    flow.source_node, flow.target_node = src, dst
    src.add_out_msg(flow)
    dst.add_in_msg(flow)
    return flow


def start(id: str = "S") -> StartEvent:
    return StartEvent(id, id, "", "")


def end(id: str = "E") -> EndEvent:
    return EndEvent(id, id, "", "")


def catch(id: str) -> IntermediateEvent:
    return IntermediateEvent(id, id, "", "", "catch")


def make_bpmn(*processes: tuple[str, list[Node]]) -> Bpmn:
    bpmn = Bpmn()
    for pid, nodes in processes:
        process = Process(pid, pid)
        for node in nodes:
            process[node.id] = node
        bpmn.processes[pid] = process
    return bpmn


def generate(bpmn: Bpmn) -> CbmcBpmnGenVisitor:
    visitor = CbmcBpmnGenVisitor()
    bpmn.accept(visitor)
    return visitor


def linear() -> Bpmn:
    s, t, e = start(), Task("T", "T", ""), end()
    seq(s, t)
    seq(t, e)
    return make_bpmn(("P", [s, t, e]))


def test_start_task_end():
    visitor = generate(linear())
    code = repr(visitor)
    assert visitor.result() == Success(code)
    assert visitor.process_ids == ["P"]
    assert "static unsigned char S = 0;" in code
    assert "static unsigned char T_FROM_S = 0;" in code
    assert "static unsigned char E_FROM_T = 0;" in code
    assert "static bool S_step(void)" in code
    assert "if (!((hasToken(S)))) return false;" in code
    assert "static void T_BehaviorModel(void)" in code
    assert "T_BehaviorModel();" in code
    assert "consumeToken(T_FROM_S);" in code
    assert "putToken(E_FROM_T);" in code
    assert "P_done = true;" in code
    assert "bool P_step(void)" in code
    assert "void P_init(void)" in code
    assert "putToken(S);" in code


def test_start_with_incoming_flow_not_initialised():
    s, e = start(), end()
    seq(s, e)
    visitor = generate(make_bpmn(("P", [s, e])))
    init = repr(visitor.inits)
    assert "putToken(S);" in init


def test_message_start_event_waits_for_message():
    sender, send_end = start("S1"), end("E1")
    seq(sender, send_end)
    receiver, recv_end = start("S2"), end("E2")
    seq(receiver, recv_end)
    msg(sender, receiver)
    visitor = generate(
        make_bpmn(("P1", [sender, send_end]), ("P2", [receiver, recv_end]))
    )
    code = repr(visitor)
    assert "static unsigned char S2_FROM_S1 = 0;" in code
    assert "hasToken(S2_FROM_S1)" in code
    assert "putToken(S2_FROM_S1);" in code
    assert "putToken(S2);" not in code
    assert visitor.process_ids == ["P1", "P2"]


def test_intermediate_catch_needs_flow_and_message():
    s, c, e = start(), catch("C"), end()
    seq(s, c)
    seq(c, e)
    other = start("O")
    other_end = end("OE")
    seq(other, other_end)
    msg(other, c)
    visitor = generate(make_bpmn(("P", [s, c, e]), ("Q", [other, other_end])))
    code = repr(visitor)
    assert "(hasToken(C_FROM_S)) && (hasToken(C_FROM_O))" in code
    assert "consumeToken(C_FROM_O);" in code
    assert visitor.errors == []


def test_intermediate_throw_sends_message():
    s, t, e = start(), IntermediateEvent("T", "T", "", "", "throw"), end()
    seq(s, t)
    seq(t, e)
    r, re_ = start("R"), end("RE")
    seq(r, re_)
    msg(t, r)
    code = repr(generate(make_bpmn(("P", [s, t, e]), ("Q", [r, re_]))))
    assert "putToken(R_FROM_T);" in code


def test_exclusive_gateway_merge_and_choice():
    s, g, a, b, m, e = (
        start(),
        ExclusiveGatewayNode("G", "G"),
        Task("A", "A", ""),
        Task("B", "B", ""),
        ExclusiveGatewayNode("M", "M"),
        end(),
    )
    seq(s, g)
    seq(g, a, "x > 1")
    seq(g, b, "x\n<= 1")
    seq(a, m)
    seq(b, m)
    seq(m, e, "true")
    visitor = generate(make_bpmn(("P", [s, g, a, b, m, e])))
    code = repr(visitor)
    assert visitor.errors == []
    assert "bool guard0 = (x > 1);" in code
    assert "bool guard1 = (x <= 1);" in code
    assert "No viable path to take" in code
    assert "__CPROVER_assume((pick == 0 && guard0) || (pick == 1 && guard1));" in code
    assert "if (pick == 0) putToken(A_FROM_G);" in code
    assert "if (pick == 1) putToken(B_FROM_G);" in code
    # merge gateway: either incoming token enables it
    assert "(hasToken(M_FROM_A) || hasToken(M_FROM_B))" in code
    # each element is generated once even though it is reachable twice
    assert code.count("static bool M_step(void)") == 1


def test_gateway_flow_without_expression_is_an_error():
    s, g, a, e = start(), ExclusiveGatewayNode("G", "G"), Task("A", "A", ""), end()
    seq(s, g)
    seq(g, a)
    seq(a, e)
    visitor = generate(make_bpmn(("P", [s, g, a, e])))
    assert isinstance(visitor.errors[0], BpmnSeqFlowNoExprError)
    assert isinstance(visitor.result(), Failure)


def fork_join() -> Bpmn:
    s, f, a, b, j, e = (
        start(),
        ParallelGatewayNode("F", "F"),
        Task("A", "A", ""),
        Task("B", "B", ""),
        ParallelGatewayNode("J", "J"),
        end(),
    )
    seq(s, f)
    seq(f, a)
    seq(f, b)
    seq(a, j)
    seq(b, j)
    seq(j, e)
    return make_bpmn(("P", [s, f, a, b, j, e]))


def test_parallel_fork_and_join():
    visitor = generate(fork_join())
    code = repr(visitor)
    assert visitor.errors == []
    assert "if (!((hasToken(F_FROM_S)))) return false;" in code
    assert "putToken(A_FROM_F);" in code
    assert "putToken(B_FROM_F);" in code
    assert "if (!((hasToken(J_FROM_A) && hasToken(J_FROM_B)))) return false;" in code
    assert "consumeToken(J_FROM_A);" in code
    assert "consumeToken(J_FROM_B);" in code
    assert "putToken(E_FROM_J);" in code
    assert code.count("static bool J_step(void)") == 1


def test_nested_parallel_gateways():
    s, f1, f2, a, b, c, j2, j1, e = (
        start(),
        ParallelGatewayNode("F1", "F1"),
        ParallelGatewayNode("F2", "F2"),
        Task("A", "A", ""),
        Task("B", "B", ""),
        Task("C", "C", ""),
        ParallelGatewayNode("J2", "J2"),
        ParallelGatewayNode("J1", "J1"),
        end(),
    )
    seq(s, f1)
    seq(f1, f2)
    seq(f1, c)
    seq(f2, a)
    seq(f2, b)
    seq(a, j2)
    seq(b, j2)
    seq(j2, j1)
    seq(c, j1)
    seq(j1, e)
    visitor = generate(make_bpmn(("P", [s, f1, f2, a, b, c, j2, j1, e])))
    code = repr(visitor)
    assert visitor.errors == []
    assert "putToken(F2_FROM_F1);" in code
    assert "putToken(C_FROM_F1);" in code
    assert "hasToken(J2_FROM_A) && hasToken(J2_FROM_B)" in code
    assert "hasToken(J1_FROM_J2) && hasToken(J1_FROM_C)" in code


def test_parallel_gateway_with_message_is_an_error():
    s, p, e = start(), ParallelGatewayNode("PG", "PG"), end()
    seq(s, p)
    seq(p, e)
    o, oe = start("O"), end("OE")
    seq(o, oe)
    msg(o, p)
    visitor = generate(make_bpmn(("P", [s, p, e]), ("Q", [o, oe])))
    error = visitor.result().failure()
    assert isinstance(error, BpmnCbmcUnsupportedElementError)
    assert error.element_id == "PG"


def behavior_code(behavior: str):
    s, t, e = start(), Task("T", "T", behavior), end()
    seq(s, t)
    seq(t, e)
    visitor = generate(make_bpmn(("P", [s, t, e])))
    return visitor, repr(visitor.behaviors)


def test_behavior_assignments():
    visitor, code = behavior_code("x = 1\ny = x + 2; z = y\nskip\nupdateState()")
    assert visitor.errors == []
    assert "x = 1;" in code
    assert "y = x + 2;" in code
    assert "z = y;" in code
    assert "skip" not in code
    assert "updateState();" in code
    assert "void updateState(void);" in code


def test_empty_behavior():
    visitor, code = behavior_code("")
    assert visitor.errors == []
    assert "static void T_BehaviorModel(void) {" in code
    assert "updateState" not in code


def test_behavior_assert_and_comparison():
    _, code = behavior_code("assert(x != y)\nassert(x == 1 || y >= 2)")
    assert "assert(x != y);" in code
    assert "assert(x == 1 || y >= 2);" in code


def test_behavior_if_with_guards_and_else():
    visitor, code = behavior_code(
        "if\n"
        ":: x == a -> y = b\n"
        ":: (x != a) && (y == b) -> y = a; x = b\n"
        ":: else -> skip\n"
        "fi\n"
        "updateState()"
    )
    assert visitor.errors == []
    assert "bool if0_guard0 = (x == a);" in code
    assert "bool if0_guard1 = ((x != a) && (y == b));" in code
    assert "bool if0_guard2 = (!((x == a) || ((x != a) && (y == b))));" in code
    assert "__CPROVER_assume(" in code
    assert "if (if0_pick == 0) {" in code
    assert "y = b;" in code
    assert "x = b;" in code
    assert code.index("}") < code.index("updateState();")


def test_behavior_nested_if_and_true_guard():
    visitor, code = behavior_code(
        "if\n:: true ->\n  if\n  :: x == 1 -> y = 2\n  :: else -> y = 3\n  fi\nfi"
    )
    assert visitor.errors == []
    assert "bool if1_guard0 = (true);" in code
    assert "bool if0_guard0 = (x == 1);" in code
    assert "y = 3;" in code


@pytest.mark.parametrize(
    "behavior", ["if\n:: true -> x = 1", "fi", "do\n:: x = 1\nod", "goto end"]
)
def test_unsupported_behavior_is_an_error(behavior):
    visitor, _ = behavior_code(behavior)
    error = visitor.result().failure()
    assert isinstance(error, BpmnCbmcUnsupportedElementError)
    assert error.element_id == "T"


@pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc not installed")
def test_fork_join_and_behaviors_in_cbmc(tmp_path):
    s, f, a, b, j, e = (
        start(),
        ParallelGatewayNode("F", "F"),
        Task("A", "A", "x = x + 1"),
        Task("B", "B", "if\n:: x == 0 -> y = 5\n:: else -> y = 7\nfi"),
        ParallelGatewayNode("J", "J"),
        end(),
    )
    seq(s, f)
    seq(f, a)
    seq(f, b)
    seq(a, j)
    seq(b, j)
    seq(j, e)
    code = repr(generate(make_bpmn(("P", [s, f, a, b, j, e]))))
    harness = (
        "int x = 0;\nint y = 0;\n"
        f"{code}"
        "int main(void) {\n"
        "\tP_init();\n"
        "\tfor (int i = 0; i < 8; i++) P_step();\n"
        "\tassert(P_done);\n"
        "\tassert(x == 1);\n"
        "\tassert(y == 5 || y == 7);\n"
        "\treturn 0;\n"
        "}\n"
    )
    path = tmp_path / "model.c"
    path.write_text(harness)
    run = subprocess.run(
        ["cbmc", str(path), "--unwind", "9"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert "VERIFICATION SUCCESSFUL" in run.stdout, run.stdout


def test_boundary_event_is_an_error():
    s, t, e = start(), Task("T", "T", ""), end()
    seq(s, t)
    seq(t, e)
    boundary = Task.BoundaryEvent("BE", "BE", "", "", "T")
    t.add_boundary_event(boundary)
    visitor = generate(make_bpmn(("P", [s, t, e])))
    assert isinstance(visitor.result().failure(), BpmnCbmcUnsupportedElementError)


def test_gateway_with_message_is_an_error():
    s, g, e = start(), ExclusiveGatewayNode("G", "G"), end()
    seq(s, g)
    seq(g, e, "true")
    o, oe = start("O"), end("OE")
    seq(o, oe)
    msg(o, g)
    visitor = generate(make_bpmn(("P", [s, g, e]), ("Q", [o, oe])))
    assert isinstance(visitor.result().failure(), BpmnCbmcUnsupportedElementError)


@pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc not installed")
def test_generated_c_runs_in_cbmc(tmp_path):
    s, g, a, b, e = (
        start(),
        ExclusiveGatewayNode("G", "G"),
        Task("A", "A", ""),
        Task("B", "B", ""),
        end(),
    )
    seq(s, g)
    seq(g, a, "x > 1")
    seq(g, b, "x <= 1")
    seq(a, e)
    seq(b, e)
    code = repr(generate(make_bpmn(("P", [s, g, a, b, e]))))
    harness = (
        "int x;\n"
        f"{code}"
        "int main(void) {\n"
        "\tx = nondet_uint() % 4;\n"
        "\tP_init();\n"
        "\tfor (int i = 0; i < 4; i++) P_step();\n"
        "\tassert(P_done);\n"
        "\treturn 0;\n"
        "}\n"
    )
    path = tmp_path / "model.c"
    path.write_text(harness)
    run = subprocess.run(
        ["cbmc", str(path), "--unwind", "5"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert "VERIFICATION SUCCESSFUL" in run.stdout, run.stdout


def _feel(text: str):
    return parse_expression(text).unwrap()


def test_feel_behavior_and_conditions_are_translated():
    s, g, t, e, e2 = (
        start(),
        ExclusiveGatewayNode("G", "G"),
        Task("T", "T", ""),
        end(),
        end("E2"),
    )
    t.behavior = parse_behavior("(x, [x], x + 1), (y, [], choose [1, 2])").unwrap()
    seq(s, t)
    seq(t, g)
    seq(g, e, "")
    seq(g, e2, "")
    g.out_flows[0].expression = _feel("x > 2 and choose [true, false]")
    g.out_flows[1].expression = _feel("not (x > 2)")
    visitor = generate(make_bpmn(("P", [s, t, g, e, e2])))
    code = repr(visitor)
    assert visitor.errors == []
    assert "x = (x + 1);" in code
    assert "void updateState(void);" in code
    assert code.count("updateState();") == 1
    assert "unsigned int T_feel_choose_0 = nondet_uint();" in code
    assert "y = (T_feel_choose_0 == 0 ? 1 : 2);" in code
    assert "unsigned int guard0_choose_0 = nondet_uint();" in code
    assert "bool guard0 = (((x > 2) && (guard0_choose_0 == 0 ? true : false)));" in code
    assert "bool guard1 = ((!(x > 2)));" in code


def test_feel_that_c_cannot_express_is_an_error():
    s, t, e = start(), Task("T", "T", ""), end()
    t.behavior = parse_behavior("(x, [x], x + 1.5)").unwrap()
    seq(s, t)
    seq(t, e)
    visitor = generate(make_bpmn(("P", [s, t, e])))
    assert isinstance(visitor.result().failure(), FeelCbmcUnsupportedError)


@pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc not installed")
def test_feel_behavior_with_choose_in_cbmc(tmp_path):
    s, t, e = start(), Task("T", "T", ""), end()
    t.behavior = parse_behavior("(x, [], choose [1, 2, 3])").unwrap()
    seq(s, t)
    seq(t, e)
    code = repr(generate(make_bpmn(("P", [s, t, e]))))

    def run(check: str):
        path = tmp_path / "model.c"
        path.write_text(
            f"int x = 0;\nvoid updateState(void) {{}}\n{code}int main(void) {{\n\tP_init();\n"
            f"\tfor (int i = 0; i < 4; i++) P_step();\n\t{check}\n\treturn 0;\n}}\n"
        )
        return subprocess.run(
            ["cbmc", str(path), "--unwind", "5"],
            check=False,
            capture_output=True,
            text=True,
        ).stdout

    assert "VERIFICATION SUCCESSFUL" in run("assert(x >= 1 && x <= 3);")
    for value in (1, 2, 3):
        assert "VERIFICATION FAILED" in run(f"assert(x != {value});")


@pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc not installed")
def test_feel_workflow_verifies_in_cbmc(tmp_path):
    state_text = (Path(FEEL) / "state.txt").read_text()
    state = State.from_str(state_text).unwrap()
    cwp_xml = unsafe_perform_io(
        element_tree_from_string((Path(FEEL) / "test_cwp.xml").read_text()).unwrap()
    )
    bpmn_xml = unsafe_perform_io(
        element_tree_from_string((Path(FEEL) / "test_bpmn.bpmn").read_text()).unwrap()
    )
    builder = (
        CbmcBuilder()
        .with_state(state)
        .with_cwp(CwpXmlParser.from_xml(cwp_xml, state).unwrap())
        .with_bpmn(bpmnmethods.from_xml(bpmn_xml, state).unwrap())
    )
    code = builder.build().unwrap()
    bound = builder.unwind_bound().unwrap()

    # The CWP's start state is only made active by calculateState(), which the
    # builder's main does not call; call it first, as the Promela init does.
    code = code.replace("_init();", "_init(); calculateState();", 1)
    path = tmp_path / "model.c"
    path.write_text(code)
    run = subprocess.run(
        ["cbmc", str(path), "--unwind", str(bound), "--unwinding-assertions"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert "VERIFICATION SUCCESSFUL" in run.stdout, run.stdout
