import shutil
import subprocess
from pathlib import Path

import pytest
from returns.pipeline import is_successful

from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState
from bpmncwpverify.core.error import FeelCbmcUnsupportedError
from bpmncwpverify.core.feel import parse
from bpmncwpverify.core.feel_tree import FeelExpr
from bpmncwpverify.core.state import State
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    END_STR,
    START_STR,
    CwpCbmcVisitor,
)

RESOURCES = Path(__file__).parent.parent / "resources" / "feel"

needs_cbmc = pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc not found")
needs_gcc = pytest.mark.skipif(shutil.which("gcc") is None, reason="gcc not found")


def _feel(text: str) -> FeelExpr | None:
    """The FEEL tree of a condition, None for no condition."""
    return parse(text).unwrap() if text else None


def _make_cwp(
    states: list[str], edges: list[tuple[str, str, str]], init_expr: str
) -> Cwp:
    """Build a CWP by hand; the first state is the start state."""
    cwp = Cwp()
    for name in states:
        cwp.states[name] = CwpState(name, name)
    cwp.start_state = cwp.states[states[0]]
    cwp.start_state.init_state = True
    init = CwpEdge("Init_Edge", "Init")
    init.expression = init_expr
    init.expression_tree = _feel(init_expr)
    init.set_dest(cwp.start_state)
    cwp.start_state.in_edges.append(init)
    for i, (src, dst, expr) in enumerate(edges):
        edge = CwpEdge(f"e{i}", f"Edge{i}")
        edge.expression = expr
        edge.expression_tree = _feel(expr)
        edge.set_source(cwp.states[src])
        edge.set_dest(cwp.states[dst])
        cwp.states[src].out_edges.append(edge)
        cwp.states[dst].in_edges.append(edge)
        cwp.edges[edge.id] = edge
    # edges into an already visited state must not be followed again
    seen: set[str] = set()

    def mark(state: CwpState) -> None:
        seen.add(state.id)
        for e in state.out_edges:
            e.is_leaf = e.dest.id in seen
            if not e.is_leaf:
                mark(e.dest)

    mark(cwp.start_state)
    return cwp


def _generate(cwp: Cwp) -> str:
    visitor = CwpCbmcVisitor()
    cwp.accept(visitor)
    return str(visitor)


# Start -> Mid (x == 1), Mid -> Mid2 (x == 2), Mid -> End (x == 3), Mid2 -> End (x == 3)
# Start is active when x == 0, Mid when x == 1, Mid2 when x == 2, End when x == 3
def _diamond() -> Cwp:
    return _make_cwp(
        ["Start", "Mid", "Mid2", "End"],
        [
            ("Start", "Mid", "x = 1"),
            ("Mid", "Mid2", "x = 2"),
            ("Mid", "End", "x = 3"),
            ("Mid2", "End", "x = 3"),
        ],
        "x = 0",
    )


def _program(cwp_c: str, body: str) -> str:
    return f"int x = 0;\n{cwp_c}\nint main(void) {{\n{body}\n}}\n"


def _run_cbmc(tmp_path: Path, program: str) -> subprocess.CompletedProcess[str]:
    src = tmp_path / "prog.c"
    src.write_text(program)
    return subprocess.run(
        ["cbmc", str(src)], capture_output=True, text=True, timeout=120
    )


class TestStructure:
    def test_markers(self):
        out = _generate(_diamond())
        assert out.startswith(START_STR)
        assert out.rstrip().endswith(END_STR)

    def test_state_enum_and_variable(self):
        out = _generate(_diamond())
        for name in ("Start", "Mid", "Mid2", "End"):
            assert f"CWP_STATE_{name}," in out
        assert "cwp_state_t cwp_state;" in out

    def test_start_state_condition_uses_init_edge(self):
        out = _generate(_diamond())
        assert "if (((x == 0)) && !((x == 1)))" in out

    def test_branching_state_ors_out_edges(self):
        out = _generate(_diamond())
        assert "if (((x == 1)) && !((x == 2) || (x == 3)))" in out

    def test_end_state_has_no_out_edges(self):
        out = _generate(_diamond())
        assert "if (((x == 3) && (x == 3)) && !(0))" in out

    def test_valid_moves_per_state(self):
        out = _generate(_diamond())
        assert "valid = next == CWP_STATE_Start || next == CWP_STATE_Mid;" in out
        assert (
            "valid = next == CWP_STATE_Mid || next == CWP_STATE_Mid2 || next == CWP_STATE_End;"
            in out
        )
        assert "valid = next == CWP_STATE_End;" in out

    def test_asserts_present(self):
        out = _generate(_diamond())
        assert "active == 1" in out
        assert "not a valid CWP transition" in out

    def test_no_loops(self):
        out = _generate(_diamond())
        assert "for (" not in out and "while" not in out

    def test_empty_expression_is_true(self):
        cwp = _make_cwp(["A", "B"], [("A", "B", "")], "x = 0")
        assert "!(1)" in _generate(cwp)

    def test_state_name_sanitized(self):
        cwp = _make_cwp(["A", "B C"], [("A", "B C", "x = 1")], "x = 0")
        assert "CWP_STATE_B_C," in _generate(cwp)

    def test_each_state_emitted_once(self):
        out = _generate(_diamond())
        assert out.count("CWP_STATE_End,") == 1

    def test_self_loop_edge_not_duplicated_in_valid_moves(self):
        cwp = _make_cwp(["A", "B"], [("A", "A", "x = 5"), ("A", "B", "x = 1")], "x = 0")
        out = _generate(cwp)
        assert "valid = next == CWP_STATE_A || next == CWP_STATE_B;" in out


@needs_gcc
class TestCompiles:
    def test_compiles_with_gcc(self, tmp_path):
        stub = "#define __CPROVER_assert(c, m) ((void)(c))\n"
        body = "cwp_init(); x = 1; cwp_update(); return 0;"
        src = tmp_path / "prog.c"
        src.write_text(stub + _program(_generate(_diamond()), body))
        result = subprocess.run(
            ["gcc", "-Wall", "-Werror", "-c", str(src), "-o", str(tmp_path / "p.o")],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr


@needs_cbmc
class TestCbmc:
    def test_valid_path_verifies(self, tmp_path):
        body = (
            "cwp_init();\n"
            "x = 1; cwp_update();\n"
            "x = 2; cwp_update();\n"
            "x = 3; cwp_update();\n"
            '__CPROVER_assert(cwp_state == CWP_STATE_End, "ended");\n'
            "return 0;"
        )
        result = _run_cbmc(tmp_path, _program(_generate(_diamond()), body))
        assert result.returncode == 0, result.stdout
        assert "VERIFICATION SUCCESSFUL" in result.stdout

    def test_unchanged_variable_stays_in_state(self, tmp_path):
        body = "cwp_init(); cwp_update(); cwp_update(); return 0;"
        result = _run_cbmc(tmp_path, _program(_generate(_diamond()), body))
        assert "VERIFICATION SUCCESSFUL" in result.stdout

    def test_skipped_edge_fails(self, tmp_path):
        # Start -> End is not an edge
        body = "cwp_init(); x = 3; cwp_update(); return 0;"
        result = _run_cbmc(tmp_path, _program(_generate(_diamond()), body))
        assert result.returncode != 0
        assert "not a valid CWP transition" in result.stdout

    def test_no_active_state_fails(self, tmp_path):
        body = "cwp_init(); x = 7; cwp_update(); return 0;"
        result = _run_cbmc(tmp_path, _program(_generate(_diamond()), body))
        assert result.returncode != 0
        assert "more than one state or no state" in result.stdout

    def test_init_with_unmatched_variables_fails(self, tmp_path):
        body = "x = 7; cwp_init(); return 0;"
        result = _run_cbmc(tmp_path, _program(_generate(_diamond()), body))
        assert result.returncode != 0

    def test_overlapping_states_fail(self, tmp_path):
        # B and C are both active when x == 1
        cwp = _make_cwp(
            ["A", "B", "C"], [("A", "B", "x = 1"), ("A", "C", "x = 1")], "x = 0"
        )
        body = "x = 1; cwp_init(); return 0;"
        result = _run_cbmc(tmp_path, _program(_generate(cwp), body))
        assert result.returncode != 0
        assert "more than one state or no state" in result.stdout

    def test_nondeterministic_variable_changes(self, tmp_path):
        # x may take any value after each step; invalid moves must be found
        body = "cwp_init();\nx = nondet_int(); cwp_update();\nreturn 0;"
        prog = "int nondet_int(void);\n" + _program(_generate(_diamond()), body)
        result = _run_cbmc(tmp_path, prog)
        assert result.returncode != 0


FACE2FACE_C_VARS = """
typedef enum { agreed, failed, noRetry, pending } TermsType;
typedef enum { buyerName, sellerName } OwnerType;
#define paymentAmount 253
#define belowPaymentAmount 252
#define noRetryPayment 254
#define pendingPayment 255
TermsType terms = pending;
OwnerType backpackOwner = sellerName;
OwnerType paymentOwner = buyerName;
unsigned char paymentOffered = pendingPayment;
"""


@needs_cbmc
def test_face2face_cwp_compiles_and_initializes(tmp_path):
    from xml.etree.ElementTree import parse

    state = State.from_str((RESOURCES / "face2face" / "state.txt").read_text())
    assert is_successful(state)
    root = parse(RESOURCES / "face2face" / "cwp.xml").getroot()
    cwp = CwpXmlParser.from_xml(root, state.unwrap())
    assert is_successful(cwp)

    cwp_c = _generate(cwp.unwrap())
    program = FACE2FACE_C_VARS + cwp_c + "\nint main(void) { cwp_init(); return 0; }\n"
    result = _run_cbmc(tmp_path, program)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "VERIFICATION SUCCESSFUL" in result.stdout


def test_unsupported_edge_condition_is_an_error():
    cwp = _make_cwp(["A", "B"], [("A", "B", "x ** 9 > 1")], "x = 0")
    visitor = CwpCbmcVisitor()
    cwp.accept(visitor)
    assert isinstance(visitor.get_result().failure(), FeelCbmcUnsupportedError)
    assert "#error" in str(visitor)


def test_get_result_is_the_generated_c():
    visitor = CwpCbmcVisitor()
    _diamond().accept(visitor)
    assert visitor.get_result().unwrap() == str(visitor)
