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
from bpmncwpverify.core.error import (
    BpmnCbmcUnsupportedElementError,
    BpmnSeqFlowNoExprError,
)
from bpmncwpverify.visitors.bpmn_cbmc_visitor import CbmcBpmnGenVisitor


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


def test_parallel_gateway_is_an_error():
    s, p, e = start(), ParallelGatewayNode("PG", "PG"), end()
    seq(s, p)
    seq(p, e)
    visitor = generate(make_bpmn(("P", [s, p, e])))
    assert len(visitor.errors) == 1
    error = visitor.result().failure()
    assert isinstance(error, BpmnCbmcUnsupportedElementError)
    assert error.element_id == "PG"


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
