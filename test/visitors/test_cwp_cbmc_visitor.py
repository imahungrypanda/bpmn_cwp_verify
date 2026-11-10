import shutil
import subprocess
from pathlib import Path

import pytest
from returns.result import Success

from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState
from bpmncwpverify.core.error import FeelCbmcUnsupportedError
from bpmncwpverify.core.feel import parse_expression
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    END_STR,
    START_STR,
    CwpCbmcVisitor,
)

HEADER = "#include <stdbool.h>\n#include <assert.h>\n#include <stdlib.h>\n"


def _link(cwp: Cwp, src: CwpState, dest: CwpState, expr: str) -> CwpEdge:
    edge = CwpEdge(f"{src.name}_{dest.name}", f"{src.name}_{dest.name}")
    edge.expression = expr
    edge.source = src
    edge.dest = dest
    src.out_edges.append(edge)
    dest.in_edges.append(edge)
    cwp.edges[edge.id] = edge
    return edge


def _build_cwp(branch: bool = False) -> Cwp:
    """Start --x==1--> A --x==2--> End (and optionally A --x==3--> B)."""
    cwp = Cwp()
    names = ["Start", "A", "End"] + (["B"] if branch else [])
    for n in names:
        cwp.states[n] = CwpState(n, n)
    s, a, e = cwp.states["Start"], cwp.states["A"], cwp.states["End"]
    cwp.start_state = s
    cwp.end_states = [e]
    _link(cwp, s, a, "x == 1")
    _link(cwp, a, e, "x == 2")
    if branch:
        _link(cwp, a, cwp.states["B"], "x == 3")
    return cwp


def _generate(cwp: Cwp) -> CwpCbmcVisitor:
    visitor = CwpCbmcVisitor()
    cwp.accept(visitor)
    return visitor


def _program(visitor: CwpCbmcVisitor, main_body: str) -> str:
    return (
        f"{HEADER}int x;\n{visitor}\nint main(void) {{\n{main_body}\n return 0;\n}}\n"
    )


def _write(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "prog.c"
    path.write_text(source)
    return path


def _gcc(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gcc", "-Wall", "-Werror", "-o", str(path.with_suffix("")), str(path)],
        capture_output=True,
        text=True,
    )


def _cbmc(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["cbmc", str(path), "--unwind", "5"], capture_output=True, text=True
    )


class TestStructure:
    def test_start_state_is_true_others_false(self) -> None:
        out = str(_generate(_build_cwp()))
        assert START_STR in out and END_STR in out
        assert "bool Start = true;" in out
        assert "bool A = false;" in out
        assert "bool End = false;" in out

    def test_only_non_start_states_are_summed(self) -> None:
        v = _generate(_build_cwp())
        assert v.list_of_cwp_states == ["A", "End"]
        assert "(int)A + (int)End;" in str(v.build_XOR_block())

    def test_prime_and_mapping_for_intermediate_state(self) -> None:
        out = str(_generate(_build_cwp()))
        assert "bool A_prime = ((x == 1)) && !((x == 2));" in out
        assert "A = ((x == 1)) && !((x == 2));" in out

    def test_end_state_has_no_out_edges(self) -> None:
        out = str(_generate(_build_cwp()))
        assert "bool End_prime = ((x == 2)) && !(false);" in out

    def test_branching_state_ors_out_edges(self) -> None:
        out = str(_generate(_build_cwp(branch=True)))
        assert "!((x == 2) || (x == 3))" in out
        assert "|| (A && B_prime)" in out

    def test_edges_and_stationary_paths(self) -> None:
        v = _generate(_build_cwp())
        paths = str(v.proper_path_block)
        assert "|| (Start && A_prime)" in paths
        assert "|| (A && End_prime)" in paths
        assert "|| (A && A_prime)" in paths
        assert "|| (End && End_prime)" in paths
        assert "Start_prime" not in str(v)  # start state cannot be re-entered

    def test_reassignment(self) -> None:
        v = _generate(_build_cwp())
        text = str(v.var_reassignment)
        assert "Start = false;" in text
        assert "A = A_prime;" in text
        assert "End = End_prime;" in text

    def test_assertions_present(self) -> None:
        out = str(_generate(_build_cwp()))
        assert "Not a valid CWP transition" in out
        assert "sumOfActiveStates == 1" in out

    def test_empty_expression_is_true(self) -> None:
        cwp = Cwp()
        s, a = CwpState("S", "S"), CwpState("A", "A")
        cwp.states = {"S": s, "A": a}
        cwp.start_state = s
        _link(cwp, s, a, "")
        assert "bool A_prime = (true) && !(false);" in str(_generate(cwp))

    def test_state_visited_once(self) -> None:
        cwp = _build_cwp()
        # a loop back to A from End, marked leaf like the real graph does
        edge = _link(cwp, cwp.states["End"], cwp.states["A"], "x == 9")
        edge.is_leaf = True
        v = _generate(cwp)
        assert v.list_of_cwp_states == ["A", "End"]
        assert str(v).count("bool A = false;") == 1


class TestCompiles:
    @pytest.mark.parametrize("branch", [False, True])
    def test_gcc_compiles(self, tmp_path: Path, branch: bool) -> None:
        v = _generate(_build_cwp(branch))
        path = _write(tmp_path, _program(v, "calculateState();\nupdateState();"))
        result = _gcc(path)
        assert result.returncode == 0, result.stderr

    def test_valid_run_executes(self, tmp_path: Path) -> None:
        v = _generate(_build_cwp())
        body = "x = 1; calculateState(); updateState();\nassert(A);\n"
        body += "x = 2; calculateState(); updateState();\nassert(End);"
        path = _write(tmp_path, _program(v, body))
        assert _gcc(path).returncode == 0
        assert subprocess.run([str(path.with_suffix(""))]).returncode == 0


class TestCbmc:
    def test_valid_walk_verifies(self, tmp_path: Path) -> None:
        v = _generate(_build_cwp())
        body = "x = 1; updateState();\nassert(A && !Start);\n"
        body += "x = 2; updateState();\nassert(End && !A);\n"
        body += "updateState();  // staying in the end state is allowed\n"
        result = _cbmc(_write(tmp_path, _program(v, body)))
        assert result.returncode == 0, result.stdout
        assert "VERIFICATION SUCCESSFUL" in result.stdout

    def test_invalid_transition_is_caught(self, tmp_path: Path) -> None:
        v = _generate(_build_cwp())
        body = "x = 5; updateState();"  # no edge expression holds
        result = _cbmc(_write(tmp_path, _program(v, body)))
        assert result.returncode != 0
        assert "VERIFICATION FAILED" in result.stdout
        assert "Not a valid CWP transition" in result.stdout

    def test_two_active_states_is_caught(self, tmp_path: Path) -> None:
        # Overlapping guards out of A: x == 5 enables both End and B.
        cwp = _build_cwp(branch=True)
        cwp.edges["A_End"].expression = "x > 1"
        cwp.edges["A_B"].expression = "x > 2"
        v = _generate(cwp)
        body = "x = 1; updateState();\nx = 5; updateState();"
        result = _cbmc(_write(tmp_path, _program(v, body)))
        assert "VERIFICATION FAILED" in result.stdout
        assert "In more than one or no state" in result.stdout


class TestFeelEdges:
    @staticmethod
    def _feel_cwp(expr: str) -> Cwp:
        cwp = _build_cwp()
        cwp.states["Start"].out_edges[0].expression = parse_expression(expr).unwrap()
        return cwp

    def test_feel_edge_is_evaluated_once_per_function(self) -> None:
        v = _generate(self._feel_cwp("x = 1 or x = 5"))
        assert v.errors == []
        out = str(v)
        assert out.count("bool edge0_value = ((x == 1) || (x == 5));") == 2
        assert "bool A_prime = (edge0_value) && !((x == 2));" in out
        assert "A = (edge0_value) && !((x == 2));" in out

    def test_choose_is_hoisted_and_shared(self) -> None:
        v = _generate(self._feel_cwp("choose [true, false]"))
        out = str(v.prime_vars)
        assert out.count("unsigned int edge0_choose_0 = nondet_uint();") == 1
        assert "bool edge0_value = (edge0_choose_0 == 0 ? true : false);" in out

    def test_unsupported_feel_is_an_error(self) -> None:
        v = _generate(self._feel_cwp("x > 1.5"))
        assert isinstance(v.result().failure(), FeelCbmcUnsupportedError)
        assert "#error" in str(v)

    def test_plain_string_edges_are_unchanged(self) -> None:
        v = _generate(_build_cwp())
        assert v.result() == Success(str(v))

    @pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc not installed")
    def test_feel_cwp_in_cbmc(self, tmp_path: Path) -> None:
        v = _generate(self._feel_cwp("x = 1"))
        src = _program(v, "x = 1;\ncalculateState();\nupdateState();\nassert(A);")
        src = src.replace("int x;", "unsigned int nondet_uint(void);\nint x;")
        run = _cbmc(_write(tmp_path, src))
        assert "VERIFICATION SUCCESSFUL" in run.stdout, run.stdout
