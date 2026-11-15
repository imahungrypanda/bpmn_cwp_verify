# type: ignore
import shutil
import subprocess
from xml.etree.ElementTree import parse

import pytest
from returns.pipeline import is_successful

from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState
from bpmncwpverify.core.state import State
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    END_STR,
    START_STR,
    CwpCbmcVisitor,
)

FACE2FACE = "./test/resources/face2face/"
C_TYPES = {"byte": "unsigned char", "bool": "_Bool", "bit": "_Bool", "int": "int"}


def build_cwp(states, edges, start):
    """states: names; edges: (source, dest, expression) in order."""
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
    # Mark edges that close a cycle the way CwpConnectivityVisitor does
    from bpmncwpverify.visitors.cwp_connectivity_visitor import CwpConnectivityVisitor

    cwp.accept(CwpConnectivityVisitor())
    return cwp


def generate(cwp):
    visitor = CwpCbmcVisitor()
    cwp.accept(visitor)
    return str(visitor)


def abc_cwp(with_init_edge=True):
    """A -> B -> C (end), plus a back edge B -> A, over one int variable x."""
    cwp = build_cwp(
        ["A", "B", "C"],
        [("A", "B", "x == 1"), ("B", "C", "x == 2"), ("B", "A", "x == 0")],
        "A",
    )
    if with_init_edge:
        init = CwpEdge("Init_Edge", "EdgeInit")
        init.expression = "x == 0"
        init.set_dest(cwp.states["A"])
        cwp.states["A"].in_edges.append(init)
    return cwp


def run_cbmc(tmp_path, source):
    c_file = tmp_path / "prog.c"
    c_file.write_text(source)
    return subprocess.run(
        ["cbmc", str(c_file)], capture_output=True, text=True, timeout=120
    )


def program(cwp_c, body, init_x=0):
    return (
        "#include <assert.h>\n"
        f"int x = {init_x};\n"
        f"{cwp_c}\n"
        f"int main(void) {{\n cwp_calculate_state();\n{body}\n return 0;\n}}\n"
    )


class TestStructure:
    def test_visit_cwp_writes_header(self):
        visitor = CwpCbmcVisitor()
        assert visitor.visit_cwp(Cwp())
        assert str(visitor) == START_STR + "\n"

    def test_declarations_cover_each_state(self):
        c = generate(abc_cwp())
        assert START_STR in c and END_STR in c
        for name in "ABC":
            assert f"CWP_STATE_{name}," in c
        assert "static enum cwp_state_id cwp_state = CWP_STATE_A;" in c

    def test_mapping_for_start_middle_and_end_states(self):
        c = generate(abc_cwp())
        # Start state: init edge and the back edge come in, edge to B goes out
        assert "_Bool A_prime = ((x == 0) && (x == 0)) && !((x == 1));" in c
        # Middle state: one way in, two out
        assert "_Bool B_prime = ((x == 1)) && !((x == 2) || (x == 0));" in c
        # End state: nothing goes out
        assert "_Bool C_prime = ((x == 2)) && !(0);" in c

    def test_state_without_in_edges_is_always_reachable_by_values(self):
        cwp = build_cwp(["S", "T"], [("S", "T", "x == 1")], "S")
        c = generate(cwp)
        assert "_Bool S_prime = (1) && !((x == 1));" in c

    def test_empty_edge_expression_is_true(self):
        cwp = build_cwp(["S", "T"], [("S", "T", "")], "S")
        assert "_Bool T_prime = (1) && !(0);" in generate(cwp)

    def test_valid_moves_follow_out_edges_and_stay_put(self):
        c = generate(abc_cwp())
        assert "cwp_state == CWP_STATE_A ? (A_prime || B_prime)" in c
        assert "cwp_state == CWP_STATE_B ? (B_prime || C_prime || A_prime)" in c
        assert "cwp_state == CWP_STATE_C ? (C_prime)" in c

    def test_one_active_state_assertion(self):
        c = generate(abc_cwp())
        assert "int cwp_active_states = A_prime + B_prime + C_prime;" in c
        assert c.count("cwp_active_states == 1") == 2  # update and calculate

    def test_single_state_cwp(self):
        cwp = Cwp()
        only = CwpState("only", "only")
        cwp.states["only"] = only
        cwp.start_state = only
        c = generate(cwp)
        assert "CWP_STATE_only," in c
        assert "int cwp_active_states = only_prime;" in c


class TestCompiles:
    def test_generated_c_compiles_with_cbmc(self, tmp_path):
        result = run_cbmc(tmp_path, program(generate(abc_cwp()), ""))
        assert result.returncode == 0, result.stdout + result.stderr
        assert "VERIFICATION SUCCESSFUL" in result.stdout

    @pytest.mark.skipif(shutil.which("gcc") is None, reason="gcc not installed")
    def test_generated_c_compiles_with_gcc(self, tmp_path):
        c_file = tmp_path / "prog.c"
        c_file.write_text(program(generate(abc_cwp()), " cwp_update_state();"))
        result = subprocess.run(
            ["gcc", "-Wall", "-Werror", "-c", str(c_file), "-o", str(tmp_path / "o")],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize(
        "body",
        [
            "x = 1; cwp_update_state(); assert(cwp_state == CWP_STATE_B);",
            "x = 1; cwp_update_state(); x = 2; cwp_update_state();"
            " assert(cwp_state == CWP_STATE_C);",
            "x = 1; cwp_update_state(); x = 0; cwp_update_state();"
            " assert(cwp_state == CWP_STATE_A);",
            "cwp_update_state(); assert(cwp_state == CWP_STATE_A);",  # stay put
        ],
    )
    def test_valid_moves_verify(self, tmp_path, body):
        result = run_cbmc(tmp_path, program(generate(abc_cwp()), body))
        assert "VERIFICATION SUCCESSFUL" in result.stdout, result.stdout

    @pytest.mark.parametrize(
        "body, message",
        [
            # A -> C is not an edge
            ("x = 2; cwp_update_state();", "Not a valid CWP transition"),
            # No state matches
            ("x = 5; cwp_update_state();", "In more than one or no state"),
            # Nothing leaves C, so it cannot go back to A
            (
                "x = 1; cwp_update_state(); x = 2; cwp_update_state();"
                " x = 0; cwp_update_state();",
                "Not a valid CWP transition",
            ),
        ],
    )
    def test_invalid_moves_fail(self, tmp_path, body, message):
        result = run_cbmc(tmp_path, program(generate(abc_cwp()), body))
        assert "VERIFICATION FAILED" in result.stdout, result.stdout
        assert message in result.stdout

    def test_initial_values_in_no_state_fail(self, tmp_path):
        result = run_cbmc(tmp_path, program(generate(abc_cwp()), "", init_x=7))
        assert "VERIFICATION FAILED" in result.stdout
        assert "Initial values are in more than one or no state" in result.stdout

    def test_initial_state_follows_initial_values(self, tmp_path):
        cwp = abc_cwp(with_init_edge=False)
        # Without an init edge A only needs to not leave: x != 1
        body = "assert(cwp_state == CWP_STATE_B);"
        result = run_cbmc(tmp_path, program(generate(cwp), body, init_x=1))
        assert "VERIFICATION SUCCESSFUL" in result.stdout, result.stdout


class TestFace2Face:
    @staticmethod
    def c_declarations(state):
        out = []
        for const in state.consts:
            out.append(f"#define {const.id} {const.init.value}")
        for enum in state.enums:
            out.append(
                f"enum {enum.id} {{ {', '.join(v.value for v in enum.values)} }};"
            )
        for var in state.vars:
            type_ = C_TYPES.get(var.type_, f"enum {var.type_}")
            out.append(f"{type_} {var.id} = {var.init.value};")
        return "\n".join(out)

    def test_face2face_cwp_compiles_and_starts_in_initial_state(self, tmp_path):
        with open(FACE2FACE + "state.txt") as f:
            state = State.from_str(f.read())
        assert is_successful(state)
        state = state.unwrap()
        cwp = CwpXmlParser.from_xml(parse(FACE2FACE + "cwp.xml").getroot(), state)
        assert is_successful(cwp)
        cwp = cwp.unwrap()

        c = generate(cwp)
        for cwp_state in cwp.states.values():
            assert f"CWP_STATE_{cwp_state.name}," in c

        source = (
            "#include <assert.h>\n"
            f"{self.c_declarations(state)}\n{c}\n"
            "int main(void) {\n"
            " cwp_calculate_state();\n"
            # The start edge's condition already holds, so the CWP begins one on
            " assert(cwp_state == CWP_STATE_Init_Purchase_Pending);\n"
            " cwp_update_state();\n"
            " return 0;\n}\n"
        )
        result = run_cbmc(tmp_path, source)
        assert "VERIFICATION SUCCESSFUL" in result.stdout, result.stdout + source
