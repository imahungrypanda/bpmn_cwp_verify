# type: ignore
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

from returns.pipeline import is_successful

from bpmncwpverify.core.accessmethods import bpmnmethods
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
        assert "// behavior of T" in body

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
    def test_parallel_gateway_is_an_error(self):
        p = Process("P", "P")
        s = _node(p, StartEvent, "S", "", "")
        g = _node(p, ParallelGatewayNode, "PG")
        e = _node(p, EndEvent, "E", "", "")
        _connect(p, s, g, "a")
        _connect(p, g, e, "b")
        v = _generate(_bpmn(p))
        result = v.get_result()
        assert not is_successful(result)
        err = result.failure()
        assert isinstance(err, BpmnCbmcUnsupportedElementError)
        assert err.element_id == "PG"

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
        # parallel gateways arrive with S4; nothing else may be unsupported
        assert set(errors) <= {"BpmnCbmcUnsupportedElementError"}
        assert STEP_FUNC in str(v)

    def test_face2face_open_generates_step_function(self):
        v = _generate(self._load("face2face_open.bpmn"))
        assert STEP_FUNC in str(v)
        assert len(v.transitions) > 0
