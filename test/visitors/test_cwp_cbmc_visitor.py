# type: ignore
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState
from bpmncwpverify.core.state import State
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    CALCULATE_STATE_FUNC,
    END_STR,
    START_STR,
    UPDATE_STATE_FUNC,
    CwpCbmcVisitor,
)

FACE2FACE = Path(__file__).parent.parent / "resources" / "face2face"


def _edge(cwp: Cwp, name: str, src: CwpState | None, dest: CwpState, expr: str):
    edge = CwpEdge(name, name)
    edge.expression = expr
    edge.set_dest(dest)
    dest.in_edges.append(edge)
    if src is not None:
        edge.set_source(src)
        src.out_edges.append(edge)
    cwp.edges[name] = edge
    return edge


def _make_cwp() -> Cwp:
    """Start -> A -> (B | C), B -> End; A has two outgoing edges, End two incoming."""
    cwp = Cwp()
    for n in ("Start", "A", "B", "C", "End"):
        cwp.states[n] = CwpState(n, n)
    s, a, b, c, e = (cwp.states[n] for n in ("Start", "A", "B", "C", "End"))
    _edge(cwp, "e0", None, s, "x == 0")
    _edge(cwp, "e1", s, a, "x == 1")
    _edge(cwp, "e2", a, b, "x == 2")
    _edge(cwp, "e3", a, c, "x == 3")
    _edge(cwp, "e4", b, e, "x == 4")
    _edge(cwp, "e5", c, e, "x == 4")
    cwp.start_state = s
    s.init_state = True
    cwp.end_states = [e]
    return cwp


def _generate(cwp: Cwp) -> str:
    visitor = CwpCbmcVisitor()
    cwp.accept(visitor)
    return str(visitor)


def _run_cbmc(tmp_path: Path, program: str) -> subprocess.CompletedProcess:
    src = tmp_path / "main.c"
    src.write_text(program)
    return subprocess.run(
        ["cbmc", str(src)], capture_output=True, text=True, timeout=120
    )


def _program(cwp_c: str, main_body: str, decls: str = "int x;") -> str:
    return f"{decls}\n{cwp_c}\nint main(void) {{\n{main_body}\n}}\n"


class TestCwpCbmcVisitor:
    def test_visit_cwp_writes_header(self):
        visitor = CwpCbmcVisitor()
        assert visitor.visit_cwp(Cwp())
        assert str(visitor).startswith(START_STR)

    def test_end_visit_cwp_writes_footer_and_functions(self):
        visitor = CwpCbmcVisitor()
        visitor.end_visit_cwp(Cwp())
        out = str(visitor)
        assert END_STR in out
        assert f"void {CALCULATE_STATE_FUNC}(void)" in out
        assert f"void {UPDATE_STATE_FUNC}(void)" in out

    def test_visit_state_and_edge_continue(self):
        visitor = CwpCbmcVisitor()
        state = CwpState("s", "S")
        assert visitor.visit_state(state)
        assert visitor.visit_edge(CwpEdge("e", "e"))
        assert "#define CWP_STATE_S 0" in str(visitor)

    def test_start_state_with_in_edge(self):
        out = _generate(_make_cwp())
        assert "#define CWP_STATE_Start 0" in out
        assert "_Bool cwp_active_Start = ((x == 0)) && !((x == 1));" in out

    def test_state_with_several_out_edges(self):
        out = _generate(_make_cwp())
        assert "_Bool cwp_prime_A = ((x == 1)) && !((x == 2) || (x == 3));" in out
        assert (
            "(cwp_state == CWP_STATE_A && (cwp_prime_B || cwp_prime_C || cwp_prime_A))"
            in out
        )

    def test_state_with_several_in_edges(self):
        out = _generate(_make_cwp())
        assert "_Bool cwp_prime_End = ((x == 4) && (x == 4)) && !(0);" in out

    def test_state_without_in_edges(self):
        cwp = Cwp()
        s = CwpState("s", "S")
        d = CwpState("d", "D")
        cwp.states = {"s": s, "d": d}
        _edge(cwp, "e", s, d, "x == 1")
        cwp.start_state = s
        out = _generate(cwp)
        assert "_Bool cwp_active_S = (1) && !((x == 1));" in out

    def test_state_reached_twice_is_declared_once(self):
        out = _generate(_make_cwp())
        assert out.count("_Bool cwp_prime_End =") == 1
        assert out.count("#define CWP_STATE_End ") == 1

    def test_stationary_move_allowed(self):
        out = _generate(_make_cwp())
        assert "(cwp_state == CWP_STATE_End && (cwp_prime_End))" in out

    def test_asserts_present(self):
        out = _generate(_make_cwp())
        assert '"In more that one or no state"' in out
        assert '"Not a valid CWP transition"' in out

    def test_compiles_and_verifies(self, tmp_path):
        out = _generate(_make_cwp())
        body = f'x = 0;\n{CALCULATE_STATE_FUNC}();\n__CPROVER_assert(cwp_state == CWP_STATE_Start, "start");\nx = 1;\n{UPDATE_STATE_FUNC}();\n__CPROVER_assert(cwp_state == CWP_STATE_A, "a");\nx = 2;\n{UPDATE_STATE_FUNC}();\n__CPROVER_assert(cwp_state == CWP_STATE_B, "b");\nx = 4;\n{UPDATE_STATE_FUNC}();\n{UPDATE_STATE_FUNC}();\n__CPROVER_assert(cwp_state == CWP_STATE_End, "end");\nreturn 0;'
        result = _run_cbmc(tmp_path, _program(out, body))
        assert result.returncode == 0, result.stdout
        assert "VERIFICATION SUCCESSFUL" in result.stdout

    def test_invalid_edge_is_caught(self, tmp_path):
        out = _generate(_make_cwp())
        # Start -> B is not an edge
        body = f"x = 0;\n{CALCULATE_STATE_FUNC}();\nx = 2;\n{UPDATE_STATE_FUNC}();\nreturn 0;"
        result = _run_cbmc(tmp_path, _program(out, body))
        assert "VERIFICATION FAILED" in result.stdout
        assert "Not a valid CWP transition: FAILURE" in result.stdout

    def test_not_exactly_one_state_is_caught(self, tmp_path):
        out = _generate(_make_cwp())
        # x == 7 matches no state's in-edges
        body = f"x = 0;\n{CALCULATE_STATE_FUNC}();\nx = 7;\n{UPDATE_STATE_FUNC}();\nreturn 0;"
        result = _run_cbmc(tmp_path, _program(out, body))
        assert "In more that one or no state: FAILURE" in result.stdout

    def test_face2face_verifies(self, tmp_path):
        state = State.from_str((FACE2FACE / "state.txt").read_text()).unwrap()
        cwp = CwpXmlParser.from_xml(
            ET.fromstring((FACE2FACE / "cwp.xml").read_text()), state
        ).unwrap()
        out = _generate(cwp)
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
        body = f"""
{CALCULATE_STATE_FUNC}();
__CPROVER_assert(cwp_state == CWP_STATE_Init_Purchase_Pending, "init");
paymentOffered = paymentAmount;
{UPDATE_STATE_FUNC}();
__CPROVER_assert(cwp_state == CWP_STATE_Negotiations, "neg");
terms = agreed;
{UPDATE_STATE_FUNC}();
__CPROVER_assert(cwp_state == CWP_STATE_Purchase_Agreed, "agreed");
return 0;"""
        result = _run_cbmc(tmp_path, _program(out, body, decls))
        assert "VERIFICATION SUCCESSFUL" in result.stdout, result.stdout
