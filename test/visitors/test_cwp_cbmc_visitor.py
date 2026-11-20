import shutil
import subprocess
from pathlib import Path
from xml.etree.ElementTree import parse

import pytest

from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState
from bpmncwpverify.core.state import State
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    CALCULATE_FUNCTION,
    END_STR,
    START_STR,
    STATE_VAR,
    UPDATE_FUNCTION,
    CwpCbmcVisitor,
)

FACE2FACE = Path("test/resources/face2face")

needs_cbmc = pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc not found")


def _connect(cwp: Cwp, src: str, dest: str, expr: str) -> CwpEdge:
    edge = CwpEdge(f"{src}_{dest}", f"{src}_{dest}")
    edge.expression = expr
    s, d = cwp.states[src], cwp.states[dest]
    edge.set_source(s)
    edge.set_dest(d)
    s.out_edges.append(edge)
    d.in_edges.append(edge)
    cwp.edges[edge.id] = edge
    return edge


def _make_cwp(init_edge: bool, back_edge: bool = True) -> Cwp:
    """a -(x > 0)-> b -(x > 1)-> c, optionally with b -(x == 0)-> a closing a loop."""
    cwp = Cwp()
    for name in "abc":
        cwp.states[name] = CwpState(name, name)
    cwp.start_state = cwp.states["a"]
    _connect(cwp, "a", "b", "x > 0")
    _connect(cwp, "b", "c", "x > 1")
    if back_edge:
        _connect(cwp, "b", "a", "x == 0").is_leaf = True
    if init_edge:
        edge = CwpEdge("Init_Edge", "Init_Edge")
        edge.expression = "x == 0"
        edge.set_dest(cwp.start_state)
        cwp.start_state.in_edges.append(edge)
    cwp.end_states.append(cwp.states["c"])
    return cwp


def _generate(cwp: Cwp) -> CwpCbmcVisitor:
    visitor = CwpCbmcVisitor()
    cwp.accept(visitor)
    return visitor


def _check(tmp_path: Path, c_code: str) -> subprocess.CompletedProcess[str]:
    source = tmp_path / "prog.c"
    source.write_text(c_code)
    return subprocess.run(
        ["cbmc", str(source)], capture_output=True, text=True, timeout=120
    )


def _program(visitor: CwpCbmcVisitor, decls: str, body: str) -> str:
    return f"{decls}\n{visitor}\nint main(void) {{\n{body}\n}}\n"


class TestStructure:
    def test_visits_each_state_once(self):
        visitor = _generate(_make_cwp(init_edge=False, back_edge=False))
        assert [s.name for s in visitor.states] == ["a", "b", "c"]

    def test_declarations(self):
        text = str(_generate(_make_cwp(init_edge=False, back_edge=False)).declarations)
        assert text.startswith(START_STR)
        assert text.rstrip().endswith(END_STR)
        for name in ("CWP_a", "CWP_b", "CWP_c"):
            assert name in text
        assert f"enum CwpState {STATE_VAR} = CWP_a;" in text

    def test_start_state_without_in_edge_is_initial(self):
        visitor = _generate(_make_cwp(init_edge=False, back_edge=False))
        assert "int matches = 1;" in str(visitor.calculate_function)

    def test_start_state_with_init_edge_is_calculated(self):
        visitor = _generate(_make_cwp(init_edge=True))
        calc = str(visitor.calculate_function)
        assert "int matches = 0;" in calc
        assert "(x == 0)" in calc

    def test_update_has_case_per_state_and_edge(self):
        update = str(_generate(_make_cwp(init_edge=False)).update_function)
        for name in ("a", "b", "c"):
            assert f"case CWP_{name}:" in update
        assert "(x > 0)" in update and "(x > 1)" in update and "(x == 0)" in update
        assert "Not a valid CWP transition" in update
        assert "In no state" in update

    def test_state_without_in_edges_cannot_stay(self):
        update = str(
            _generate(_make_cwp(init_edge=False, back_edge=False)).update_function
        )
        a_case = update.split("case CWP_a:")[1].split("case CWP_b:")[0]
        assert "enabled0" in a_case and "enabled1" not in a_case  # only the edge to b
        b_case = update.split("case CWP_b:")[1].split("case CWP_c:")[0]
        assert "enabled1" in b_case and "enabled2" not in b_case  # edge plus staying

    def test_end_state_may_only_stay(self):
        update = str(
            _generate(_make_cwp(init_edge=False, back_edge=False)).update_function
        )
        c_case = update.split("case CWP_c:")[1].split("default:")[0]
        assert "enabled0" in c_case and "enabled1" not in c_case

    def test_no_loops_in_generated_code(self):
        text = str(_generate(_make_cwp(init_edge=True)))
        assert "for (" not in text and "while" not in text

    def test_repr_orders_parts(self):
        visitor = _generate(_make_cwp(init_edge=True))
        text = str(visitor)
        assert (
            text.index("enum CwpState")
            < text.index(f"void {CALCULATE_FUNCTION}")
            < text.index(f"void {UPDATE_FUNCTION}")
        )


@needs_cbmc
class TestCompiles:
    DECLS = "int x = 0;"

    def test_compiles_and_valid_move_passes(self, tmp_path):
        visitor = _generate(_make_cwp(init_edge=True))
        body = f"""
            {CALCULATE_FUNCTION}();
            __CPROVER_assert({STATE_VAR} == CWP_a, "starts in a");
            x = 1;
            {UPDATE_FUNCTION}();
            __CPROVER_assert({STATE_VAR} == CWP_b, "moved to b");
            x = 2;
            {UPDATE_FUNCTION}();
            __CPROVER_assert({STATE_VAR} == CWP_c, "moved to c");
            return 0;
        """
        result = _check(tmp_path, _program(visitor, self.DECLS, body))
        assert result.returncode == 0, result.stdout
        assert "VERIFICATION SUCCESSFUL" in result.stdout

    def test_staying_is_allowed(self, tmp_path):
        visitor = _generate(_make_cwp(init_edge=True))
        body = f"""
            {CALCULATE_FUNCTION}();
            x = 1;
            {UPDATE_FUNCTION}();
            {UPDATE_FUNCTION}();
            return 0;
        """
        result = _check(tmp_path, _program(visitor, self.DECLS, body))
        assert "VERIFICATION SUCCESSFUL" in result.stdout, result.stdout

    def test_invalid_edge_is_caught(self, tmp_path):
        # From a with x = 2, b's out edge holds, so b is not a valid target.
        visitor = _generate(_make_cwp(init_edge=True))
        body = f"""
            {CALCULATE_FUNCTION}();
            x = 2;
            {UPDATE_FUNCTION}();
            return 0;
        """
        result = _check(tmp_path, _program(visitor, self.DECLS, body))
        assert result.returncode != 0
        assert "Not a valid CWP transition" in result.stdout

    def test_every_nondeterministic_path_is_valid(self, tmp_path):
        visitor = _generate(_make_cwp(init_edge=True))
        body = f"""
            {CALCULATE_FUNCTION}();
            x = 1;
            {UPDATE_FUNCTION}();
            __CPROVER_assert({STATE_VAR} == CWP_b, "must be b");
            return 0;
        """
        result = _check(tmp_path, _program(visitor, self.DECLS, body))
        assert "VERIFICATION SUCCESSFUL" in result.stdout, result.stdout

    def test_invalid_initial_state_is_caught(self, tmp_path):
        visitor = _generate(_make_cwp(init_edge=True))
        body = f"x = -1; {CALCULATE_FUNCTION}(); return 0;"
        result = _check(tmp_path, _program(visitor, self.DECLS, body))
        assert result.returncode != 0
        assert "exactly one state" in result.stdout


FACE2FACE_DECLS = """
#include <stdint.h>
enum TermsType { agreed, failed, pending, noRetry };
enum OwnerType { buyerName, sellerName };
#define paymentAmount 253
#define belowPaymentAmount 252
#define noRetryPayment 254
#define pendingPayment 255
enum TermsType terms = pending;
enum OwnerType backpackOwner = sellerName;
enum OwnerType paymentOwner = buyerName;
uint8_t paymentOffered = pendingPayment;
"""


@needs_cbmc
def test_face2face_cwp_compiles(tmp_path):
    state = State.from_str((FACE2FACE / "state.txt").read_text())
    cwp_result = CwpXmlParser.from_xml(
        parse(FACE2FACE / "cwp.xml").getroot(), state.unwrap()
    )
    cwp = cwp_result.unwrap()
    visitor = _generate(cwp)
    assert len(visitor.states) == len(cwp.states)
    assert f"enum CwpState {STATE_VAR} = " in str(visitor.declarations)
    body = f"{CALCULATE_FUNCTION}(); {UPDATE_FUNCTION}(); return 0;"
    result = _check(tmp_path, _program(visitor, FACE2FACE_DECLS, body))
    assert "VERIFICATION SUCCESSFUL" in result.stdout, result.stdout
