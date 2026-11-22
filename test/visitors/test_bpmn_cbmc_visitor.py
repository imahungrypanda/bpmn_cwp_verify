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
from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState
from bpmncwpverify.core.error import BpmnCbmcUnsupportedElementError
from bpmncwpverify.visitors.bpmn_cbmc_visitor import (
    END_STR,
    START_STR,
    BpmnCbmcVisitor,
)
from bpmncwpverify.visitors.cwp_cbmc_visitor import CwpCbmcVisitor

CWP_STUB = "static void cwp_update(void) {}\n"


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

    def test_parallel_gateway_with_one_flow_is_a_join_without_error(self):
        s, g, e = start(), ParallelGatewayNode("PG", "PG"), end()
        link(s, g)
        link(g, e)
        visitor = visit(make_bpmn(s, g, e))
        assert visitor.result() == Success(str(visitor))

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


def fork_join():
    s, f, a, b, j, e = (
        start(),
        ParallelGatewayNode("F", "F"),
        task("A"),
        task("B"),
        ParallelGatewayNode("J", "J"),
        end(),
    )
    link(s, f)
    link(f, a)
    link(f, b)
    link(a, j)
    link(b, j)
    link(j, e)
    return make_bpmn(s, f, a, b, j, e)


def fork_loop(a_behavior="x = x + 1"):
    """A fork that the start event and the loop at the end both flow into."""
    s, f, a, b, j, g, e = (
        start(),
        ParallelGatewayNode("F", "F"),
        task("A", a_behavior),
        task("B"),
        ParallelGatewayNode("J", "J"),
        ExclusiveGatewayNode("G", "G"),
        end(),
    )
    link(s, f)
    link(f, a)
    link(f, b)
    link(a, j)
    link(b, j)
    link(j, g)
    link(g, f, "back", "x < 2").is_leaf = True  # as the BPMN validation marks it
    link(g, e, "exit", "x >= 2")
    return make_bpmn(s, f, a, b, j, g, e)


def nested():
    """S -> F1 -> (A, F2 -> (B, C) -> J2) -> J1 -> E."""
    s, f1, a, f2, b, c, j2, j1, e = (
        start(),
        ParallelGatewayNode("F1", "F1"),
        task("A"),
        ParallelGatewayNode("F2", "F2"),
        task("B"),
        task("C"),
        ParallelGatewayNode("J2", "J2"),
        ParallelGatewayNode("J1", "J1"),
        end(),
    )
    link(s, f1)
    link(f1, a)
    link(f1, f2)
    link(f2, b)
    link(f2, c)
    link(b, j2)
    link(c, j2)
    link(a, j1)
    link(j2, j1)
    link(j1, e)
    return make_bpmn(s, f1, a, f2, b, c, j2, j1, e)


def behavior_bpmn(behavior):
    s, t, e = start(), task("T", behavior), end()
    link(s, t)
    link(t, e)
    return make_bpmn(s, t, e)


def fire_t(behavior):
    return function_body(generate(behavior_bpmn(behavior)), "bpmn_fire_T")


class TestBpmnCbmcParallelGateways:
    def test_fork_is_enabled_by_any_incoming_and_starts_every_branch(self):
        out = generate(fork_loop())
        assert (
            function_body(out, "bpmn_enabled_F").strip()
            == "return (tok_S_F || tok_back);"
        )
        fire = function_body(out, "bpmn_fire_F")
        assert "tok_S_F = false;" in fire and "tok_back = false;" in fire
        assert "tok_F_A = true;" in fire and "tok_F_B = true;" in fire

    def test_join_waits_for_every_incoming(self):
        out = generate(fork_join())
        assert (
            function_body(out, "bpmn_enabled_J").strip()
            == "return (tok_A_J && tok_B_J);"
        )
        fire = function_body(out, "bpmn_fire_J")
        assert "tok_A_J = false;" in fire and "tok_B_J = false;" in fire
        assert "tok_J_E = true;" in fire

    def test_fork_checks_its_outgoing_places_for_overflow(self):
        fire = function_body(generate(fork_join()), "bpmn_fire_F")
        assert "bpmn_overflow = bpmn_overflow || tok_F_A || tok_F_B;" in fire

    def test_nested_gateways_each_have_a_transition(self):
        visitor = visit(nested())
        out = str(visitor)
        assert visitor.transition_count == 9
        assert visitor.result() == Success(out)
        assert (
            function_body(out, "bpmn_enabled_J1").strip()
            == "return (tok_A_J1 && tok_J2_J1);"
        )
        assert (
            function_body(out, "bpmn_enabled_J2").strip()
            == "return (tok_B_J2 && tok_C_J2);"
        )
        fire = function_body(out, "bpmn_fire_F1")
        assert "tok_F1_A = true;" in fire and "tok_F1_F2 = true;" in fire

    def test_no_loops_with_gateways(self):
        assert not re.search(r"\b(for|while|do)\b", generate(fork_loop()))


class TestBpmnCbmcBehaviors:
    def test_empty_behavior_does_not_update_the_cwp(self):
        assert "cwp_update" not in fire_t("")
        assert "cwp_update" not in fire_t("  \n ")

    def test_assignment(self):
        fire = fire_t("backpackOwner = sellerName\npaymentOwner = buyerName")
        assert "backpackOwner = sellerName;" in fire
        assert "paymentOwner = buyerName;" in fire

    def test_cwp_update_comes_after_behavior_and_before_tokens_move(self):
        lines = [line.strip() for line in fire_t("x = x + 1").splitlines()]
        assert lines.index("x = x + 1;") < lines.index("cwp_update();")
        assert lines.index("cwp_update();") < lines.index("tok_T_E = true;")
        assert lines.index("tok_S_T = false;") < lines.index("x = x + 1;")
        assert lines.count("cwp_update();") == 1

    def test_semicolon_separated_statements(self):
        fire = fire_t("x = 1; y = 2")
        assert "x = 1;" in fire and "y = 2;" in fire

    def test_if_with_comparisons(self):
        fire = fire_t("if\n:: x == 1 -> y = 2\n:: x != 1 && y < 3 -> y = 3\nfi")
        assert fire.count("switch (choice_0)") == 1
        assert "__CPROVER_assume(x == 1);" in fire
        assert "__CPROVER_assume(x != 1 && y < 3);" in fire
        assert "y = 2;" in fire and "y = 3;" in fire
        assert fire.count("cwp_update();") == 1

    def test_if_else(self):
        fire = fire_t("if\n:: x == 1 -> y = 2\n:: else -> y = 3\nfi")
        assert "__CPROVER_assume(!(x == 1));" in fire

    def test_nested_if(self):
        fire = fire_t(
            "if\n:: true -> if\n:: x == 1 -> y = 1\n:: x == 2 -> y = 2\nfi\n"
            ":: true -> y = 3\nfi"
        )
        assert "switch (choice_0)" in fire and "switch (choice_1)" in fire
        assert not re.search(r"\b(for|while|do)\b", fire)

    def test_skip_is_nothing(self):
        fire = fire_t("skip")
        assert "skip" not in fire
        assert "cwp_update();" in fire

    def test_bare_expression_blocks(self):
        assert "__CPROVER_assume(x == 1);" in fire_t("x == 1")

    @pytest.mark.parametrize(
        "behavior",
        ["do\n:: x = 1\nod", "goto end", "if\n:: x = 1", "x = 1\nfi", ":: x = 1"],
    )
    def test_unsupported_behavior_is_an_error(self, behavior):
        visitor = visit(behavior_bpmn(behavior))
        result = visitor.result()
        assert isinstance(result, Failure)
        assert isinstance(result.failure(), BpmnCbmcUnsupportedElementError)
        assert result.failure().element_id == "T"

    def test_shared_task_behavior_is_translated_once(self):
        bpmn = behavior_bpmn("x = 1")
        visitor = BpmnCbmcVisitor()
        bpmn.accept(visitor)
        bpmn.accept(visitor)
        assert str(visitor).count("x = 1;") == 1


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


class TestBpmnCbmcBehaviorsCompile:
    def test_behaviors_compile(self, tmp_path):
        behavior = (
            "x = x + 1\nif\n:: x == 1 -> y = 2\n"
            ":: else -> if\n:: true -> y = 3\n:: true -> y = 4\nfi\nfi"
        )
        source = program(
            behavior_bpmn(behavior), 3, "int x = 0, y = 0;\n" + CWP_STUB, "true"
        )
        result = gcc(tmp_path, source)
        assert result.returncode == 0, result.stderr

    def test_parallel_gateways_compile(self, tmp_path):
        for bpmn in (fork_join(), fork_loop(), nested()):
            source = program(bpmn, 3, "int x = 0;\n" + CWP_STUB)
            result = gcc(tmp_path, source)
            assert result.returncode == 0, result.stderr


def simple_cwp():
    """A -> B -> C, driven by x. The init edge puts x == 0 in A."""
    cwp = Cwp()
    for name in "ABC":
        cwp.states[name] = CwpState(name, name)
    for i, (src, dst, expr) in enumerate([("A", "B", "x == 1"), ("B", "C", "x == 2")]):
        edge = CwpEdge(f"e{i}", f"Edge{i}")
        edge.expression = expr
        edge.set_source(cwp.states[src])
        edge.set_dest(cwp.states[dst])
        cwp.states[src].out_edges.append(edge)
        cwp.states[dst].in_edges.append(edge)
        cwp.edges[edge.id] = edge
    init = CwpEdge("init", "Init")
    init.expression = "x == 0"
    init.set_dest(cwp.states["A"])
    cwp.states["A"].in_edges.append(init)
    cwp.start_state = cwp.states["A"]
    return cwp


def cwp_program(bpmn, bound, assertion):
    cwp = CwpCbmcVisitor()
    simple_cwp().accept(cwp)
    return f"""int x = 0;
{cwp}
{generate(bpmn)}
int main(void) {{
    cwp_init();
    bpmn_init();
    for (unsigned i = 0; i < {bound} && !bpmn_all_done(); i++) bpmn_step();
    assert({assertion});
    return 0;
}}
"""


def two_tasks(first, second):
    s, t1, t2, e = start(), task("T1", first), task("T2", second), end()
    link(s, t1)
    link(t1, t2)
    link(t2, e)
    return make_bpmn(s, t1, t2, e)


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

    def test_fork_and_join(self, tmp_path):
        assert "VERIFICATION SUCCESSFUL" in cbmc(
            tmp_path, program(fork_join(), 6, CWP_STUB), 7
        )

    def test_fork_and_join_bound_is_tight(self, tmp_path):
        out = cbmc(tmp_path, program(fork_join(), 5, CWP_STUB), 6)
        assert "VERIFICATION FAILED" in out

    def test_join_waits_for_the_other_branch(self, tmp_path):
        # A's branch has no way to reach J's other incoming flow
        s, f, a, j, e = (
            start(),
            ParallelGatewayNode("F", "F"),
            task("A"),
            ParallelGatewayNode("J", "J"),
            end(),
        )
        link(s, f)
        link(f, a)
        link(f, e, "fe")
        link(a, j)
        link(j, e, "je")
        # J has a single incoming flow, so it is a join that A alone enables
        out = cbmc(tmp_path, program(make_bpmn(s, f, a, j, e), 5, CWP_STUB), 6)
        assert "VERIFICATION SUCCESSFUL" in out

    def test_join_with_missing_branch_blocks(self, tmp_path):
        s, f, a, j, e = (
            start(),
            ParallelGatewayNode("F", "F"),
            task("A"),
            ParallelGatewayNode("J", "J"),
            end(),
        )
        link(s, f)
        link(f, a)
        link(f, j, "fj")
        link(a, j)
        link(j, e)
        out = cbmc(tmp_path, program(make_bpmn(s, f, a, j, e), 5, CWP_STUB, "true"), 6)
        assert "VERIFICATION SUCCESSFUL" in out
        # J needs both tokens, so it takes A's run to get there
        blocked = program(make_bpmn(s, f, a, j, e), 3, CWP_STUB, "!done_P")
        assert "VERIFICATION SUCCESSFUL" in cbmc(tmp_path, blocked, 4)

    def test_fork_with_loop_back_does_not_deadlock(self, tmp_path):
        # S F A B J G, then F A B J G again with x == 2, then the end: 12 passes
        ok = cbmc(tmp_path, program(fork_loop(), 12, "int x = 0;\n" + CWP_STUB), 13)
        assert "VERIFICATION SUCCESSFUL" in ok
        short = cbmc(tmp_path, program(fork_loop(), 11, "int x = 0;\n" + CWP_STUB), 12)
        assert "VERIFICATION FAILED" in short

    def test_nested_gateways(self, tmp_path):
        # S F1 A F2 B C J2 J1 E
        assert "VERIFICATION SUCCESSFUL" in cbmc(
            tmp_path, program(nested(), 9, CWP_STUB), 10
        )
        assert "VERIFICATION FAILED" in cbmc(
            tmp_path, program(nested(), 8, CWP_STUB), 9
        )

    def test_behavior_assigns_and_gateway_compares(self, tmp_path):
        s, t, g, a, b = (
            start(),
            task("T", "x = 1"),
            ExclusiveGatewayNode("G", "G"),
            end("A"),
            end("B"),
        )
        link(s, t)
        link(t, g)
        link(g, a, "ga", "x == 1")
        link(g, b, "gb", "x != 1")
        out = cbmc(
            tmp_path,
            program(
                make_bpmn(s, t, g, a, b),
                4,
                "int x = 0;\n" + CWP_STUB,
                "done_P && x == 1 && !tok_gb",
            ),
            5,
        )
        assert "VERIFICATION SUCCESSFUL" in out

    def test_nondeterministic_behavior_reaches_each_option(self, tmp_path):
        behavior = "if\n:: true -> y = 1\n:: true -> y = 2\nfi"
        for wrong in ("y != 1", "y != 2"):
            source = program(
                behavior_bpmn(behavior), 3, "int y = 0;\n" + CWP_STUB, wrong
            )
            assert "VERIFICATION FAILED" in cbmc(tmp_path, source, 4)
        ok = program(
            behavior_bpmn(behavior), 3, "int y = 0;\n" + CWP_STUB, "y == 1 || y == 2"
        )
        assert "VERIFICATION SUCCESSFUL" in cbmc(tmp_path, ok, 4)

    def test_behavior_else_branch(self, tmp_path):
        behavior = "if\n:: x == 1 -> y = 1\n:: else -> y = 2\nfi"
        source = program(
            behavior_bpmn(behavior), 3, "int x = 0, y = 0;\n" + CWP_STUB, "y == 2"
        )
        assert "VERIFICATION SUCCESSFUL" in cbmc(tmp_path, source, 4)

    def test_cwp_follows_behaviors(self, tmp_path):
        source = cwp_program(two_tasks("x = 1", "x = 2"), 4, "cwp_state == CWP_C")
        assert "VERIFICATION SUCCESSFUL" in cbmc(tmp_path, source, 5)

    def test_cwp_not_updated_without_behavior(self, tmp_path):
        source = cwp_program(two_tasks("x = 1", ""), 4, "cwp_state == CWP_B")
        assert "VERIFICATION SUCCESSFUL" in cbmc(tmp_path, source, 5)

    def test_cwp_update_rejects_an_invalid_move(self, tmp_path):
        # A -> C skips B, which the CWP does not allow
        source = cwp_program(two_tasks("x = 2", ""), 4, "true")
        out = cbmc(tmp_path, source, 5)
        assert "VERIFICATION FAILED" in out
        assert re.search(r"assertion .*: FAILURE", out)
        assert "assertion true: SUCCESS" in out
