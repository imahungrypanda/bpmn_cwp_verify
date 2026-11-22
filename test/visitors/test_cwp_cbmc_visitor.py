# type: ignore
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest
from returns.pipeline import is_successful

from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState
from bpmncwpverify.core.state import State
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    END_STR,
    START_STR,
    CwpCbmcVisitor,
)

pytestmark = pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc missing")


def make_cwp(state_names, edges, start_in_expr=None):
    """edges: (source, dest, expression). First state is the start state."""
    cwp = Cwp()
    for name in state_names:
        cwp.states[name] = CwpState(name, name)
    for i, (src, dst, expr) in enumerate(edges):
        edge = CwpEdge(f"e{i}", f"Edge{i}")
        edge.expression = expr
        edge.set_source(cwp.states[src])
        edge.set_dest(cwp.states[dst])
        cwp.states[src].out_edges.append(edge)
        cwp.states[dst].in_edges.append(edge)
        cwp.edges[edge.id] = edge
    cwp.start_state = cwp.states[state_names[0]]
    if start_in_expr is not None:
        edge = CwpEdge("Init_Edge", "Init")
        edge.expression = start_in_expr
        edge.set_dest(cwp.start_state)
        cwp.start_state.in_edges.append(edge)
    cwp.end_states = [s for s in cwp.states.values() if not s.out_edges]
    return cwp


def generate(cwp):
    visitor = CwpCbmcVisitor()
    cwp.accept(visitor)
    return str(visitor)


def run_cbmc(tmp_path, decls, cwp_c, main_body):
    src = tmp_path / "prog.c"
    src.write_text(f"{decls}\n{cwp_c}\nint main(void) {{\n{main_body}\n}}\n")
    return subprocess.run(
        ["cbmc", str(src), "--unwind", "3"], capture_output=True, text=True
    )


# Start -> A (x == 1) -> B (x == 2); A -> Start (x == 0, a loop); B is the end.
LINEAR = (
    ["Start", "A", "B"],
    [("Start", "A", "x == 1"), ("A", "B", "x == 2"), ("A", "Start", "x == 0")],
)


NO_CYCLE = (["Start", "A", "B"], [("Start", "A", "x == 1"), ("A", "B", "x == 2")])


def test_generates_declarations_for_each_state():
    out = generate(make_cwp(*LINEAR, start_in_expr="x == 0"))
    assert START_STR in out
    assert END_STR in out
    assert "enum cwp_state_id { CWP_Start, CWP_A, CWP_B };" in out
    assert "static enum cwp_state_id cwp_state = CWP_Start;" in out


def test_each_state_gets_a_guard_from_its_edges():
    out = generate(make_cwp(*LINEAR, start_in_expr="x == 0"))
    # in-edges must hold and no out-edge may hold
    assert "_Bool cwp_next_Start = ((x == 0) && (x == 0)) && !((x == 1));" in out
    assert "_Bool cwp_next_A = ((x == 1)) && !((x == 2) || (x == 0));" in out
    assert "_Bool cwp_next_B = ((x == 2)) && !(0);" in out


def test_updates_assert_one_state_and_valid_edges():
    out = generate(make_cwp(*LINEAR, start_in_expr="x == 0"))
    assert "cwp_active_states = cwp_next_Start + cwp_next_A + cwp_next_B;" in out
    assert "CWP: in more than one or no state" in out
    assert "CWP: not a valid CWP transition" in out
    # staying put plus each out edge
    assert "(cwp_state == CWP_A && (cwp_next_A || cwp_next_B || cwp_next_Start))" in out
    assert "(cwp_state == CWP_B && (cwp_next_B))" in out


def test_no_loops_over_states():
    out = generate(make_cwp(*LINEAR, start_in_expr="x == 0"))
    assert "for (" not in out
    assert "while" not in out


def test_empty_expression_is_true():
    cwp = make_cwp(["S", "T"], [("S", "T", "")], start_in_expr="x == 0")
    out = generate(cwp)
    assert "_Bool cwp_next_T = (1) && !(0);" in out


def test_start_state_without_in_edges_is_only_left_by_an_edge():
    out = generate(make_cwp(*NO_CYCLE))
    # start is not recomputed, only moved out of through its edges
    assert "cwp_next_Start" not in out
    assert "cwp_start_active" in out
    assert "(cwp_start_active && (cwp_next_A))" in out


def test_each_state_visited_once_in_cycle():
    cwp = make_cwp(*LINEAR, start_in_expr="x == 0")
    visitor = CwpCbmcVisitor()
    cwp.accept(visitor)
    assert [s.name for s in visitor.states] == ["Start", "A", "B"]


DECLS = "int x = 0;"


def test_generated_c_compiles_and_valid_walk_passes(tmp_path):
    cwp_c = generate(make_cwp(*LINEAR, start_in_expr="x == 0"))
    body = """
        cwp_calculate_state();
        __CPROVER_assert(cwp_state == CWP_Start, "initial");
        x = 1; cwp_update_state();
        __CPROVER_assert(cwp_state == CWP_A, "moved to A");
        cwp_update_state(); // no change, stays
        x = 2; cwp_update_state();
        __CPROVER_assert(cwp_state == CWP_B, "moved to B");
    """
    result = run_cbmc(tmp_path, DECLS, cwp_c, body)
    assert "VERIFICATION SUCCESSFUL" in result.stdout, result.stdout


def test_skipping_a_state_is_an_invalid_transition(tmp_path):
    cwp_c = generate(make_cwp(*LINEAR, start_in_expr="x == 0"))
    body = "cwp_calculate_state(); x = 2; cwp_update_state();"
    result = run_cbmc(tmp_path, DECLS, cwp_c, body)
    assert "VERIFICATION FAILED" in result.stdout
    assert "not a valid CWP transition" in result.stdout


def test_no_state_active_fails(tmp_path):
    cwp_c = generate(make_cwp(*LINEAR, start_in_expr="x == 0"))
    body = "cwp_calculate_state(); x = 7; cwp_update_state();"
    result = run_cbmc(tmp_path, DECLS, cwp_c, body)
    assert "VERIFICATION FAILED" in result.stdout
    assert "in more than one or no state" in result.stdout


def test_two_states_active_fails(tmp_path):
    # both in-edge conditions can hold at once for x > 5
    cwp = make_cwp(
        ["S", "T", "U"],
        [("S", "T", "x > 5"), ("S", "U", "x > 3")],
        start_in_expr="x == 0",
    )
    body = "cwp_calculate_state(); x = 6; cwp_update_state();"
    result = run_cbmc(tmp_path, DECLS, generate(cwp), body)
    assert "VERIFICATION FAILED" in result.stdout
    assert "in more than one or no state" in result.stdout


def test_start_state_without_in_edges_compiles_and_moves(tmp_path):
    cwp_c = generate(make_cwp(*NO_CYCLE))
    body = """
        cwp_calculate_state();
        x = 1; cwp_update_state();
        __CPROVER_assert(cwp_state == CWP_A, "moved to A");
    """
    result = run_cbmc(tmp_path, DECLS, cwp_c, body)
    assert "VERIFICATION SUCCESSFUL" in result.stdout, result.stdout


FACE2FACE = "test/resources/face2face"
FACE2FACE_DECLS = """
enum TermsType { agreed, failed, pending, noRetry };
enum OwnerType { buyerName, sellerName };
enum TermsType terms = pending;
enum OwnerType backpackOwner = sellerName;
enum OwnerType paymentOwner = buyerName;
const unsigned char paymentAmount = 253;
const unsigned char belowPaymentAmount = 252;
const unsigned char noRetryPayment = 254;
const unsigned char pendingPayment = 255;
unsigned char paymentOffered = 255;
"""


def load_face2face():
    with open(f"{FACE2FACE}/state.txt") as f:
        state = State.from_str(f.read())
    assert is_successful(state)
    root = ET.parse(f"{FACE2FACE}/cwp.xml").getroot()
    cwp = CwpXmlParser.from_xml(root, state.unwrap())
    assert is_successful(cwp)
    return cwp.unwrap()


def test_face2face_cwp_follows_its_edges(tmp_path):
    cwp_c = generate(load_face2face())
    body = """
        cwp_calculate_state();
        __CPROVER_assert(cwp_state == CWP_Init_Purchase_Pending, "init");
        terms = agreed;
        cwp_update_state();
        __CPROVER_assert(cwp_state == CWP_Negotiations, "negotiating");
        paymentOffered = paymentAmount;
        cwp_update_state();
        __CPROVER_assert(cwp_state == CWP_Purchase_Agreed, "agreed");
        paymentOwner = sellerName; backpackOwner = buyerName;
        cwp_update_state();
        __CPROVER_assert(cwp_state == CWP_Ownerships_Switched, "switched");
    """
    result = run_cbmc(tmp_path, FACE2FACE_DECLS, cwp_c, body)
    assert "VERIFICATION SUCCESSFUL" in result.stdout, result.stdout + cwp_c
