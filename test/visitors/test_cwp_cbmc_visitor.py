# type: ignore
import shutil
import subprocess
from pathlib import Path

import pytest
from returns.unsafe import unsafe_perform_io

from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState
from bpmncwpverify.core.state import State
from bpmncwpverify.util.file import element_tree_from_string, read_file_as_string
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    END_STR,
    START_STR,
    CwpCbmcVisitor,
)

FACE2FACE = Path(__file__).parent.parent / "resources" / "face2face"

HAS_GCC = shutil.which("gcc") is not None
HAS_CBMC = shutil.which("cbmc") is not None


def _make_cwp(states, edges):
    """states: names, first is the start; edges: (src, dest, expression).
    A src of None is the edge into the start state."""
    cwp = Cwp()
    by_name = {name: CwpState(name, name) for name in states}
    cwp.states = {s.id: s for s in by_name.values()}
    cwp.start_state = by_name[states[0]]
    cwp.start_state.init_state = True
    for i, (src, dest, expr) in enumerate(edges):
        edge = CwpEdge(f"e{i}", f"e{i}")
        edge.expression = expr
        edge.set_dest(by_name[dest])
        if src is not None:
            edge.set_source(by_name[src])
            by_name[src].out_edges.append(edge)
        by_name[dest].in_edges.append(edge)
        cwp.edges[edge.id] = edge
    return cwp


def _generate(cwp):
    visitor = CwpCbmcVisitor()
    cwp.accept(visitor)
    return visitor


# A -> B -> C, with B -> D as a branch.
# `x` picks the state: 0=A, 1=B, 2=C, 3=D.
def _chain_cwp():
    return _make_cwp(
        ["A", "B", "C", "D"],
        [
            (None, "A", "x == 0"),
            ("A", "B", "x == 1"),
            ("B", "C", "x == 2"),
            ("B", "D", "x == 3"),
        ],
    )


def _program(visitor, body, decls="int x = 0;"):
    return f"""{decls}
{visitor}
int main(void) {{
{body}
    return 0;
}}
"""


def _compile_and_run(tmp_path, source):
    if not HAS_GCC:
        pytest.skip("gcc not available")
    src = tmp_path / "prog.c"
    src.write_text(source)
    exe = tmp_path / "prog"
    subprocess.run(
        ["gcc", "-Wall", "-Werror", "-o", str(exe), str(src)],
        check=True,
        capture_output=True,
    )
    return subprocess.run([str(exe)], capture_output=True).returncode


class TestCwpCbmcVisitor:
    def test_visit_cwp_continues(self, mocker):
        assert CwpCbmcVisitor().visit_cwp(mocker.Mock()) is True

    def test_declarations_enum_and_variable(self):
        out = str(_generate(_chain_cwp()))
        assert START_STR in out
        assert END_STR in out
        for name in ["A", "B", "C", "D"]:
            assert f"CWP_{name}" in out
        assert "cwp_state_t cwp_state;" in out

    def test_each_state_has_active_flag_and_valid_moves(self):
        visitor = _generate(_chain_cwp())
        out = str(visitor)
        for name in ["A", "B", "C", "D"]:
            assert f"_Bool cwp_active_{name} = " in out
            assert f"case CWP_{name}:" in out
        assert [s.name for s in visitor.states] == ["A", "B", "C", "D"]

    def test_state_without_in_edges_is_active_by_default(self):
        out = str(_generate(_make_cwp(["A", "B"], [("A", "B", "x == 1")])))
        assert "_Bool cwp_active_A = (1) && !((x == 1));" in out

    def test_state_without_out_edges_never_leaves(self):
        out = str(_generate(_chain_cwp()))
        assert "_Bool cwp_active_C = ((x == 2)) && !(0);" in out
        assert "assert((cwp_next_state == CWP_C) &&" in out

    def test_multiple_edges_are_parenthesised(self):
        cwp = _make_cwp(
            ["A", "B", "C"],
            [
                (None, "A", "x == 0 || y == 0"),
                ("A", "B", "x == 1 || y == 1"),
                ("A", "C", "x == 2"),
            ],
        )
        out = str(_generate(cwp))
        assert "!((x == 1 || y == 1) || (x == 2))" in out

    def test_branch_allows_each_destination_and_staying(self):
        out = str(_generate(_chain_cwp()))
        assert (
            "assert((cwp_next_state == CWP_B || cwp_next_state == CWP_C || "
            "cwp_next_state == CWP_D) &&"
        ) in out

    def test_duplicate_edges_listed_once(self):
        cwp = _make_cwp(
            ["A", "B"],
            [(None, "A", "x == 0"), ("A", "B", "x == 1"), ("A", "B", "x == 2")],
        )
        out = str(_generate(cwp))
        assert ("assert((cwp_next_state == CWP_A || cwp_next_state == CWP_B) &&") in out

    def test_cycle_visits_each_state_once(self):
        cwp = _make_cwp(
            ["A", "B"],
            [(None, "A", "x == 0"), ("A", "B", "x == 1"), ("B", "A", "x == 0")],
        )
        cwp.edges["e2"].is_leaf = True
        visitor = _generate(cwp)
        assert [s.name for s in visitor.states] == ["A", "B"]

    def test_state_names_are_sanitised(self):
        cwp = _make_cwp(["A b", "C"], [("A b", "C", "x == 1")])
        out = str(_generate(cwp))
        assert "CWP_A_b" in out

    def test_compiles_and_follows_valid_edges(self, tmp_path):
        visitor = _generate(_chain_cwp())
        body = """
    cwp_init();
    if (cwp_state != CWP_A) return 10;
    cwp_update();
    if (cwp_state != CWP_A) return 11;
    x = 1; cwp_update();
    if (cwp_state != CWP_B) return 12;
    x = 3; cwp_update();
    if (cwp_state != CWP_D) return 13;
    cwp_update();
    if (cwp_state != CWP_D) return 14;
"""
        assert _compile_and_run(tmp_path, _program(visitor, body)) == 0

    def test_init_uses_initial_values(self, tmp_path):
        visitor = _generate(_chain_cwp())
        body = "cwp_init(); if (cwp_state != CWP_B) return 10;"
        assert _compile_and_run(tmp_path, _program(visitor, body, "int x = 1;")) == 0

    def test_invalid_edge_fails_assertion(self, tmp_path):
        visitor = _generate(_chain_cwp())
        body = "cwp_init(); x = 2; cwp_update();"  # A -> C is not an edge
        assert _compile_and_run(tmp_path, _program(visitor, body)) != 0

    def test_no_active_state_fails_assertion(self, tmp_path):
        visitor = _generate(_chain_cwp())
        body = "cwp_init(); x = 7; cwp_update();"
        assert _compile_and_run(tmp_path, _program(visitor, body)) != 0

    def test_overlapping_states_fail_assertion(self, tmp_path):
        cwp = _make_cwp(
            ["A", "B", "C"],
            [
                (None, "A", "x >= 0"),
                ("A", "B", "x >= 5"),
                ("A", "C", "x >= 3"),
            ],
        )
        visitor = _generate(cwp)
        # x == 6 makes both B and C active
        body = "cwp_init();"
        decls = "int x = 6;"
        assert _compile_and_run(tmp_path, _program(visitor, body, decls)) != 0

    @pytest.mark.skipif(not HAS_CBMC, reason="cbmc not available")
    def test_cbmc_checks_valid_edges(self, tmp_path):
        visitor = _generate(_chain_cwp())

        def run(body):
            src = tmp_path / "p.c"
            src.write_text(
                _program(
                    visitor,
                    body,
                    "int nondet_int(void);\nint x = 0;",
                )
            )
            return subprocess.run(["cbmc", str(src)], capture_output=True).returncode

        ok = "cwp_init(); x = nondet_int(); __CPROVER_assume(x == 0 || x == 1); cwp_update();"
        assert run(ok) == 0
        bad = "cwp_init(); x = nondet_int(); __CPROVER_assume(x == 2); cwp_update();"
        assert run(bad) != 0


def _load_face2face():
    def read(name):
        return unsafe_perform_io(read_file_as_string(str(FACE2FACE / name))).unwrap()

    state = State.from_str(read("state.txt")).unwrap()
    xml = unsafe_perform_io(element_tree_from_string(read("cwp.xml"))).unwrap()
    return state, CwpXmlParser.from_xml(xml, state).unwrap()


class TestCwpCbmcVisitorFace2Face:
    def _program(self, state, visitor, body):
        decls = """
enum { pending, agreed, failed, noRetry };
enum { buyerName, sellerName };
#define paymentAmount 253
#define belowPaymentAmount 252
#define noRetryPayment 254
#define pendingPayment 255
int nondet_int(void);
int terms = pending;
int backpackOwner = sellerName;
int paymentOwner = buyerName;
unsigned char paymentOffered = pendingPayment;
"""
        return _program(visitor, body, decls)

    def test_all_cwp_states_generated(self):
        state, cwp = _load_face2face()
        visitor = _generate(cwp)
        assert len(visitor.states) == len(cwp.states) == 6
        out = str(visitor)
        for cwp_state in cwp.states.values():
            assert f"CWP_{cwp_state.name}" in out

    def test_compiles_and_starts_in_state_from_initial_values(self, tmp_path):
        state, cwp = _load_face2face()
        visitor = _generate(cwp)
        # The initial values satisfy Init_Purchase_Pending's incoming edge, so
        # that is where the CWP starts.
        body = "cwp_init(); if (cwp_state != CWP_Init_Purchase_Pending) return 10;"
        assert _compile_and_run(tmp_path, self._program(state, visitor, body)) == 0

    def test_walks_the_happy_path(self, tmp_path):
        state, cwp = _load_face2face()
        visitor = _generate(cwp)
        body = """
    cwp_init();
    if (cwp_state != CWP_Init_Purchase_Pending) return 9;
    paymentOwner = buyerName; backpackOwner = sellerName; cwp_update();
    if (cwp_state != CWP_Init_Purchase_Pending) return 10;
    paymentOffered = belowPaymentAmount; cwp_update();
    if (cwp_state != CWP_Negotiations) return 11;
    terms = agreed; paymentOffered = paymentAmount; cwp_update();
    if (cwp_state != CWP_Purchase_Agreed) return 12;
    paymentOwner = sellerName; backpackOwner = buyerName; cwp_update();
    if (cwp_state != CWP_Ownerships_Switched) return 13;
"""
        assert _compile_and_run(tmp_path, self._program(state, visitor, body)) == 0

    def test_skipping_a_state_fails_assertion(self, tmp_path):
        state, cwp = _load_face2face()
        visitor = _generate(cwp)
        # Init_Purchase_Pending -> Purchase_Agreed is not an edge.
        body = """
    cwp_init();
    terms = agreed; paymentOffered = paymentAmount; cwp_update();
"""
        assert _compile_and_run(tmp_path, self._program(state, visitor, body)) != 0
