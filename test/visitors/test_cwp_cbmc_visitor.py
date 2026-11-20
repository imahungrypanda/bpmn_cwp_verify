import shutil
import subprocess
from pathlib import Path

import defusedxml.ElementTree as ET
import pytest

from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState
from bpmncwpverify.core.state import State
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    END_STR,
    START_STR,
    CwpCbmcVisitor,
)

RESOURCES = Path(__file__).parent.parent / "resources" / "face2face"


def _compiler():
    return shutil.which("gcc") or shutil.which("cc")


def _make_cwp() -> Cwp:
    """A -> B -> C, B -> A (cycle), C has no out edges."""
    cwp = Cwp()
    names = ["A", "B", "C"]
    for n in names:
        cwp.states[n] = CwpState(n, n)
    cwp.start_state = cwp.states["A"]

    def edge(src: str, dest: str, expr: str) -> None:
        e = CwpEdge(f"{src}{dest}", f"{src}{dest}")
        e.expression = expr
        e.set_source(cwp.states[src])
        e.set_dest(cwp.states[dest])
        cwp.states[src].out_edges.append(e)
        cwp.states[dest].in_edges.append(e)
        cwp.edges[e.id] = e

    edge("A", "B", "x == 1")
    edge("B", "C", "x == 2")
    edge("B", "A", "x == 0")
    # the back edge is a leaf so the traversal terminates
    cwp.edges["BA"].is_leaf = True
    return cwp


def _generate(cwp: Cwp) -> tuple[CwpCbmcVisitor, str]:
    visitor = CwpCbmcVisitor()
    cwp.accept(visitor)
    return visitor, str(visitor)


def _program(cwp_c: str, body: str) -> str:
    return f"#include <assert.h>\nint x;\n{cwp_c}\nint main(void) {{\n{body}\n return 0;\n}}\n"


def _compile_and_run(tmp_path: Path, source: str) -> int:
    cc = _compiler()
    if cc is None:
        pytest.skip("no C compiler")
    src = tmp_path / "prog.c"
    src.write_text(source)
    exe = tmp_path / "prog"
    subprocess.run(
        [cc, "-Wall", "-Werror", "-Wno-unused-function", str(src), "-o", str(exe)],
        check=True,
    )
    return subprocess.run([str(exe)], capture_output=True).returncode


class TestCwpCbmcVisitor:
    def test_visit_state_collects_unique(self):
        v = CwpCbmcVisitor()
        s = CwpState("a", "a")
        assert v.visit_state(s)
        assert not v.visit_state(CwpState("a2", "a"))
        assert v.states == [s]

    def test_visit_edge_records_source_and_dest(self):
        v = CwpCbmcVisitor()
        cwp = _make_cwp()
        assert v.visit_edge(cwp.edges["AB"])
        assert v.edges == [("A", "B")]

    def test_visit_edge_without_source(self):
        v = CwpCbmcVisitor()
        e = CwpEdge("e", "e")
        e.set_dest(CwpState("s", "s"))
        assert v.visit_edge(e)
        assert v.edges == []

    def test_output_structure(self):
        _, c = _generate(_make_cwp())
        assert c.startswith(START_STR)
        assert c.rstrip().endswith(END_STR)
        for name in ("A", "B", "C"):
            assert f"CWP_STATE_{name} = " in c
        assert "static int cwp_state;" in c
        assert "assert(sum_of_active_states == 1);" in c
        assert "assert(cwp_valid_edge[cwp_state][next_state]);" in c

    def test_state_guards(self):
        _, c = _generate(_make_cwp())
        # B: in edge A->B, out edges B->C and B->A
        assert "int cwp_active_B = ((x == 1)) && !((x == 2) || (x == 0));" in c
        # C has no out edges
        _, c = _generate(_make_cwp())
        assert "int cwp_active_C = ((x == 2)) && !(0);" in c

    def test_edge_table(self):
        v, c = _generate(_make_cwp())
        assert [s.name for s in v.states] == ["A", "B", "C"]
        # rows: A -> {A, B}, B -> {A, B, C}, C -> {C}
        assert "{1, 1, 0}," in c
        assert "{1, 1, 1}," in c
        assert "{0, 0, 1}," in c

    def test_empty_expression_is_true(self):
        cwp = _make_cwp()
        cwp.edges["AB"].expression = ""
        _, c = _generate(cwp)
        assert "int cwp_active_B = (1) && " in c

    def test_state_without_in_edges_is_initial(self):
        cwp = _make_cwp()
        cwp.states["A"].in_edges.clear()
        v, c = _generate(cwp)
        assert "int cwp_active_A = 0;" in c
        assert "cwp_state = CWP_STATE_A;" in c

    def test_init_calculates_state_when_all_have_in_edges(self):
        _, c = _generate(_make_cwp())
        assert "cwp_state = cwp_calculate_state();" in c

    def test_repr_is_output(self):
        v, c = _generate(_make_cwp())
        assert repr(v) == c


class TestGeneratedCompiles:
    def test_valid_moves_run(self, tmp_path):
        _, c = _generate(_make_cwp())
        body = """
        x = 0; cwp_init(); assert(cwp_state == CWP_STATE_A);
        x = 1; cwp_update(); assert(cwp_state == CWP_STATE_B);
        x = 0; cwp_update(); assert(cwp_state == CWP_STATE_A);
        x = 1; cwp_update(); assert(cwp_state == CWP_STATE_B);
        x = 2; cwp_update(); assert(cwp_state == CWP_STATE_C);
        cwp_update(); assert(cwp_state == CWP_STATE_C);
        """
        assert _compile_and_run(tmp_path, _program(c, body)) == 0

    def test_staying_in_state_is_allowed(self, tmp_path):
        _, c = _generate(_make_cwp())
        body = "x = 0; cwp_init(); cwp_update(); assert(cwp_state == CWP_STATE_A);"
        assert _compile_and_run(tmp_path, _program(c, body)) == 0

    def test_invalid_edge_asserts(self, tmp_path):
        _, c = _generate(_make_cwp())
        # A (x == 0) straight to C (x == 2) has no edge
        body = "x = 0; cwp_init(); x = 2; cwp_update();"
        assert _compile_and_run(tmp_path, _program(c, body)) != 0

    def test_no_active_state_asserts(self, tmp_path):
        _, c = _generate(_make_cwp())
        body = "x = 7; cwp_init();"
        assert _compile_and_run(tmp_path, _program(c, body)) != 0

    def test_initial_state_without_in_edges(self, tmp_path):
        cwp = _make_cwp()
        cwp.states["A"].in_edges.clear()
        _, c = _generate(cwp)
        body = "x = 99; cwp_init(); assert(cwp_state == CWP_STATE_A); x = 1; cwp_update(); assert(cwp_state == CWP_STATE_B);"
        assert _compile_and_run(tmp_path, _program(c, body)) == 0

    @pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc not installed")
    def test_cbmc_agrees(self, tmp_path):
        _, c = _generate(_make_cwp())
        # x can jump from 0 (A) straight to 2 (C), which is not an edge
        prog = _program(
            c,
            "x = 0; cwp_init(); int i; for (i = 0; i < 3; i++) { x = nondet_int() % 3; "
            "if (x < 0) x = 0; cwp_update(); }",
        ).replace("int x;", "int x;\nint nondet_int(void);")
        src = tmp_path / "prog.c"
        src.write_text(prog)
        r = subprocess.run(
            ["cbmc", str(src), "--unwind", "5"], capture_output=True, text=True
        )
        assert r.returncode != 0
        assert "VERIFICATION FAILED" in r.stdout


class TestFace2Face:
    @pytest.fixture
    def cwp(self):
        state = State.from_str((RESOURCES / "state.txt").read_text()).unwrap()
        root = ET.parse(str(RESOURCES / "cwp.xml")).getroot()
        return CwpXmlParser.from_xml(root, state).unwrap(), state

    def test_all_states_and_edges(self, cwp):
        cwp, _ = cwp
        visitor, c = _generate(cwp)
        assert len(visitor.states) == len(cwp.states) == 6
        assert len(visitor.edges) == 5
        for state in cwp.states.values():
            assert f"CWP_STATE_{state.name} = " in c

    def test_compiles_and_follows_the_workflow(self, cwp, tmp_path):
        cwp, _ = cwp
        _, c = _generate(cwp)
        decls = """
        enum { buyerName, sellerName, agreed, failed, noRetry, pending };
        int terms = pending, backpackOwner = sellerName, paymentOwner = buyerName;
        unsigned char paymentOffered = 255;
        #define paymentAmount 253
        #define noRetryPayment 254
        #define pendingPayment 255
        """
        src = f"#include <assert.h>\n{decls}\n{c}\nint main(void) {{\n"
        src += """
        // the initial values put the CWP in Init_Purchase_Pending, not Start
        cwp_init(); assert(cwp_state == CWP_STATE_Init_Purchase_Pending);
        terms = agreed; cwp_update(); assert(cwp_state == CWP_STATE_Negotiations);
        paymentOffered = paymentAmount; cwp_update();
        assert(cwp_state == CWP_STATE_Purchase_Agreed);
        paymentOwner = sellerName; backpackOwner = buyerName; cwp_update();
        assert(cwp_state == CWP_STATE_Ownerships_Switched);
        return 0;
        }
        """
        assert _compile_and_run(tmp_path, src) == 0

    def test_skipping_a_state_asserts(self, cwp, tmp_path):
        cwp, _ = cwp
        _, c = _generate(cwp)
        src = f"""#include <assert.h>
        enum {{ buyerName, sellerName, agreed, failed, noRetry, pending }};
        int terms = pending, backpackOwner = sellerName, paymentOwner = buyerName;
        unsigned char paymentOffered = 255;
        #define paymentAmount 253
        #define noRetryPayment 254
        #define pendingPayment 255
        {c}
        int main(void) {{
            cwp_init();
            terms = agreed; paymentOffered = paymentAmount; cwp_update();
            return 0;
        }}
        """
        assert _compile_and_run(tmp_path, src) != 0
