# type: ignore
import shutil
import subprocess
from xml.etree.ElementTree import parse

import pytest

from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState
from bpmncwpverify.core.state import State
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    INIT_FUNC,
    STATE_VAR,
    UPDATE_FUNC,
    CwpCbmcVisitor,
)

HAS_GCC = shutil.which("gcc") is not None
HAS_CBMC = shutil.which("cbmc") is not None


def _edge(cwp: Cwp, src: CwpState, dest: CwpState, expr: str) -> CwpEdge:
    edge = CwpEdge(f"e{len(cwp.edges)}", f"e{len(cwp.edges)}")
    edge.expression = expr
    edge.set_source(src)
    edge.set_dest(dest)
    src.out_edges.append(edge)
    dest.in_edges.append(edge)
    cwp.edges[edge.id] = edge
    return edge


def _make_cwp() -> Cwp:
    """
    init --(x == 0)--> Start --(x == 1)--> Mid --(x == 2)--> End
    Start has the init edge as its in edge, and End has no out edges.
    """
    cwp = Cwp()
    start, mid, end = (CwpState(n, n) for n in ("Start", "Mid", "End"))
    for s in (start, mid, end):
        cwp.states[s.id] = s
    cwp.start_state = start
    cwp.end_states = [end]
    init = CwpEdge("init", "init")
    init.expression = "x == 0"
    init.set_dest(start)
    start.in_edges.append(init)
    _edge(cwp, start, mid, "x == 1")
    _edge(cwp, mid, end, "x == 2")
    cwp.edges["init"] = init
    return cwp


def _generate(cwp: Cwp) -> str:
    visitor = CwpCbmcVisitor()
    cwp.accept(visitor)
    return str(visitor)


def _program(cwp: Cwp, main_body: str) -> str:
    return (
        "#include <assert.h>\n"
        "int x = 0;\n"
        f"{_generate(cwp)}\n"
        f"int main(void) {{\n{main_body}\nreturn 0;\n}}\n"
    )


def _gcc(tmp_path, source: str, run: bool) -> subprocess.CompletedProcess:
    src = tmp_path / "prog.c"
    src.write_text(source)
    exe = tmp_path / "prog"
    subprocess.run(
        ["gcc", "-Wall", "-Werror", "-o", str(exe), str(src)],
        check=True,
        capture_output=True,
    )
    return subprocess.run([str(exe)], capture_output=True)


def _cbmc(tmp_path, source: str) -> subprocess.CompletedProcess:
    src = tmp_path / "prog.c"
    src.write_text(source)
    return subprocess.run(["cbmc", str(src)], capture_output=True, text=True)


class TestGeneratedText:
    def test_every_state_gets_a_constant(self):
        c = _generate(_make_cwp())
        for name in ("Start", "Mid", "End"):
            assert f"CWP_STATE_{name}," in c
        assert f"static int {STATE_VAR}" in c

    def test_guards_follow_in_and_out_edges(self):
        c = _generate(_make_cwp())
        # state with an init edge and an out edge
        assert "cwp_guard_Start = ((x == 0)) && !((x == 1));" in c
        # in edge and out edge
        assert "cwp_guard_Mid = ((x == 1)) && !((x == 2));" in c
        # state without out edges
        assert "cwp_guard_End = ((x == 2)) && !(0);" in c

    def test_state_without_in_edges_cannot_stay(self):
        cwp = _make_cwp()
        cwp.states["Start"].in_edges.clear()
        c = _generate(cwp)
        assert "cwp_guard_Start = (1) && !((x == 1));" in c
        assert (
            "case CWP_STATE_Start: cwp_valid = cwp_next == CWP_STATE_Mid; break;" in c
        )

    def test_valid_moves_are_out_edges_or_stay(self):
        c = _generate(_make_cwp())
        assert (
            "case CWP_STATE_Start: cwp_valid = cwp_next == CWP_STATE_Mid"
            " || cwp_next == CWP_STATE_Start; break;"
        ) in c
        assert "case CWP_STATE_End: cwp_valid = cwp_next == CWP_STATE_End; break;" in c

    def test_empty_expression_is_true(self):
        cwp = _make_cwp()
        cwp.states["Mid"].out_edges[0].expression = ""
        assert "cwp_guard_Mid = ((x == 1)) && !(1);" in _generate(cwp)

    def test_asserts_present(self):
        c = _generate(_make_cwp())
        assert "In more than one or no CWP state" in c
        assert "Not a valid CWP transition" in c

    def test_states_visited_once_with_cycle(self):
        cwp = _make_cwp()
        mid = cwp.states["Mid"]
        back = _edge(cwp, mid, cwp.states["Start"], "x == 0")
        back.is_leaf = True
        c = _generate(cwp)
        assert c.count("CWP_STATE_Mid,") == 1
        assert c.count("int cwp_guard_Mid") == 2  # init and update


@pytest.mark.skipif(not HAS_GCC, reason="no gcc")
class TestCompiles:
    def test_runs_through_the_edges(self, tmp_path):
        body = (
            f"{INIT_FUNC}();\n"
            f"assert({STATE_VAR} == CWP_STATE_Start);\n"
            f"{UPDATE_FUNC}();\n"
            f"assert({STATE_VAR} == CWP_STATE_Start);\n"
            f"x = 1; {UPDATE_FUNC}();\n"
            f"assert({STATE_VAR} == CWP_STATE_Mid);\n"
            f"x = 2; {UPDATE_FUNC}();\n"
            f"assert({STATE_VAR} == CWP_STATE_End);\n"
        )
        assert _gcc(tmp_path, _program(_make_cwp(), body), True).returncode == 0

    def test_invalid_move_aborts(self, tmp_path):
        # Start cannot go straight to End
        body = f"{INIT_FUNC}(); x = 2; {UPDATE_FUNC}();"
        result = _gcc(tmp_path, _program(_make_cwp(), body), True)
        assert result.returncode != 0
        assert b"Not a valid CWP transition" in result.stderr

    def test_no_active_state_aborts(self, tmp_path):
        body = f"{INIT_FUNC}(); x = 7; {UPDATE_FUNC}();"
        result = _gcc(tmp_path, _program(_make_cwp(), body), True)
        assert result.returncode != 0
        assert b"no CWP state" in result.stderr


@pytest.mark.skipif(not HAS_CBMC, reason="no cbmc")
class TestCbmc:
    def test_valid_workflow_verifies(self, tmp_path):
        body = (
            f"{INIT_FUNC}();\n"
            "int steps[3] = {0, 1, 2};\n"
            "for (int i = 0; i < 3; i++) {\n"
            f"  x = steps[i]; {UPDATE_FUNC}();\n"
            "}\n"
            f"assert({STATE_VAR} == CWP_STATE_End);\n"
        )
        result = _cbmc(tmp_path, _program(_make_cwp(), body) + "\n")
        assert "VERIFICATION SUCCESSFUL" in result.stdout, result.stdout

    def test_invalid_move_fails(self, tmp_path):
        body = f"{INIT_FUNC}(); x = 2; {UPDATE_FUNC}();"
        result = _cbmc(tmp_path, _program(_make_cwp(), body))
        assert "VERIFICATION FAILED" in result.stdout


class TestFace2Face:
    @pytest.fixture
    def cwp_and_state(self):
        d = "./test/resources/face2face/"
        with open(d + "state.txt") as f:
            state = State.from_str(f.read()).unwrap()
        cwp = CwpXmlParser.from_xml(parse(d + "cwp.xml").getroot(), state).unwrap()
        return cwp, state

    def test_generates_all_states(self, cwp_and_state):
        cwp, _ = cwp_and_state
        c = _generate(cwp)
        for s in cwp.states.values():
            assert f"CWP_STATE_{s.name}," in c

    @pytest.mark.skipif(not (HAS_GCC and HAS_CBMC), reason="no gcc or cbmc")
    def test_init_selects_one_state(self, cwp_and_state, tmp_path):
        cwp, state = cwp_and_state
        decls = (
            "#include <assert.h>\n"
            "enum all { INIT, other };\n"
            "enum TermsType { agreed, failed, pending, noRetry };\n"
            "enum OwnerType { buyerName, sellerName };\n"
            "const unsigned char paymentAmount = 253;\n"
            "const unsigned char belowPaymentAmount = 252;\n"
            "const unsigned char noRetryPayment = 254;\n"
            "const unsigned char pendingPayment = 255;\n"
            "enum TermsType terms = pending;\n"
            "enum OwnerType backpackOwner = sellerName;\n"
            "enum OwnerType paymentOwner = buyerName;\n"
            "unsigned char paymentOffered = 255;\n"
        )
        source = (
            f"{decls}{_generate(cwp)}\n"
            "int main(void) {\n"
            f"  {INIT_FUNC}();\n"
            f"  assert({STATE_VAR} == CWP_STATE_Init_Purchase_Pending);\n"
            "  terms = failed; paymentOffered = belowPaymentAmount;\n"
            f"  {UPDATE_FUNC}();\n"
            f"  assert({STATE_VAR} == CWP_STATE_Negotiations);\n"
            "  terms = agreed; paymentOffered = paymentAmount;\n"
            f"  {UPDATE_FUNC}();\n"
            f"  assert({STATE_VAR} == CWP_STATE_Purchase_Agreed);\n"
            "  return 0;\n}\n"
        )
        result = _cbmc(tmp_path, source)
        assert "VERIFICATION SUCCESSFUL" in result.stdout, result.stdout
        assert _gcc(tmp_path, source, True).returncode == 0
