# type: ignore
import re
import subprocess

import pytest
from returns.result import Failure, Success

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
from bpmncwpverify.visitors.bpmn_cbmc_visitor import (
    END_STR,
    START_STR,
    BpmnCbmcVisitor,
)


def start(id="S"):
    return StartEvent(id, id, "", "")


def end(id="E"):
    return EndEvent(id, id, "", "")


def task(id="T", behavior=""):
    return Task(id, id, behavior)


def link(src, dst, id=None, expr=""):
    flow = SequenceFlow(id or f"{src.id}_{dst.id}", "")
    flow.expression = expr
    flow.source_node = src
    flow.target_node = dst
    src.add_out_flow(flow)
    dst.add_in_flow(flow)
    return flow


def message(src, dst, id):
    msg = MessageFlow(id, id)
    msg.source_node = src
    msg.target_node = dst
    src.add_out_msg(msg)
    dst.add_in_msg(msg)
    return msg


def make_bpmn(*nodes, pid="P"):
    process = Process(pid, pid)
    for node in nodes:
        process[node.id] = node
    bpmn = Bpmn()
    bpmn.processes[pid] = process
    return bpmn


def linear():
    s, t, e = start(), task(), end()
    link(s, t)
    link(t, e)
    return make_bpmn(s, t, e)


def visit(bpmn):
    visitor = BpmnCbmcVisitor()
    bpmn.accept(visitor)
    return visitor


def generate(bpmn):
    return str(visit(bpmn))


def function_body(code, name):
    match = re.search(rf"\b{name}\(void\) \{{\n(.*?)\n\}}\n", code, re.S)
    assert match, f"{name} not found"
    return match.group(1)


def program(bpmn, bound, extra_decls="", assertion="bpmn_all_done()"):
    return f"""{extra_decls}
{generate(bpmn)}
int main(void) {{
    bpmn_init();
    for (unsigned i = 0; i < {bound} && !bpmn_all_done(); i++) bpmn_step();
    assert({assertion});
    return 0;
}}
"""


def gcc(tmp_path, source):
    src = tmp_path / "p.c"
    src.write_text(source)
    return subprocess.run(
        [
            "gcc",
            "-Wall",
            "-Werror",
            "-Wno-unused-function",
            "-D__CPROVER_assume(x)=((void)(x))",
            "-c",
            str(src),
            "-o",
            "/dev/null",
        ],
        capture_output=True,
        text=True,
    )


def cbmc(tmp_path, source, unwind):
    src = tmp_path / "p.c"
    src.write_text(source)
    return subprocess.run(
        ["cbmc", str(src), "--unwind", str(unwind), "--unwinding-assertions"],
        capture_output=True,
        text=True,
    ).stdout


class TestBpmnCbmcVisitor:
    def test_markers(self):
        out = generate(linear())
        assert out.startswith(START_STR)
        assert out.rstrip().endswith(END_STR)

    def test_start_event_has_place_and_transition(self):
        out = generate(linear())
        assert "static bool tok_S;" in out
        assert "tok_S = true;" in function_body(out, "bpmn_init")
        assert function_body(out, "bpmn_enabled_S").strip() == "return (tok_S);"
        fire = function_body(out, "bpmn_fire_S")
        assert "tok_S = false;" in fire
        assert "tok_S_T = true;" in fire

    def test_sequence_flows_are_places(self):
        out = generate(linear())
        assert "static bool tok_S_T;" in out
        assert "static bool tok_T_E;" in out

    def test_task_consumes_and_produces(self):
        out = generate(linear())
        assert function_body(out, "bpmn_enabled_T").strip() == "return (tok_S_T);"
        fire = function_body(out, "bpmn_fire_T")
        assert "tok_S_T = false;" in fire
        assert "tok_T_E = true;" in fire

    def test_task_behavior_placeholder(self):
        out = generate(linear())
        assert "// behavior of T" in function_body(out, "bpmn_fire_T")

    def test_end_event_marks_process_done(self):
        out = generate(linear())
        assert "static bool done_P;" in out
        assert "done_P = true;" in function_body(out, "bpmn_fire_E")
        assert function_body(out, "bpmn_all_done").strip() == "return done_P;"

    def test_all_done_needs_every_process(self):
        bpmn = linear()
        s, e = start("S2"), end("E2")
        link(s, e)
        process = Process("Q", "Q")
        process["S2"] = s
        process["E2"] = e
        bpmn.processes["Q"] = process
        out = generate(bpmn)
        assert function_body(out, "bpmn_all_done").strip() == "return done_P && done_Q;"
        assert "done_Q = true;" in function_body(out, "bpmn_fire_E2")

    def test_intermediate_event(self):
        s, i, e = start(), IntermediateEvent("I", "I", "", "", "catch"), end()
        link(s, i)
        link(i, e)
        out = generate(make_bpmn(s, i, e))
        assert function_body(out, "bpmn_enabled_I").strip() == "return (tok_S_I);"
        assert "tok_I_E = true;" in function_body(out, "bpmn_fire_I")

    def test_merge_task_enabled_by_any_incoming_and_clears_all(self):
        s, a, t, e = start(), task("A"), task("T"), end()
        link(s, a)
        link(a, t, "f1")
        link(s, t, "f2")
        link(t, e)
        out = generate(make_bpmn(s, a, t, e))
        assert (
            function_body(out, "bpmn_enabled_T").strip() == "return (tok_f1 || tok_f2);"
        )
        fire = function_body(out, "bpmn_fire_T")
        assert "tok_f1 = false;" in fire and "tok_f2 = false;" in fire

    def test_message_flow(self):
        s1, t1, e1 = start("S1"), task("T1"), end("E1")
        s2, i2, e2 = (
            start("S2"),
            IntermediateEvent("I2", "I2", "", "", "catch"),
            end("E2"),
        )
        link(s1, t1)
        link(t1, e1)
        link(s2, i2)
        link(i2, e2)
        message(t1, i2, "m1")
        bpmn = make_bpmn(s1, t1, e1, pid="P1")
        process = Process("P2", "P2")
        for n in (s2, i2, e2):
            process[n.id] = n
        bpmn.processes["P2"] = process
        out = generate(bpmn)
        assert "static bool tok_m1;" in out
        assert "tok_m1 = true;" in function_body(out, "bpmn_fire_T1")
        assert (
            function_body(out, "bpmn_enabled_I2").strip()
            == "return (tok_S2_I2) && (tok_m1);"
        )
        assert "tok_m1 = false;" in function_body(out, "bpmn_fire_I2")

    def test_exclusive_gateway_has_transition_per_outgoing_flow(self):
        s, g, a, b = start(), ExclusiveGatewayNode("G", "G"), end("A"), end("B")
        link(s, g)
        link(g, a, "ga", "x == 1")
        link(g, b, "gb", "x != 1")
        out = generate(make_bpmn(s, g, a, b))
        assert (
            function_body(out, "bpmn_enabled_G__ga").strip()
            == "return (tok_S_G) && (x == 1);"
        )
        assert (
            function_body(out, "bpmn_enabled_G__gb").strip()
            == "return (tok_S_G) && (x != 1);"
        )
        fire = function_body(out, "bpmn_fire_G__ga")
        assert "tok_S_G = false;" in fire
        assert "tok_ga = true;" in fire and "tok_gb" not in fire

    def test_exclusive_gateway_multiline_expression(self):
        s, g, a = start(), ExclusiveGatewayNode("G", "G"), end("A")
        link(s, g)
        link(g, a, "ga", "x == 1 &&\n  y == 2")
        out = generate(make_bpmn(s, g, a))
        assert "(x == 1 && y == 2)" in function_body(out, "bpmn_enabled_G__ga")

    def test_step_picks_one_transition_without_looping(self):
        out = generate(linear())
        step = function_body(out, "bpmn_step")
        assert "nondet_uint()" in step
        assert "__CPROVER_assume(t < 3u);" in step
        assert step.count("switch") == 1
        assert not re.search(r"\b(for|while|do)\b", out)
        for name in ("S", "T", "E"):
            assert f"__CPROVER_assume(bpmn_enabled_{name}());" in step
            assert step.count(f"bpmn_fire_{name}();") == 1

    def test_overflow_checked_once_per_pass(self):
        out = generate(linear())
        step = function_body(out, "bpmn_step")
        assert step.count("assert(") == 1
        assert out.count("assert(") == 1 + out.count("#include <assert.h>") - 1
        assert "bpmn_overflow = bpmn_overflow || tok_S_T;" in function_body(
            out, "bpmn_fire_S"
        )

    def test_transition_count(self):
        assert visit(linear()).transition_count == 3

    def test_result_success(self):
        result = BpmnCbmcVisitor()
        linear().accept(result)
        assert result.result() == Success(str(result))

    def test_shared_node_is_generated_once(self):
        s, t, e = start(), task(), end()
        link(s, t)
        link(t, e)
        bpmn = make_bpmn(s, t, e)
        visitor = BpmnCbmcVisitor()
        bpmn.accept(visitor)
        bpmn.accept(visitor)
        assert visitor.transition_count == 3

    def test_parallel_gateway_is_an_error(self):
        s, g, e = start(), ParallelGatewayNode("PG", "PG"), end()
        link(s, g)
        link(g, e)
        visitor = visit(make_bpmn(s, g, e))
        result = visitor.result()
        assert isinstance(result, Failure)
        error = result.failure()
        assert isinstance(error, BpmnCbmcUnsupportedElementError)
        assert error.element_id == "PG"

    def test_boundary_event_is_an_error(self):
        s, t, e = start(), task(), end()
        link(s, t)
        link(t, e)
        t.add_boundary_event(Task.BoundaryEvent("B", "B", "m", "", "T"))
        visitor = visit(make_bpmn(s, t, e))
        errors = visitor.errors
        assert errors
        assert all(isinstance(x, BpmnCbmcUnsupportedElementError) for x in errors)
        assert {x.element_id for x in errors} >= {"T"}
        assert isinstance(visitor.result(), Failure)


class TestBpmnCbmcCompiles:
    def test_linear_compiles(self, tmp_path):
        result = gcc(tmp_path, program(linear(), 3))
        assert result.returncode == 0, result.stderr

    def test_gateway_message_compiles(self, tmp_path):
        s, g, a, b = start(), ExclusiveGatewayNode("G", "G"), end("A"), end("B")
        link(s, g)
        link(g, a, "ga", "x == 1")
        link(g, b, "gb", "x != 1")
        source = program(make_bpmn(s, g, a, b), 3, "int x = 0;\n")
        assert gcc(tmp_path, source).returncode == 0


@pytest.mark.skipif(
    subprocess.run(["which", "cbmc"], capture_output=True).returncode != 0,
    reason="cbmc is not installed",
)
class TestBpmnCbmcVerifies:
    def test_linear_reaches_done_within_bound(self, tmp_path):
        out = cbmc(tmp_path, program(linear(), 3), 4)
        assert "VERIFICATION SUCCESSFUL" in out

    def test_too_small_bound_is_found(self, tmp_path):
        out = cbmc(tmp_path, program(linear(), 2), 3)
        assert "VERIFICATION FAILED" in out

    def test_gateway_follows_condition(self, tmp_path):
        s, g, a, b = start(), ExclusiveGatewayNode("G", "G"), end("A"), end("B")
        link(s, g)
        link(g, a, "ga", "x == 1")
        link(g, b, "gb", "x != 1")
        bpmn = make_bpmn(s, g, a, b)
        # x is 0, so only the path to B can be taken
        ok = program(bpmn, 3, "int x = 0;\n", "done_P && !tok_ga")
        assert "VERIFICATION SUCCESSFUL" in cbmc(tmp_path, ok, 4)

    def test_blocked_path_does_not_reach_done(self, tmp_path):
        s, g, a = start(), ExclusiveGatewayNode("G", "G"), end("A")
        link(s, g)
        link(g, a, "ga", "x == 1")
        bpmn = make_bpmn(s, g, a)
        # x is 0, so no transition is enabled after the start event
        bad = program(bpmn, 3, "int x = 0;\n", "!done_P")
        assert "VERIFICATION SUCCESSFUL" in cbmc(tmp_path, bad, 4)

    def test_message_flow_orders_processes(self, tmp_path):
        s1, t1, e1 = start("S1"), task("T1"), end("E1")
        s2, i2, e2 = (
            start("S2"),
            IntermediateEvent("I2", "I2", "", "", "catch"),
            end("E2"),
        )
        link(s1, t1)
        link(t1, e1)
        link(s2, i2)
        link(i2, e2)
        message(t1, i2, "m1")
        bpmn = make_bpmn(s1, t1, e1, pid="P1")
        process = Process("P2", "P2")
        for n in (s2, i2, e2):
            process[n.id] = n
        bpmn.processes["P2"] = process
        # 6 transitions are needed, and I2 can never run before T1
        out = cbmc(tmp_path, program(bpmn, 6), 7)
        assert "VERIFICATION SUCCESSFUL" in out

    def test_token_on_occupied_place_is_found(self, tmp_path):
        # T puts a token back on its own incoming flow and on the flow to E
        s, t, e = start(), task(), end()
        link(s, t)
        link(t, t, "loop").is_leaf = True  # as the BPMN validation marks it
        link(t, e, "out")
        out = cbmc(tmp_path, program(make_bpmn(s, t, e), 4), 5)
        assert "VERIFICATION FAILED" in out
        assert "bpmn_overflow" in out
