# type: ignore
import subprocess

import pytest

from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    END_STR,
    START_STR,
    CwpCbmcVisitor,
)


def _link(cwp: Cwp, source: CwpState, dest: CwpState, expr: str) -> None:
    edge = CwpEdge(f"{source.id}_{dest.id}", f"{source.id}_{dest.id}")
    edge.expression = expr
    edge.set_source(source)
    edge.set_dest(dest)
    source.out_edges.append(edge)
    dest.in_edges.append(edge)
    cwp.edges[edge.id] = edge


@pytest.fixture
def cwp() -> Cwp:
    """
    Start -(x == 1)-> Mid -(x == 2)-> Done
                       \\-(x == 3)-> Failed
    Start has the init edge (x == 0) coming into it.
    """
    cwp = Cwp()
    for name in ["Start", "Mid", "Done", "Failed"]:
        cwp.states[name] = CwpState(name, name)
    s = cwp.states
    init = CwpEdge("Init_Edge", "Init_Edge")
    init.expression = "x == 0"
    init.set_dest(s["Start"])
    s["Start"].in_edges.append(init)
    _link(cwp, s["Start"], s["Mid"], "x == 1")
    _link(cwp, s["Mid"], s["Done"], "x == 2")
    _link(cwp, s["Mid"], s["Failed"], "x == 3")
    cwp.start_state = s["Start"]
    cwp.end_states = [s["Done"], s["Failed"]]
    return cwp


def _generate(cwp: Cwp) -> CwpCbmcVisitor:
    visitor = CwpCbmcVisitor()
    cwp.accept(visitor)
    return visitor


def _run_cbmc(tmp_path, cwp: Cwp, main_body: str) -> subprocess.CompletedProcess:
    program = f"int nondet_int(void);\nint x = 0;\n{_generate(cwp)}\nint main() {{\n{main_body}\n}}\n"
    source = tmp_path / "cwp.c"
    source.write_text(program)
    return subprocess.run(
        ["cbmc", str(source)], capture_output=True, text=True, check=False
    )


def test_state_constants_and_variable(cwp):
    out = str(_generate(cwp))
    assert out.startswith(START_STR)
    assert END_STR in out
    for i, name in enumerate(["Start", "Mid", "Done", "Failed"]):
        assert f"#define CWP_STATE_{name} {i}\n" in out
    assert "unsigned char cwp_state = CWP_STATE_NONE;" in out


def test_state_guards(cwp):
    out = str(_generate(cwp))
    # in edges hold and no out edge holds
    assert "#define CWP_IN_Start (((x == 0)) && !((x == 1)))" in out
    assert "#define CWP_IN_Mid (((x == 1)) && !((x == 2) || (x == 3)))" in out
    # end states have no out edges
    assert "#define CWP_IN_Done (((x == 2)) && !(0))" in out
    assert "#define CWP_IN_Failed (((x == 3)) && !(0))" in out


def test_edges_become_valid_transitions(cwp):
    out = str(_generate(cwp))
    assert "cwp_state == CWP_STATE_Start && cwp_next_state == CWP_STATE_Mid" in out
    assert "cwp_state == CWP_STATE_Mid && cwp_next_state == CWP_STATE_Done" in out
    assert "cwp_state == CWP_STATE_Mid && cwp_next_state == CWP_STATE_Failed" in out
    assert "cwp_state == CWP_STATE_Done && cwp_next_state" not in out
    assert "cwp_next_state == cwp_state" in out  # staying put is allowed


def test_assertions_present(cwp):
    out = str(_generate(cwp))
    assert (
        '__CPROVER_assert(active_states == 1, "In more than one or no state");' in out
    )
    assert '"Not a valid CWP transition"' in out


def test_no_loops_in_generated_code(cwp):
    out = str(_generate(cwp))
    assert "for (" not in out
    assert "while" not in out


def test_state_without_in_edges():
    cwp = Cwp()
    a, b = CwpState("a", "A"), CwpState("b", "B")
    cwp.states = {"a": a, "b": b}
    _link(cwp, a, b, "x == 1")
    cwp.start_state = a
    out = str(_generate(cwp))
    assert "CWP_IN_A" not in out
    assert "cwp_state = CWP_STATE_A;" in out
    assert "#define CWP_IN_B (((x == 1)) && !(0))" in out


def test_visit_returns_true(cwp):
    visitor = CwpCbmcVisitor()
    assert visitor.visit_cwp(cwp)
    assert visitor.visit_state(cwp.states["Start"])
    assert visitor.visit_edge(cwp.states["Start"].out_edges[0])


def test_compiles_and_calculates_initial_state(tmp_path, cwp):
    result = _run_cbmc(
        tmp_path,
        cwp,
        f'{"cwp_calculate_state();"}\n__CPROVER_assert(cwp_state == CWP_STATE_Start, "init");\nreturn 0;',
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "VERIFICATION SUCCESSFUL" in result.stdout


def test_valid_path_verifies(tmp_path, cwp):
    result = _run_cbmc(
        tmp_path,
        cwp,
        """
        cwp_calculate_state();
        x = 1; cwp_update_state();
        x = 3; cwp_update_state();
        __CPROVER_assert(cwp_state == CWP_STATE_Failed, "end");
        return 0;
        """,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "VERIFICATION SUCCESSFUL" in result.stdout


def test_update_without_change_is_valid(tmp_path, cwp):
    result = _run_cbmc(
        tmp_path,
        cwp,
        "cwp_calculate_state(); cwp_update_state(); cwp_update_state(); return 0;",
    )
    assert "VERIFICATION SUCCESSFUL" in result.stdout


def test_invalid_edge_fails(tmp_path, cwp):
    result = _run_cbmc(
        tmp_path,
        cwp,
        "cwp_calculate_state(); x = 2; cwp_update_state(); return 0;",
    )
    assert "VERIFICATION FAILED" in result.stdout
    assert "Not a valid CWP transition" in result.stdout


def test_no_active_state_fails(tmp_path, cwp):
    result = _run_cbmc(
        tmp_path,
        cwp,
        "cwp_calculate_state(); x = 7; cwp_update_state(); return 0;",
    )
    assert "VERIFICATION FAILED" in result.stdout
    assert "In more than one or no state" in result.stdout


def test_nondeterministic_variable_catches_bad_move(tmp_path, cwp):
    result = _run_cbmc(
        tmp_path,
        cwp,
        "cwp_calculate_state(); x = nondet_int(); cwp_update_state(); return 0;",
    )
    assert "VERIFICATION FAILED" in result.stdout
