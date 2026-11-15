# type: ignore
import shutil
import subprocess

import pytest

from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    END_STR,
    START_STR,
    CwpCbmcVisitor,
)


def _build_cwp() -> Cwp:
    """
    Start -(x == 0)-> A -(x == 1)-> B -(x == 3)-> D
                      A -(x == 2)-> C -(x == 3)-> D
    Start has no in edges, D has two (and no out edges).
    """
    cwp = Cwp()
    for name in ["Start", "A", "B", "C", "D"]:
        cwp.states[name] = CwpState(name, name)
    for i, (src, dest, expr) in enumerate(
        [
            ("Start", "A", "x == 0"),
            ("A", "B", "x == 1"),
            ("A", "C", "x == 2"),
            ("B", "D", "x == 3"),
            ("C", "D", "x == 3"),
        ]
    ):
        edge = CwpEdge(f"e{i}", f"e{i}")
        edge.expression = expr
        edge.set_source(cwp.states[src])
        edge.set_dest(cwp.states[dest])
        cwp.states[src].out_edges.append(edge)
        cwp.states[dest].in_edges.append(edge)
        cwp.edges[edge.id] = edge
    cwp.start_state = cwp.states["Start"]
    return cwp


def _generate(cwp: Cwp) -> str:
    visitor = CwpCbmcVisitor()
    cwp.accept(visitor)
    return repr(visitor)


@pytest.fixture
def cwp_c() -> str:
    return _generate(_build_cwp())


def _run(tmp_path, cwp_c: str, steps: list[int]) -> subprocess.CompletedProcess:
    """Compile the CWP C into a small program that drives x through `steps`."""
    body = "\n".join(f"x = {s}; cwp_update_state(); print_state();" for s in steps)
    program = f"""
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
int x = {steps[0] if steps else 0};
{cwp_c}
static void print_state(void) {{ printf("%d\\n", {"cwp_state"}); }}
int main(void) {{
    cwp_calculate_state();
    print_state();
    {body}
    return 0;
}}
"""
    src = tmp_path / "prog.c"
    src.write_text(program)
    exe = tmp_path / "prog"
    subprocess.run(["gcc", "-Wall", "-Werror", str(src), "-o", str(exe)], check=True)
    return subprocess.run([str(exe)], capture_output=True, text=True)


def _states(result) -> list[int]:
    return [int(line) for line in result.stdout.split()]


# Enum order follows the visit order: Start, A, B, C, D (D is reached via B first).
START, A, B, C, D = 0, 1, 2, 4, 3


class TestStructure:
    def test_declarations(self, cwp_c):
        assert cwp_c.startswith(START_STR)
        assert END_STR in cwp_c
        assert "int cwp_state = CWP_STATE_Start;" in cwp_c
        for name in ["Start", "A", "B", "C", "D"]:
            assert f"CWP_STATE_{name}" in cwp_c

    def test_start_state_has_no_next_variable(self, cwp_c):
        assert "cwp_next_Start" not in cwp_c

    def test_state_mapping(self, cwp_c):
        assert "bool cwp_next_A = ((x == 0)) && !((x == 1) || (x == 2));" in cwp_c
        # no out edges -> !(false); several in edges -> all must hold
        assert "bool cwp_next_D = ((x == 3) && (x == 3)) && !(false);" in cwp_c

    def test_assertions(self, cwp_c):
        assert "assert(cwp_active_count == 1);" in cwp_c
        assert "assert(cwp_valid_move);" in cwp_c

    def test_valid_moves_cover_edges_and_staying(self, cwp_c):
        assert "(cwp_state == CWP_STATE_Start && cwp_next_A)" in cwp_c
        assert "(cwp_state == CWP_STATE_A && cwp_next_B)" in cwp_c
        assert "(cwp_state == CWP_STATE_A && cwp_next_C)" in cwp_c
        assert "(cwp_state == CWP_STATE_B && cwp_next_D)" in cwp_c
        assert "(cwp_state == CWP_STATE_C && cwp_next_D)" in cwp_c
        for name in ["A", "B", "C", "D"]:
            assert f"(cwp_state == CWP_STATE_{name} && cwp_next_{name})" in cwp_c
        assert "(cwp_state == CWP_STATE_Start && cwp_next_Start)" not in cwp_c

    def test_state_visited_twice_is_declared_once(self, cwp_c):
        assert cwp_c.count("CWP_STATE_D,") + cwp_c.count("CWP_STATE_D }") == 1
        assert cwp_c.count("bool cwp_next_D =") == 2  # calculate + update

    def test_no_loops(self, cwp_c):
        assert "for (" not in cwp_c and "while" not in cwp_c

    def test_visit_helpers(self):
        visitor = CwpCbmcVisitor()
        assert visitor.visit_edge(CwpEdge("e", "e")) is True
        visitor.end_visit_edge(CwpEdge("e", "e"))
        visitor.end_visit_state(CwpState("s", "s"))


@pytest.mark.skipif(shutil.which("gcc") is None, reason="gcc not available")
class TestCompiledProgram:
    def test_initial_state_from_variables(self, tmp_path, cwp_c):
        # x == 0 puts the CWP in A
        result = _run(tmp_path, cwp_c, [0])
        assert result.returncode == 0
        assert _states(result)[0] == A

    def test_path_through_first_branch(self, tmp_path, cwp_c):
        result = _run(tmp_path, cwp_c, [0, 1, 3])
        assert result.returncode == 0
        assert _states(result) == [A, A, B, D]

    def test_path_through_second_branch(self, tmp_path, cwp_c):
        result = _run(tmp_path, cwp_c, [0, 2, 3])
        assert result.returncode == 0
        assert _states(result) == [A, A, C, D]

    def test_staying_is_allowed(self, tmp_path, cwp_c):
        result = _run(tmp_path, cwp_c, [0, 0, 0])
        assert result.returncode == 0
        assert _states(result) == [A, A, A, A]

    def test_invalid_edge_is_caught(self, tmp_path, cwp_c):
        # A -> D has no edge
        result = _run(tmp_path, cwp_c, [0, 3])
        assert result.returncode != 0
        assert "cwp_valid_move" in result.stderr

    def test_no_matching_state_is_caught(self, tmp_path, cwp_c):
        result = _run(tmp_path, cwp_c, [0, 7])
        assert result.returncode != 0
        assert "cwp_active_count" in result.stderr

    def test_two_matching_states_are_caught(self, tmp_path):
        cwp = _build_cwp()
        # Make B and C both hold when x == 5
        cwp.edges["e1"].expression = "x == 1 || x == 5"
        cwp.edges["e2"].expression = "x == 2 || x == 5"
        result = _run(tmp_path, _generate(cwp), [0, 5])
        assert result.returncode != 0
