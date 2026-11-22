# type: ignore
import subprocess
from xml.etree import ElementTree as ET

import pytest

from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState
from bpmncwpverify.core.state import State
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    END_STR,
    START_STR,
    CwpCbmcVisitor,
)

FACE2FACE = "test/resources/face2face/"


def make_cwp(states, edges, start):
    """states: names; edges: (source, dest, expression); start: state name."""
    cwp = Cwp()
    for name in states:
        cwp.states[name] = CwpState(name, name)
    for i, (src, dst, expr) in enumerate(edges):
        edge = CwpEdge(f"e{i}", f"Edge{i}")
        edge.expression = expr
        edge.set_source(cwp.states[src])
        edge.set_dest(cwp.states[dst])
        cwp.states[src].out_edges.append(edge)
        cwp.states[dst].in_edges.append(edge)
        cwp.edges[edge.id] = edge
    cwp.start_state = cwp.states[start]
    return cwp


def generate(cwp):
    visitor = CwpCbmcVisitor()
    cwp.accept(visitor)
    return str(visitor)


# A -> B -> C, with a self-contained init edge into A. x drives the CWP.
def simple_cwp():
    cwp = make_cwp(
        ["A", "B", "C"],
        [("A", "B", "x == 1"), ("B", "C", "x == 2")],
        "A",
    )
    init = CwpEdge("init", "Init")
    init.expression = "x == 0"
    init.set_dest(cwp.states["A"])
    cwp.states["A"].in_edges.append(init)
    return cwp


def program(cwp, body):
    return f"int x = 0;\n{generate(cwp)}\nint main(void) {{\n{body}\nreturn 0;\n}}\n"


def gcc(tmp_path, source):
    src = tmp_path / "p.c"
    src.write_text(source)
    return subprocess.run(
        [
            "gcc",
            "-Wall",
            "-Werror",
            "-Wno-unused-function",
            str(src),
            "-o",
            str(tmp_path / "p"),
        ],
        capture_output=True,
        text=True,
    )


def cbmc(tmp_path, source):
    src = tmp_path / "p.c"
    src.write_text(source)
    return subprocess.run(["cbmc", str(src)], capture_output=True, text=True).stdout


class TestCwpCbmcVisitor:
    def test_markers(self):
        out = generate(simple_cwp())
        assert out.startswith(START_STR)
        assert out.rstrip().endswith(END_STR)

    def test_state_constants_and_variable(self):
        out = generate(simple_cwp())
        for name in "ABC":
            assert f"CWP_{name}," in out
        assert "static unsigned cwp_state;" in out

    def test_state_guard_in_and_out_edges(self):
        out = generate(simple_cwp())
        assert "bool B_prime = ((x == 1)) && !((x == 2));" in out
        assert "bool A_prime = ((x == 0)) && !((x == 1));" in out

    def test_end_state_has_no_out_edges(self):
        out = generate(simple_cwp())
        assert "bool C_prime = ((x == 2)) && !(false);" in out

    def test_multiple_edges_are_parenthesized(self):
        cwp = make_cwp(
            ["A", "B", "C"],
            [
                ("A", "B", "x == 1 || x == 2"),
                ("A", "C", "x == 3"),
                ("B", "C", "x == 4"),
            ],
            "A",
        )
        out = generate(cwp)
        assert "bool B_prime = ((x == 1 || x == 2)) && !((x == 4));" in out
        assert "bool C_prime = ((x == 3) && (x == 4)) && !(false);" in out

    def test_exactly_one_state_assertion(self):
        out = generate(simple_cwp())
        assert "assert((A_prime + B_prime + C_prime) == 1);" in out

    def test_valid_edge_assertions(self):
        out = generate(simple_cwp())
        assert "case CWP_A:" in out
        assert "assert(next == CWP_A || next == CWP_B);" in out
        assert "assert(next == CWP_B || next == CWP_C);" in out
        assert "assert(next == CWP_C);" in out

    def test_start_state_without_in_edges(self):
        cwp = make_cwp(["S", "E"], [("S", "E", "x == 1")], "S")
        out = generate(cwp)
        assert "cwp_state = CWP_S;" in out
        assert "bool S_prime" not in out
        assert "assert(next == CWP_E);" in out

    def test_empty_expression_is_true(self):
        cwp = make_cwp(["S", "E"], [("S", "E", "")], "S")
        assert "bool E_prime = (true) && !(false);" in generate(cwp)

    def test_diamond_state_declared_once(self):
        cwp = make_cwp(
            ["S", "L", "R", "E"],
            [
                ("S", "L", "x == 1"),
                ("S", "R", "x == 2"),
                ("L", "E", "x == 3"),
                ("R", "E", "x == 3"),
            ],
            "S",
        )
        out = generate(cwp)
        assert out.count("CWP_E,") == 1
        assert out.count("case CWP_E:") == 1

    def test_compiles(self, tmp_path):
        body = "cwp_init(); x = 1; cwp_update(); x = 2; cwp_update();"
        result = gcc(tmp_path, program(simple_cwp(), body))
        assert result.returncode == 0, result.stderr
        assert subprocess.run([str(tmp_path / "p")]).returncode == 0

    def test_compiles_start_state_without_in_edges(self, tmp_path):
        cwp = make_cwp(["S", "E"], [("S", "E", "x == 1")], "S")
        result = gcc(tmp_path, program(cwp, "cwp_init(); x = 1; cwp_update();"))
        assert result.returncode == 0, result.stderr

    def test_cbmc_valid_walk_verifies(self, tmp_path):
        body = "cwp_init(); x = 1; cwp_update(); x = 2; cwp_update();"
        assert "VERIFICATION SUCCESSFUL" in cbmc(tmp_path, program(simple_cwp(), body))

    def test_cbmc_stay_is_valid(self, tmp_path):
        body = "cwp_init(); cwp_update(); cwp_update();"
        assert "VERIFICATION SUCCESSFUL" in cbmc(tmp_path, program(simple_cwp(), body))

    def test_cbmc_skipped_edge_fails(self, tmp_path):
        # x == 2 jumps A -> C without going through B
        body = "cwp_init(); x = 2; cwp_update();"
        assert "VERIFICATION FAILED" in cbmc(tmp_path, program(simple_cwp(), body))

    def test_cbmc_no_state_fails(self, tmp_path):
        body = "cwp_init(); x = 7; cwp_update();"
        assert "VERIFICATION FAILED" in cbmc(tmp_path, program(simple_cwp(), body))

    def test_cbmc_overlapping_states_fails(self, tmp_path):
        cwp = make_cwp(
            ["A", "B", "C"],
            [("A", "B", "x >= 1"), ("A", "C", "x >= 1")],
            "A",
        )
        init = CwpEdge("init", "Init")
        init.expression = "x == 0"
        init.set_dest(cwp.states["A"])
        cwp.states["A"].in_edges.append(init)
        body = "cwp_init(); x = 1; cwp_update();"
        assert "VERIFICATION FAILED" in cbmc(tmp_path, program(cwp, body))

    @pytest.fixture
    def face2face_cwp(self):
        with open(FACE2FACE + "state.txt") as f:
            state = State.from_str(f.read()).unwrap()
        root = ET.parse(FACE2FACE + "cwp.xml").getroot()
        return CwpXmlParser.from_xml(root, state).unwrap()

    def test_face2face_compiles_and_verifies(self, face2face_cwp, tmp_path):
        out = generate(face2face_cwp)
        for state in face2face_cwp.states.values():
            assert f"CWP_{state.name}," in out
        decls = """
enum TermsType { agreed, failed, noRetry, pending };
enum OwnerType { buyerName, sellerName };
#define paymentAmount 253
#define noRetryPayment 254
#define pendingPayment 255
enum TermsType terms = pending;
enum OwnerType backpackOwner = sellerName;
enum OwnerType paymentOwner = buyerName;
unsigned char paymentOffered = pendingPayment;
"""
        body = (
            "cwp_init(); terms = failed; cwp_update(); terms = agreed;"
            " paymentOffered = paymentAmount; cwp_update(); paymentOwner = sellerName; backpackOwner = buyerName; cwp_update();"
        )
        src = f"{decls}\n{out}\nint main(void) {{ {body} return 0; }}\n"
        assert gcc(tmp_path, src).returncode == 0
        assert "VERIFICATION SUCCESSFUL" in cbmc(tmp_path, src)
