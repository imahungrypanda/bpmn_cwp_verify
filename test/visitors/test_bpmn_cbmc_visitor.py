# type: ignore
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

from returns.pipeline import is_successful

from bpmncwpverify.builder.cbmc_bound import compute_bound
from bpmncwpverify.core.accessmethods import bpmnmethods
from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
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
from bpmncwpverify.core.state import State
from bpmncwpverify.visitors.bpmn_cbmc_visitor import (
    END_STR,
    START_STR,
    STEP_FUNC,
    BpmnCbmcVisitor,
)
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    CALCULATE_STATE_FUNC,
    UPDATE_STATE_FUNC,
    CwpCbmcVisitor,
)

FACE2FACE = Path(__file__).parent.parent / "resources" / "face2face"


def _connect(process, src, dst, flow_id, expr=""):
    flow = SequenceFlow(flow_id, flow_id)
    flow.expression = expr
    flow.source_node = src
    flow.target_node = dst
    src.add_out_flow(flow)
    dst.add_in_flow(flow)
    process[flow_id] = flow
    return flow


def _node(process, cls, node_id, *args):
    node = cls(node_id, node_id, *args)
    process[node_id] = node
    return node


def _bpmn(*processes) -> Bpmn:
    bpmn = Bpmn()
    for p in processes:
        bpmn.processes[p.id] = p
    return bpmn


def _generate(bpmn: Bpmn) -> BpmnCbmcVisitor:
    visitor = BpmnCbmcVisitor()
    bpmn.accept(visitor)
    return visitor


def _linear() -> Bpmn:
    """Start -> Task -> End"""
    p = Process("P", "P")
    s = _node(p, StartEvent, "S", "", "")
    t = _node(p, Task, "T", "")
    e = _node(p, EndEvent, "E", "", "")
    _connect(p, s, t, "f1")
    _connect(p, t, e, "f2")
    return _bpmn(p)


def _run_cbmc(tmp_path, program, *args):
    src = tmp_path / "main.c"
    src.write_text(program)
    return subprocess.run(
        ["cbmc", str(src), *args], capture_output=True, text=True, timeout=120
    )


def _program(visitor, loop_body="", bound=10):
    return f"""{visitor}
int main(void) {{
    for (int i = 0; i < {bound}; i++) {{
        if ({visitor.done_expr}) break;
        {STEP_FUNC}();
        {loop_body}
    }}
    __CPROVER_assert({visitor.done_expr}, "finished");
    return 0;
}}
"""


class TestStructure:
    def test_places_for_start_and_flows(self):
        out = str(_generate(_linear()))
        assert START_STR in out and END_STR in out
        assert "_Bool tok_S = 1;" in out
        assert "_Bool tok_f1 = 0;" in out
        assert "_Bool tok_f2 = 0;" in out
        assert "_Bool done_P = 0;" in out

    def test_one_transition_per_element(self):
        v = _generate(_linear())
        assert [t.name for t in v.transitions] == ["S", "T", "E"]
        assert v.transitions[0].enable == "(tok_S)"
        assert v.transitions[1].enable == "(tok_f1)"
        assert v.transitions[2].enable == "(tok_f2)"

    def test_step_picks_exactly_one_enabled_transition(self):
        out = str(_generate(_linear()))
        assert out.count("nondet_uint()") == 1
        assert "__CPROVER_assume(bpmn_choice < 3);" in out
        assert out.count("switch (bpmn_choice)") == 1
        for i in range(3):
            assert f"case {i}: {{" in out
        # exactly one assume per case plus the choice bound
        assert out.count("__CPROVER_assume(") == 4

    def test_step_has_no_loop(self):
        out = str(_generate(_linear()))
        assert "for (" not in out and "while" not in out

    def test_body_clears_incoming_then_sets_outgoing(self):
        v = _generate(_linear())
        body = repr(v.transitions[1].body)
        assert body.index("tok_f1 = 0;") < body.index("tok_f2 = 1;")
        # a task without a behavior has nothing between clear and set
        assert "bpmn_update_cwp" not in body

    def test_collision_checked_once_per_pass(self):
        out = str(_generate(_linear()))
        assert out.count("__CPROVER_assert(") == 1
        assert "bpmn_collision = tok_f1;" in out

    def test_end_event_marks_process_done(self):
        v = _generate(_linear())
        assert "done_P = 1;" in repr(v.transitions[2].body)
        assert v.done_expr == "done_P"

    def test_intermediate_event(self):
        p = Process("P", "P")
        s = _node(p, StartEvent, "S", "", "")
        i = _node(p, IntermediateEvent, "I", "", "", "catch")
        e = _node(p, EndEvent, "E", "", "")
        _connect(p, s, i, "f1")
        _connect(p, i, e, "f2")
        v = _generate(_bpmn(p))
        assert [t.name for t in v.transitions] == ["S", "I", "E"]
        assert v.transitions[1].enable == "(tok_f1)"

    def test_node_visited_twice_is_one_transition(self):
        p = Process("P", "P")
        t = _node(p, Task, "T", "")
        v = BpmnCbmcVisitor()
        v.visit_process(p)
        v.visit_task(t)
        v.visit_task(t)
        assert len(v.transitions) == 1


class TestExclusiveGateway:
    def _gateway(self) -> Bpmn:
        p = Process("P", "P")
        s = _node(p, StartEvent, "S", "", "")
        g = _node(p, ExclusiveGatewayNode, "G")
        e1 = _node(p, EndEvent, "E1", "", "")
        e2 = _node(p, EndEvent, "E2", "", "")
        _connect(p, s, g, "f0")
        _connect(p, g, e1, "f1", "x == 1")
        _connect(p, g, e2, "f2", "x != 1")
        return _bpmn(p)

    def test_one_transition_per_outgoing_flow(self):
        v = _generate(self._gateway())
        names = [t.name for t in v.transitions]
        assert names == ["S", "G_f1", "G_f2", "E1", "E2"]
        assert v.transitions[1].enable == "(tok_f0) && (x == 1)"
        assert v.transitions[2].enable == "(tok_f0) && (x != 1)"

    def test_gateway_flow_sets_only_its_flow(self):
        v = _generate(self._gateway())
        body = repr(v.transitions[1].body)
        assert "tok_f1 = 1;" in body and "tok_f2" not in body
        assert "tok_f0 = 0;" in body

    def test_join_gateway_enable_is_or_of_incoming(self):
        p = Process("P", "P")
        s1 = _node(p, StartEvent, "S1", "", "")
        s2 = _node(p, StartEvent, "S2", "", "")
        g = _node(p, ExclusiveGatewayNode, "G")
        e = _node(p, EndEvent, "E", "", "")
        _connect(p, s1, g, "a")
        _connect(p, s2, g, "b")
        _connect(p, g, e, "c", "1")
        v = _generate(_bpmn(p))
        gate = next(t for t in v.transitions if t.name == "G_c")
        assert gate.enable == "(tok_a || tok_b) && (1)"
        body = repr(gate.body)
        assert "tok_a = 0;" in body and "tok_b = 0;" in body

    def test_cbmc_takes_both_paths(self, tmp_path):
        v = _generate(self._gateway())
        main = f"""
int main(void) {{
    for (int i = 0; i < 4; i++) {{ if ({v.done_expr}) break; {STEP_FUNC}(); }}
    __CPROVER_assert(!tok_f1 && !tok_f2, "left");
    return 0;
}}
"""
        r = _run_cbmc(tmp_path, f"int x;\n{v}{main}", "--unwind", "5")
        assert "VERIFICATION SUCCESSFUL" in r.stdout, r.stdout


class TestMessageFlows:
    def _messages(self) -> Bpmn:
        a = Process("A", "A")
        sa = _node(a, StartEvent, "SA", "", "")
        send = _node(a, IntermediateEvent, "Send", "", "", "send")
        ea = _node(a, EndEvent, "EA", "", "")
        _connect(a, sa, send, "fa1")
        _connect(a, send, ea, "fa2")
        b = Process("B", "B")
        sb = _node(b, StartEvent, "SB", "", "")
        recv = _node(b, IntermediateEvent, "Recv", "", "", "catch")
        eb = _node(b, EndEvent, "EB", "", "")
        _connect(b, sb, recv, "fb1")
        _connect(b, recv, eb, "fb2")
        msg = MessageFlow("M", "M")
        msg.source_node = send
        msg.target_node = recv
        send.add_out_msg(msg)
        recv.add_in_msg(msg)
        return _bpmn(a, b)

    def test_message_place_declared(self):
        assert "_Bool tok_M = 0;" in str(_generate(self._messages()))

    def test_sender_sets_message_place(self):
        v = _generate(self._messages())
        send = next(t for t in v.transitions if t.name == "Send")
        assert "tok_M = 1;" in repr(send.body)
        assert "tok_fa2 = 1;" in repr(send.body)

    def test_receiver_needs_seq_and_message_token(self):
        v = _generate(self._messages())
        recv = next(t for t in v.transitions if t.name == "Recv")
        assert recv.enable == "(tok_fb1) && (tok_M)"
        body = repr(recv.body)
        assert "tok_fb1 = 0;" in body and "tok_M = 0;" in body

    def test_done_waits_for_all_processes(self):
        assert _generate(self._messages()).done_expr == "done_A && done_B"

    def test_cbmc_message_workflow_finishes(self, tmp_path):
        v = _generate(self._messages())
        r = _run_cbmc(tmp_path, _program(v, bound=10), "--unwind", "11")
        assert "VERIFICATION SUCCESSFUL" in r.stdout, r.stdout


class TestCbmc:
    def test_linear_finishes(self, tmp_path):
        v = _generate(_linear())
        r = _run_cbmc(tmp_path, _program(v, bound=5), "--unwind", "6")
        assert "VERIFICATION SUCCESSFUL" in r.stdout, r.stdout

    def test_bound_too_small_fails(self, tmp_path):
        v = _generate(_linear())
        r = _run_cbmc(tmp_path, _program(v, bound=2), "--unwind", "3")
        assert "finished" in r.stdout and "VERIFICATION FAILED" in r.stdout

    def test_token_on_occupied_place_is_caught(self, tmp_path):
        p = Process("P", "P")
        s = _node(p, StartEvent, "S", "", "")
        t = _node(p, Task, "T", "")
        e = _node(p, EndEvent, "E", "", "")
        _connect(p, s, t, "f1")
        _connect(p, t, e, "f2")
        v = _generate(_bpmn(p))
        # the task's output place is already occupied when it runs
        main = f"""
int main(void) {{
    tok_f1 = 0; tok_S = 0; tok_f2 = 1; tok_f1 = 1;
    {STEP_FUNC}();
    return 0;
}}
"""
        r = _run_cbmc(tmp_path, f"{v}{main}", "--unwind", "2")
        assert "Attempting to place token in already-occupied place" in r.stdout
        assert "VERIFICATION FAILED" in r.stdout


class TestUnsupported:
    def test_unsupported_behavior_statement_is_an_error(self):
        p = Process("P", "P")
        _node(p, Task, "T", "printf(hello)")
        v = BpmnCbmcVisitor()
        v.visit_process(p)
        v.visit_task(p["T"])
        err = v.get_result().failure()
        assert isinstance(err, BpmnCbmcUnsupportedElementError)
        assert err.element_id == "T"

    def test_boundary_event_is_an_error(self):
        p = Process("P", "P")
        t = _node(p, Task, "T", "")
        be = Task.BoundaryEvent("BE", "BE", "", "", "T")
        t.add_boundary_event(be)
        v = BpmnCbmcVisitor()
        be.accept(v)
        err = v.get_result().failure()
        assert isinstance(err, BpmnCbmcUnsupportedElementError)
        assert err.element_id == "BE"

    def test_supported_workflow_is_success(self):
        v = _generate(_linear())
        assert is_successful(v.get_result())
        assert v.get_result().unwrap() == str(v)


class TestFace2Face:
    def _load(self, name):
        state = State.from_str((FACE2FACE / "state.txt").read_text()).unwrap()
        return bpmnmethods.from_xml(
            ET.fromstring((FACE2FACE / name).read_text()), state
        ).unwrap()

    def test_workflow_generates_step_function(self):
        bpmn = self._load("workflow.bpmn")
        v = _generate(bpmn)
        errors = [type(e).__name__ for e in v.errors]
        assert errors == []
        assert STEP_FUNC in str(v)

    def test_face2face_open_generates_step_function(self):
        v = _generate(self._load("face2face_open.bpmn"))
        assert STEP_FUNC in str(v)
        assert len(v.transitions) > 0


def _fork_join() -> Bpmn:
    """S -> Fork -> (A | B) -> Join -> E"""
    p = Process("P", "P")
    s = _node(p, StartEvent, "S", "", "")
    f = _node(p, ParallelGatewayNode, "F")
    a = _node(p, Task, "A", "")
    b = _node(p, Task, "B", "")
    j = _node(p, ParallelGatewayNode, "J")
    e = _node(p, EndEvent, "E", "", "")
    _connect(p, s, f, "f0")
    _connect(p, f, a, "fa")
    _connect(p, f, b, "fb")
    _connect(p, a, j, "ja")
    _connect(p, b, j, "jb")
    _connect(p, j, e, "f9")
    return _bpmn(p)


def _tr(v, name):
    return next(t for t in v.transitions if t.name == name)


class TestParallelGateway:
    def test_fork_starts_every_branch(self):
        t = _tr(_generate(_fork_join()), "F")
        assert t.enable == "(tok_f0)"
        body = repr(t.body)
        assert "tok_f0 = 0;" in body
        assert "tok_fa = 1;" in body and "tok_fb = 1;" in body
        assert "bpmn_collision = tok_fa || tok_fb;" in body

    def test_join_waits_for_every_incoming_flow(self):
        t = _tr(_generate(_fork_join()), "J")
        assert t.enable == "(tok_ja && tok_jb)"
        body = repr(t.body)
        assert "tok_ja = 0;" in body and "tok_jb = 0;" in body
        assert "tok_f9 = 1;" in body

    def test_no_error_for_parallel_gateways(self):
        assert is_successful(_generate(_fork_join()).get_result())

    def test_fork_join_cbmc_finishes(self, tmp_path):
        v = _generate(_fork_join())
        r = _run_cbmc(tmp_path, _program(v, bound=8), "--unwind", "9")
        assert "VERIFICATION SUCCESSFUL" in r.stdout, r.stdout

    def test_join_does_not_fire_on_one_token(self, tmp_path):
        v = _generate(_fork_join())
        main = f"""
int main(void) {{
    tok_S = 0; tok_ja = 1;
    {STEP_FUNC}();
    __CPROVER_assert(0, "join fired with one token");
    return 0;
}}
"""
        r = _run_cbmc(tmp_path, f"{v}{main}", "--unwind", "2")
        # the only enabled transition is B's... there is none: path is pruned
        assert "VERIFICATION SUCCESSFUL" in r.stdout, r.stdout

    def _loop_into_fork(self) -> Bpmn:
        """S -> F(fork, also entered by the loop) -> (T -> X, U -> X) -> J -> G -> (back to F | E)"""
        p = Process("P", "P")
        s = _node(p, StartEvent, "S", "", "")
        f = _node(p, ParallelGatewayNode, "F")
        t = _node(p, Task, "T", "")
        u = _node(p, Task, "U", "")
        j = _node(p, ParallelGatewayNode, "J")
        g = _node(p, ExclusiveGatewayNode, "G")
        e = _node(p, EndEvent, "E", "", "")
        _connect(p, s, f, "in")
        _connect(p, g, f, "back", "again == 1").is_leaf = True
        _connect(p, f, t, "ft")
        _connect(p, f, u, "fu")
        _connect(p, t, j, "tj")
        _connect(p, u, j, "uj")
        _connect(p, j, g, "jg")
        _connect(p, g, e, "out", "again != 1")
        return _bpmn(p)

    def test_fork_entered_by_loop_is_enabled_by_either_flow(self):
        v = _generate(self._loop_into_fork())
        fork = _tr(v, "F")
        assert fork.enable == "(tok_in || tok_back)"
        assert "tok_in = 0;" in repr(fork.body) and "tok_back = 0;" in repr(fork.body)

    def test_loop_into_fork_does_not_deadlock(self, tmp_path):
        v = _generate(self._loop_into_fork())
        main = f"""
int again;
int main(void) {{
    for (int i = 0; i < 12; i++) {{
        if ({v.done_expr}) break;
        {STEP_FUNC}();
        again = 0;
    }}
    __CPROVER_assert({v.done_expr}, "finished");
    return 0;
}}
"""
        r = _run_cbmc(
            tmp_path,
            f"int again;\n{v}{main}".replace("int again;\nint again", "int again"),
            "--unwind",
            "13",
        )
        assert "VERIFICATION SUCCESSFUL" in r.stdout, r.stdout

    def test_nested_parallel_gateways(self, tmp_path):
        """S -> F1 -> (F2 -> (A | B) -> J2 | C) -> J1 -> E"""
        p = Process("P", "P")
        s = _node(p, StartEvent, "S", "", "")
        f1 = _node(p, ParallelGatewayNode, "F1")
        f2 = _node(p, ParallelGatewayNode, "F2")
        a = _node(p, Task, "A", "")
        b = _node(p, Task, "B", "")
        c = _node(p, Task, "C", "")
        j2 = _node(p, ParallelGatewayNode, "J2")
        j1 = _node(p, ParallelGatewayNode, "J1")
        e = _node(p, EndEvent, "E", "", "")
        _connect(p, s, f1, "s")
        _connect(p, f1, f2, "f1f2")
        _connect(p, f1, c, "f1c")
        _connect(p, f2, a, "f2a")
        _connect(p, f2, b, "f2b")
        _connect(p, a, j2, "aj2")
        _connect(p, b, j2, "bj2")
        _connect(p, j2, j1, "j2j1")
        _connect(p, c, j1, "cj1")
        _connect(p, j1, e, "e")
        v = _generate(_bpmn(p))
        assert _tr(v, "F2").enable == "(tok_f1f2)"
        assert _tr(v, "J2").enable == "(tok_aj2 && tok_bj2)"
        assert _tr(v, "J1").enable == "(tok_j2j1 && tok_cj1)"
        r = _run_cbmc(tmp_path, _program(v, bound=12), "--unwind", "13")
        assert "VERIFICATION SUCCESSFUL" in r.stdout, r.stdout


def _task_visitor(behavior: str) -> BpmnCbmcVisitor:
    p = Process("P", "P")
    s = _node(p, StartEvent, "S", "", "")
    t = _node(p, Task, "T", behavior)
    e = _node(p, EndEvent, "E", "", "")
    _connect(p, s, t, "f1")
    _connect(p, t, e, "f2")
    return _generate(_bpmn(p))


STATE_DECLS = """
enum { red, green, blue };
int x = 0;
int color = red;
int y = 0;
"""


class TestBehaviors:
    def test_assignments(self):
        body = repr(_tr(_task_visitor("x = 1\ncolor = green;"), "T").body)
        assert "x = 1;" in body and "color = green;" in body
        assert body.index("tok_f1 = 0;") < body.index("x = 1;")
        assert body.index("x = 1;") < body.index("tok_f2 = 1;")

    def test_no_behavior_has_no_update(self):
        out = str(_task_visitor(""))
        assert UPDATE_STATE_FUNC not in out
        assert "bpmn_update_cwp" not in out

    def test_update_follows_behavior(self):
        v = _task_visitor("x = 1")
        assert "bpmn_update_cwp = 1;" in repr(_tr(v, "T").body)
        out = str(v)
        assert out.count(f"{UPDATE_STATE_FUNC}();") == 1
        assert out.index("switch (bpmn_choice)") < out.index(f"{UPDATE_STATE_FUNC}();")
        assert "_Bool bpmn_update_cwp = 0;" in out

    def test_skip_is_empty_behavior(self):
        assert "bpmn_update_cwp" not in str(_task_visitor("skip"))

    def test_true_false_become_c(self):
        out = str(_task_visitor("if\n:: true -> x = 1\n:: false -> x = 2\nfi"))
        assert "assume(1);" in out and "assume(0);" in out

    def test_if_is_nondeterministic_choice_without_loop(self):
        out = str(_task_visitor("if\n:: x == 0 -> x = 1\n:: else -> skip\nfi"))
        assert "bpmn_option_1 = nondet_uint()" in out
        assert "__CPROVER_assume(x == 0);" in out
        assert "__CPROVER_assume(!(x == 0));" in out
        assert "for (" not in out and "while" not in out

    def _run(self, tmp_path, behavior, check, init=""):
        v = _task_visitor(behavior)
        main = f"""
int main(void) {{
    {init}
    {STEP_FUNC}();
    {STEP_FUNC}();
    {check}
    return 0;
}}
"""
        prog = f"{STATE_DECLS}\nstatic void {UPDATE_STATE_FUNC}(void) {{}}\n{v}{main}"
        return _run_cbmc(tmp_path, prog, "--unwind", "3")

    def test_assign_changes_state(self, tmp_path):
        r = self._run(
            tmp_path,
            "x = 5\ncolor = blue",
            '__CPROVER_assert(x == 5 && color == blue, "assigned");',
        )
        assert "VERIFICATION SUCCESSFUL" in r.stdout, r.stdout

    def test_assign_wrong_value_fails(self, tmp_path):
        r = self._run(tmp_path, "x = 5", '__CPROVER_assert(x == 4, "wrong");')
        assert "VERIFICATION FAILED" in r.stdout

    def test_compare_picks_matching_branch(self, tmp_path):
        beh = "if\n:: x == 0 -> y = 1\n:: x != 0 -> y = 2\nfi"
        r = self._run(tmp_path, beh, '__CPROVER_assert(y == 1, "x was 0");')
        assert "VERIFICATION SUCCESSFUL" in r.stdout, r.stdout

    def test_else_only_when_nothing_else_holds(self, tmp_path):
        beh = "if\n:: x == 0 -> y = 1\n:: else -> y = 2\nfi"
        r = self._run(tmp_path, beh, '__CPROVER_assert(y == 1, "else not taken");')
        assert "VERIFICATION SUCCESSFUL" in r.stdout, r.stdout

    def test_nondeterministic_options_all_reachable(self, tmp_path):
        beh = "if\n:: true -> y = 1\n:: true -> y = 2\nfi"
        r = self._run(tmp_path, beh, '__CPROVER_assert(y == 1, "only one");')
        assert "VERIFICATION FAILED" in r.stdout

    def test_nested_if_and_multiline_option(self, tmp_path):
        beh = (
            "if\n:: x == 0 ->\n  y = 1;\n  x = 3;\n"
            ":: else ->\n  if\n  :: true -> y = 9\n  fi\nfi\ncolor = green"
        )
        r = self._run(
            tmp_path,
            beh,
            '__CPROVER_assert(y == 1 && x == 3 && color == green, "nested");',
        )
        assert "VERIFICATION SUCCESSFUL" in r.stdout, r.stdout

    def test_option_without_arrow_does_nothing(self, tmp_path):
        beh = "if\n:: x == 0 -> x = 7\n:: true\nfi"
        r = self._run(tmp_path, beh, '__CPROVER_assert(x == 0 || x == 7, "ok");')
        assert "VERIFICATION SUCCESSFUL" in r.stdout, r.stdout

    def test_assert_statement(self, tmp_path):
        r = self._run(tmp_path, "assert(x == 1)", "")
        assert "VERIFICATION FAILED" in r.stdout

    def test_behavior_in_one_line(self):
        out = str(_task_visitor("if :: true -> x = 1; y = 2 fi"))
        assert "x = 1;" in out and "y = 2;" in out


class TestCwpUpdate:
    """The CWP follows the state through task behaviors."""

    def _cwp_program(self, behavior, tmp_path, check):
        from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState

        cwp = Cwp()
        for n in ("A", "B"):
            cwp.states[n] = CwpState(n, n)
        a, b = cwp.states["A"], cwp.states["B"]

        def edge(name, src, dest, expr):
            e = CwpEdge(name, name)
            e.expression = expr
            e.set_dest(dest)
            dest.in_edges.append(e)
            if src is not None:
                e.set_source(src)
                src.out_edges.append(e)
            cwp.edges[name] = e

        edge("e0", None, a, "x == 0")
        edge("e1", a, b, "x == 1")
        cwp.start_state = a
        a.init_state = True
        cwp.end_states = [b]
        cv = CwpCbmcVisitor()
        cwp.accept(cv)
        v = _task_visitor(behavior)
        main = f"""
int main(void) {{
    {CALCULATE_STATE_FUNC}();
    {STEP_FUNC}(); {STEP_FUNC}();
    {check}
    return 0;
}}
"""
        return _run_cbmc(tmp_path, f"int x = 0;\n{cv}{v}{main}", "--unwind", "3")

    def test_cwp_moves_after_behavior(self, tmp_path):
        r = self._cwp_program(
            "x = 1", tmp_path, '__CPROVER_assert(cwp_state == CWP_STATE_B, "moved");'
        )
        assert "VERIFICATION SUCCESSFUL" in r.stdout, r.stdout

    def test_cwp_checks_invalid_move(self, tmp_path):
        r = self._cwp_program("x = 7", tmp_path, "")
        assert "VERIFICATION FAILED" in r.stdout
        assert "Not a valid CWP transition" in r.stdout or "no state" in r.stdout


class TestFace2FaceCbmc:
    DECLS = """
enum all { INIT, other };
enum TermsType { agreed, failed, pending, noRetry };
enum OwnerType { buyerName, sellerName };
#define paymentAmount 253
#define belowPaymentAmount 252
#define noRetryPayment 254
#define pendingPayment 255
enum TermsType terms = pending;
enum OwnerType backpackOwner = sellerName;
enum OwnerType paymentOwner = buyerName;
unsigned char paymentOffered = pendingPayment;
"""

    def _verify(self, tmp_path, name, final=""):
        state = State.from_str((FACE2FACE / "state.txt").read_text()).unwrap()
        bpmn = bpmnmethods.from_xml(
            ET.fromstring((FACE2FACE / name).read_text()), state
        ).unwrap()
        cwp = CwpXmlParser.from_xml(
            ET.fromstring((FACE2FACE / "cwp.xml").read_text()), state
        ).unwrap()
        cv = CwpCbmcVisitor()
        cwp.accept(cv)
        v = _generate(bpmn)
        assert v.errors == []
        bound = compute_bound(bpmn)
        # The loop can run forever (a failed negotiation starts over), so the
        # workflow is not required to finish; the bound cuts the paths off.
        program = f"""{self.DECLS}
{cv}{v}
int main(void) {{
    {CALCULATE_STATE_FUNC}();
    for (int i = 0; i < {bound}; i++) {{
        if ({v.done_expr}) break;
        {STEP_FUNC}();
    }}
    {final.format(done=v.done_expr)}
    return 0;
}}
"""
        src = tmp_path / "main.c"
        src.write_text(program)
        return subprocess.run(
            ["cbmc", str(src), "--unwind", str(bound + 1)],
            capture_output=True,
            text=True,
            timeout=300,
        )

    def test_workflow_verifies(self, tmp_path):
        r = self._verify(tmp_path, "workflow.bpmn")
        assert "VERIFICATION SUCCESSFUL" in r.stdout, r.stdout[-2000:]

    def test_face2face_open_verifies(self, tmp_path):
        r = self._verify(tmp_path, "face2face_open.bpmn")
        assert "VERIFICATION SUCCESSFUL" in r.stdout, r.stdout[-2000:]

    def test_workflow_can_finish(self, tmp_path):
        # the end event is reachable, so asserting it is not is a failure
        r = self._verify(
            tmp_path, "workflow.bpmn", '__CPROVER_assert(!({done}), "ended");'
        )
        assert "VERIFICATION FAILED" in r.stdout
        assert "ended: FAILURE" in r.stdout
