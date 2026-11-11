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
    HELPER_DEFS_STR,
    CbmcBpmnGenVisitor,
    ended_name,
    place_name,
)


def connect(src: Node, dst: Node, fid: str, expr: str = "") -> SequenceFlow:
    flow = SequenceFlow(fid, fid)
    flow.source_node = src
    flow.target_node = dst
    flow.expression = expr
    src.add_out_flow(flow)
    dst.add_in_flow(flow)
    return flow


def message(src: Node, dst: Node, mid: str) -> MessageFlow:
    msg = MessageFlow(mid, mid)
    msg.source_node = src
    msg.target_node = dst
    src.add_out_msg(msg)
    dst.add_in_msg(msg)
    return msg


def start(i: str = "s") -> StartEvent:
    return StartEvent(i, i, "", "")


def end(i: str = "e") -> EndEvent:
    return EndEvent(i, i, "", "")


def task(i: str = "t") -> Task:
    return Task(i, i, "")


def run(*processes: tuple[str, list[Node]]) -> CbmcBpmnGenVisitor:
    bpmn = Bpmn()
    for pid, nodes in processes:
        process = Process(pid, pid)
        for node in nodes:
            process[node.id] = node
        bpmn.processes[pid] = process
    visitor = CbmcBpmnGenVisitor()
    bpmn.accept(visitor)
    return visitor


def linear() -> CbmcBpmnGenVisitor:
    s, t, e = start(), task(), end()
    connect(s, t, "f1")
    connect(t, e, "f2")
    return run(("p", [s, t, e]))


def test_places_one_per_start_event_and_flow():
    v = linear()
    assert v.places == {
        place_name("s"): True,
        place_name("f1"): False,
        place_name("f2"): False,
    }


def test_start_task_end_transitions():
    v = linear()
    assert [t.label for t in v.transitions] == ["s", "t", "e"]
    start_t, task_t, end_t = v.transitions
    assert start_t.enable == "tok_s"
    assert start_t.body == [
        "tok_s = false;",
        "bpmn_occupied = tok_f1;",
        "tok_f1 = true;",
    ]
    assert task_t.enable == "(tok_f1)"
    assert task_t.body[0] == "tok_f1 = false;"
    assert "tok_f2 = true;" in task_t.body
    assert end_t.enable == "(tok_f2)"
    assert end_t.body == ["tok_f2 = false;", f"{ended_name('p')} = true;"]


def test_all_ended_expression_covers_every_process():
    s1, e1, s2, e2 = start("s1"), end("e1"), start("s2"), end("e2")
    connect(s1, e1, "f1")
    connect(s2, e2, "f2")
    v = run(("p1", [s1, e1]), ("p2", [s2, e2]))
    assert v.all_ended_expr() == "ended_p1 && ended_p2"
    assert "bool ended_p1 = false;" in v.gen_defs()


def test_defs_initialise_tokens():
    defs = linear().gen_defs()
    assert "bool tok_s = true;" in defs
    assert "bool tok_f1 = false;" in defs


def test_intermediate_event():
    s, i, e = start(), IntermediateEvent("i", "i", "", "", "catch"), end()
    connect(s, i, "f1")
    connect(i, e, "f2")
    v = run(("p", [s, i, e]))
    assert [t.label for t in v.transitions] == ["s", "i", "e"]
    assert v.transitions[1].enable == "(tok_f1)"


def gateway_visitor() -> CbmcBpmnGenVisitor:
    s, g, a, b, e = start(), ExclusiveGatewayNode("g", "g"), task("a"), task("b"), end()
    connect(s, g, "f1")
    connect(g, a, "fa", "x > 5")
    connect(g, b, "fb", "x <= 5")
    connect(a, e, "fa2")
    connect(b, e, "fb2")
    return run(("p", [s, g, a, b, e]))


def test_exclusive_gateway_has_one_transition_per_out_flow():
    v = gateway_visitor()
    by_label = {t.label: t for t in v.transitions}
    ta, tb = by_label["g -> fa"], by_label["g -> fb"]
    assert ta.enable == "(tok_f1) && (x > 5)"
    assert tb.enable == "(tok_f1) && (x <= 5)"
    assert ta.body == ["tok_f1 = false;", "bpmn_occupied = tok_fa;", "tok_fa = true;"]
    assert tb.body[-1] == "tok_fb = true;"


def test_exclusive_gateway_without_viable_path_is_a_violation():
    v = gateway_visitor()
    stuck = next(t for t in v.transitions if "no viable path" in t.label)
    assert stuck.enable == "(tok_f1) && !(x > 5) && !(x <= 5)"
    assert stuck.body[0].startswith("__CPROVER_assert(false")


def test_merging_flows_enable_on_any_incoming_place():
    v = gateway_visitor()
    end_t = next(t for t in v.transitions if t.label == "e")
    assert end_t.enable == "(tok_fa2 || tok_fb2)"
    assert end_t.body[:2] == ["tok_fa2 = false;", "tok_fb2 = false;"]


def test_message_flow_places_and_guards():
    s1, t1, e1 = start("s1"), task("t1"), end("e1")
    s2, c, e2 = start("s2"), IntermediateEvent("c", "c", "", "", "catch"), end("e2")
    connect(s1, t1, "f1")
    connect(t1, e1, "f2")
    connect(s2, c, "g1")
    connect(c, e2, "g2")
    message(t1, c, "m1")
    v = run(("p1", [s1, t1, e1]), ("p2", [s2, c, e2]))
    assert v.places["tok_m1"] is False
    send = next(t for t in v.transitions if t.label == "t1")
    assert "tok_m1 = true;" in send.body
    catch = next(t for t in v.transitions if t.label == "c")
    assert catch.enable == "(tok_g1) && (tok_m1)"
    assert "tok_m1 = false;" in catch.body


def test_pass_picks_one_enabled_transition_without_looping():
    v = gateway_visitor()
    code = v.gen_pass()
    n = len(v.transitions)
    assert f"__CPROVER_assume(bpmn_choice < {n}u);" in code
    assert code.count("nondet_uint()") == 1
    assert code.count("switch (") == 1
    assert code.count("__CPROVER_assume(") == n + 2  # bound, every case, default
    for keyword in ("for (", "while (", "do {"):
        assert keyword not in code
    for i in range(n):
        assert f"case {i}:" in code
    # token overflow is checked once per pass
    assert code.count("__CPROVER_assert(!bpmn_occupied") == 1


def test_get_result_success():
    result = linear().get_result()
    assert isinstance(result, Success)
    assert "switch (bpmn_choice)" in result.unwrap()


def test_parallel_gateway_is_an_error():
    s, g, e = start(), ParallelGatewayNode("g", "g"), end()
    connect(s, g, "f1")
    connect(g, e, "f2")
    result = run(("p", [s, g, e])).get_result()
    assert isinstance(result, Failure)
    err = result.failure()
    assert isinstance(err, BpmnCbmcUnsupportedElementError)
    assert err.element_id == "g"


def test_boundary_event_is_an_error():
    s, t, e, b, e2 = start(), task(), end(), None, end("e2")
    b = Task.BoundaryEvent("b", "b", "", "", "t")
    t.add_boundary_event(b)
    connect(s, t, "f1")
    connect(t, e, "f2")
    connect(b, e2, "f3")
    result = run(("p", [s, t, e, e2])).get_result()
    assert isinstance(result, Failure)
    assert result.failure().element_id == "b"


def test_gateway_with_message_flow_is_an_error():
    s, g, e, o = start(), ExclusiveGatewayNode("g", "g"), end(), end("o")
    connect(s, g, "f1")
    connect(g, e, "f2", "true")
    message(g, o, "m")
    assert isinstance(run(("p", [s, g, e])).get_result(), Failure)


@pytest.mark.parametrize("workflow_name", ["linear", "gateway"])
def test_generated_c_runs_in_cbmc(tmp_path, workflow_name):
    v = linear() if workflow_name == "linear" else gateway_visitor()
    program = (
        f"{HELPER_DEFS_STR}\nint x;\n{v.gen_defs()}\n"
        "int main(void) {\n"
        "  x = nondet_uint() % 10;\n"
        f"  for (int i = 0; i < 6 && !({v.all_ended_expr()}); i++)\n"
        f"{v.gen_pass()}"
        f'  __CPROVER_assert({v.all_ended_expr()}, "ends");\n'
        "  return 0;\n}\n"
    )
    src = tmp_path / "m.c"
    src.write_text(program)
    out = subprocess.run(
        ["cbmc", str(src), "--unwind", "7"], capture_output=True, text=True
    )
    assert "VERIFICATION SUCCESSFUL" in out.stdout, out.stdout[-2000:] + out.stderr


def test_cbmc_finds_gateway_without_viable_path(tmp_path):
    v = gateway_visitor()
    program = (
        f"{HELPER_DEFS_STR}\nint x;\n{v.gen_defs()}\n"
        "int main(void) {\n"
        "  x = nondet_uint() % 10;\n"
        "  __CPROVER_assume(x == 5);\n"
        "  for (int i = 0; i < 6; i++)\n"
        f"{v.gen_pass()}"
        "  return 0;\n}\n"
    ).replace("x <= 5", "x < 5")
    src = tmp_path / "m.c"
    src.write_text(program)
    out = subprocess.run(
        ["cbmc", str(src), "--unwind", "7"], capture_output=True, text=True
    )
    assert "VERIFICATION FAILED" in out.stdout
    assert "no viable path from g" in out.stdout
