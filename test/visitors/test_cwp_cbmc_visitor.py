# type: ignore
import subprocess
from xml.etree.ElementTree import fromstring

from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState
from bpmncwpverify.core.state import State
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    END_STR,
    START_STR,
    CwpCbmcVisitor,
)

FACE2FACE = "./test/resources/face2face/"


def _link(cwp: Cwp, src: CwpState, dest: CwpState, expr: str) -> CwpEdge:
    edge = CwpEdge(f"e{len(cwp.edges)}", f"e{len(cwp.edges)}")
    edge.expression = expr
    edge.source = src
    edge.dest = dest
    src.out_edges.append(edge)
    dest.in_edges.append(edge)
    cwp.edges[edge.id] = edge
    return edge


def _cwp() -> Cwp:
    """
    init (x == 0, entered by an init edge) -> mid (x == 1) -> done (x == 2)
                                          \\-> bad (x == 3)
    done and bad are terminal; mid also loops back to init (x == 0), so the
    graph has a cycle and a state with two in edges
    """
    cwp = Cwp()
    for n in ("init", "mid", "done", "bad"):
        cwp.states[n] = CwpState(n, n)
    s = cwp.states
    init_edge = CwpEdge("Init_Edge", "init_edge")
    init_edge.expression = "x == 0"
    init_edge.dest = s["init"]
    s["init"].in_edges.append(init_edge)
    cwp.start_state = s["init"]
    cwp.end_states = [s["done"], s["bad"]]
    _link(cwp, s["init"], s["mid"], "x == 1")
    _link(cwp, s["mid"], s["done"], "x == 2")
    _link(cwp, s["mid"], s["bad"], "x == 3")
    back = _link(cwp, s["mid"], s["init"], "x == 0")
    back.is_leaf = True
    return cwp


def _generate(cwp: Cwp) -> CwpCbmcVisitor:
    visitor = CwpCbmcVisitor()
    cwp.accept(visitor)
    return visitor


def _program(visitor: CwpCbmcVisitor, decls: str, body: str) -> str:
    return f"""#include <stdbool.h>
{decls}
{visitor}
int main(void) {{
{body}
    return 0;
}}
"""


def _cbmc(tmp_path, program: str) -> subprocess.CompletedProcess:
    src = tmp_path / "prog.c"
    src.write_text(program)
    return subprocess.run(
        ["cbmc", str(src), "--unwind", "2"], capture_output=True, text=True
    )


class TestCwpCbmcVisitor:
    def test_visit_cwp_writes_header(self):
        visitor = CwpCbmcVisitor()
        assert visitor.visit_cwp(Cwp())
        assert START_STR in str(visitor.cwp_states)

    def test_visit_state_collects_each_state_once(self):
        visitor = CwpCbmcVisitor()
        state = CwpState("a", "a")
        assert visitor.visit_state(state)
        assert not visitor.visit_state(state)
        assert visitor.states == [state]

    def test_states_become_enum_constants(self):
        out = str(_generate(_cwp()))
        assert (
            "enum cwp_state_type { CWP_STATE_init, CWP_STATE_mid, "
            "CWP_STATE_done, CWP_STATE_bad };" in out
        )
        assert END_STR in out

    def test_state_guard_uses_in_and_out_edges(self):
        out = str(_generate(_cwp()))
        # start state: init edge in, out edge to mid
        assert "bool init_prime = ((x == 0) && (x == 0)) && !((x == 1));" in out
        # inner state: one in edge, three out edges
        assert (
            "bool mid_prime = ((x == 1)) && !((x == 2) || (x == 3) || (x == 0));" in out
        )
        # terminal state: no out edges
        assert "bool done_prime = ((x == 2)) && !(false);" in out

    def test_state_without_in_edges_is_true_guarded(self):
        cwp = Cwp()
        a, b = CwpState("a", "a"), CwpState("b", "b")
        cwp.states = {"a": a, "b": b}
        cwp.start_state = a
        _link(cwp, a, b, "x == 1")
        out = str(_generate(cwp))
        assert "bool a_prime = (true) && !((x == 1));" in out

    def test_edges_become_valid_transitions(self):
        out = str(_generate(_cwp()))
        assert (
            "cwp_valid_transition = cwp_next == CWP_STATE_init || "
            "cwp_next == CWP_STATE_mid;"
        ) in out
        assert (
            "cwp_valid_transition = cwp_next == CWP_STATE_mid || "
            "cwp_next == CWP_STATE_done || cwp_next == CWP_STATE_bad || "
            "cwp_next == CWP_STATE_init;"
        ) in out
        # terminal state can only stay put
        assert "cwp_valid_transition = cwp_next == CWP_STATE_done;" in out

    def test_assertions_present(self):
        out = str(_generate(_cwp()))
        assert "cwp_sum_of_active_states == 1" in out
        assert "__CPROVER_assert(cwp_valid_transition" in out

    def test_empty_cwp_generates_no_functions(self):
        visitor = CwpCbmcVisitor()
        visitor.end_visit_cwp(Cwp())
        assert str(visitor.update_state_func) == ""

    def test_compiles_and_follows_edges(self, tmp_path):
        visitor = _generate(_cwp())
        body = """
    x = 0; cwp_calculate_state();
    __CPROVER_assert(cwp_state == CWP_STATE_init, "starts in init");
    x = 1; cwp_update_state();
    __CPROVER_assert(cwp_state == CWP_STATE_mid, "moved to mid");
    x = 1; cwp_update_state();
    __CPROVER_assert(cwp_state == CWP_STATE_mid, "stayed in mid");
    x = 0; cwp_update_state();
    __CPROVER_assert(cwp_state == CWP_STATE_init, "back to init");
    x = 1; cwp_update_state();
    x = 2; cwp_update_state();
    __CPROVER_assert(cwp_state == CWP_STATE_done, "reached done");
"""
        result = _cbmc(tmp_path, _program(visitor, "int x;", body))
        assert result.returncode == 0, result.stdout
        assert "VERIFICATION SUCCESSFUL" in result.stdout

    def test_invalid_transition_fails(self, tmp_path):
        visitor = _generate(_cwp())
        # init -> done skips mid
        body = "x = 0; cwp_calculate_state(); x = 2; cwp_update_state();"
        result = _cbmc(tmp_path, _program(visitor, "int x;", body))
        assert "VERIFICATION FAILED" in result.stdout
        assert "not a valid CWP transition" in result.stdout

    def test_terminal_state_cannot_be_left(self, tmp_path):
        visitor = _generate(_cwp())
        body = (
            "x = 0; cwp_calculate_state(); x = 1; cwp_update_state();"
            "x = 2; cwp_update_state(); x = 0; cwp_update_state();"
        )
        result = _cbmc(tmp_path, _program(visitor, "int x;", body))
        assert "VERIFICATION FAILED" in result.stdout

    def test_no_active_state_fails(self, tmp_path):
        visitor = _generate(_cwp())
        body = "x = 0; cwp_calculate_state(); x = 7; cwp_update_state();"
        result = _cbmc(tmp_path, _program(visitor, "int x;", body))
        assert "VERIFICATION FAILED" in result.stdout
        assert "in more than one or no state" in result.stdout

    def test_more_than_one_active_state_fails(self, tmp_path):
        cwp = Cwp()
        a, b, c = (CwpState(n, n) for n in "abc")
        cwp.states = {"a": a, "b": b, "c": c}
        cwp.start_state = a
        init = CwpEdge("Init_Edge", "i")
        init.expression = "x == 0"
        init.dest = a
        a.in_edges.append(init)
        _link(cwp, a, b, "x == 1")
        _link(cwp, a, c, "x == 1")  # b and c are both active when x == 1
        visitor = _generate(cwp)
        body = "x = 0; cwp_calculate_state(); x = 1; cwp_update_state();"
        result = _cbmc(tmp_path, _program(visitor, "int x;", body))
        assert "VERIFICATION FAILED" in result.stdout
        assert "in more than one or no state" in result.stdout

    def test_bad_initial_values_fail(self, tmp_path):
        visitor = _generate(_cwp())
        result = _cbmc(
            tmp_path, _program(visitor, "int x = 9;", "cwp_calculate_state();")
        )
        assert "VERIFICATION FAILED" in result.stdout
        assert "initial values" in result.stdout

    def test_face2face(self, tmp_path):
        with open(FACE2FACE + "state.txt") as f:
            state = State.from_str(f.read()).unwrap()
        with open(FACE2FACE + "cwp.xml") as f:
            cwp = CwpXmlParser.from_xml(fromstring(f.read()), state).unwrap()
        visitor = _generate(cwp)
        decls = """
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
        body = """
    cwp_calculate_state();
    __CPROVER_assert(cwp_state == CWP_STATE_Init_Purchase_Pending, "init");
    terms = agreed; cwp_update_state();
    __CPROVER_assert(cwp_state == CWP_STATE_Negotiations, "negotiating");
    paymentOffered = paymentAmount; cwp_update_state();
    __CPROVER_assert(cwp_state == CWP_STATE_Purchase_Agreed, "agreed");
    paymentOwner = sellerName; backpackOwner = buyerName; cwp_update_state();
    __CPROVER_assert(cwp_state == CWP_STATE_Ownerships_Switched, "switched");
"""
        result = _cbmc(tmp_path, _program(visitor, decls, body))
        assert result.returncode == 0, result.stdout
