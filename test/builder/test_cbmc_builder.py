# type: ignore
import subprocess
from xml.etree import ElementTree as ET

import pytest
from returns.result import Failure, Success

from bpmncwpverify.builder.cbmc_bound import calculate_cbmc_bound
from bpmncwpverify.builder.cbmc_builder import CbmcBuilder, CbmcOutputs
from bpmncwpverify.core.accessmethods import bpmnmethods
from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.bpmn import (
    Bpmn,
    EndEvent,
    ExclusiveGatewayNode,
    Process,
    SequenceFlow,
    StartEvent,
    Task,
)
from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState
from bpmncwpverify.core.error import (
    BpmnCbmcUnsupportedElementError,
    CbmcBuildError,
    NotInitializedError,
)
from bpmncwpverify.core.state import State

FACE2FACE = "test/resources/face2face/"
STATE = """enum Color { red green }
const limit: byte = 7
var x: byte = 0 {0 1 2}
var c: Color = red
var flag: bool = false
"""


def make_state(text=STATE):
    return State.from_str(text).unwrap()


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


def simple_cwp():
    # A -> B when x == 1. A also has an init edge, so it is entered at x == 0.
    cwp = make_cwp(["A", "B"], [("A", "B", "x == 1")], "A")
    init = CwpEdge("init", "Init")
    init.expression = "x == 0"
    init.set_dest(cwp.states["A"])
    cwp.states["A"].in_edges.append(init)
    return cwp


def link(src, dst, expr=""):
    flow = SequenceFlow(f"{src.id}_{dst.id}", "")
    flow.expression = expr
    flow.source_node = src
    flow.target_node = dst
    src.add_out_flow(flow)
    dst.add_in_flow(flow)


def linear_bpmn(behavior="x = 1"):
    s, t, e = (
        StartEvent("S", "S", "", ""),
        Task("T", "T", behavior),
        EndEvent("E", "E", "", ""),
    )
    link(s, t)
    link(t, e)
    process = Process("P", "P")
    for node in (s, t, e):
        process[node.id] = node
    bpmn = Bpmn()
    bpmn.processes["P"] = process
    return bpmn


def build(bpmn, cwp=None, state=None):
    return (
        CbmcBuilder()
        .with_state(state or make_state())
        .with_cwp(cwp or simple_cwp())
        .with_bpmn(bpmn)
        .build()
    )


def gcc(tmp_path, source):
    src = tmp_path / "p.c"
    src.write_text(source)
    return subprocess.run(
        [
            "gcc",
            "-Wall",
            "-Werror",
            "-Wno-unused-function",
            "-Wno-unused-variable",
            "-D__CPROVER_assume(x)=((void)(x))",
            "-c",
            str(src),
            "-o",
            "/dev/null",
        ],
        capture_output=True,
        text=True,
    )


def run_cbmc(tmp_path, outputs):
    src = tmp_path / "p.c"
    src.write_text(outputs.c_code)
    return subprocess.run(
        ["cbmc", str(src), "--unwind", str(outputs.unwind), "--unwinding-assertions"],
        capture_output=True,
        text=True,
    ).stdout


def face2face(bpmn_file):
    def element(path):
        return ET.fromstring(open(FACE2FACE + path).read())

    state = make_state(open(FACE2FACE + "state.txt").read())
    cwp = CwpXmlParser.from_xml(element("cwp.xml"), state).unwrap()
    bpmn = bpmnmethods.from_xml(element(bpmn_file), state).unwrap()
    return state, cwp, bpmn


class TestCbmcBuilder:
    def test_build_returns_c_and_bound(self):
        bpmn = linear_bpmn()
        result = build(bpmn)
        assert isinstance(result, Success)
        outputs = result.unwrap()
        assert isinstance(outputs, CbmcOutputs)
        assert outputs.bound == calculate_cbmc_bound(bpmn) == 3
        assert outputs.unwind == 4
        assert "pass < 3u" in outputs.c_code

    def test_declares_state(self):
        code = build(linear_bpmn()).unwrap().c_code
        assert "#define limit 7" in code
        assert "enum Color {green, red};" in code
        assert "static unsigned char x = 0;" in code
        assert "static enum Color c = red;" in code
        assert "static bool flag = false;" in code

    def test_includes_visitor_output(self):
        code = build(linear_bpmn()).unwrap().c_code
        assert "static void cwp_update(void)" in code
        assert "static void bpmn_step(void)" in code
        assert "static bool bpmn_all_done(void)" in code

    def test_main_sets_cwp_state_before_loop(self):
        code = build(linear_bpmn()).unwrap().c_code
        main = code[code.index("int main(void)") :]
        assert main.index("cwp_init();") < main.index("for (")
        assert main.index("bpmn_init();") < main.index("for (")
        assert "bpmn_step();" in main.split("for (")[1]
        assert "bpmn_all_done()" in main.split("for (")[1]

    def test_main_has_no_loop_over_transitions(self):
        main = build(linear_bpmn()).unwrap().c_code.split("int main(void)")[1]
        assert main.count("for (") + main.count("while") == 1

    def test_compiles(self, tmp_path):
        result = gcc(tmp_path, build(linear_bpmn()).unwrap().c_code)
        assert result.returncode == 0, result.stderr

    def test_compiles_with_exclusive_gateway(self, tmp_path):
        s, g, a, b = (
            StartEvent("S", "S", "", ""),
            ExclusiveGatewayNode("G", "G"),
            EndEvent("A", "A", "", ""),
            EndEvent("B", "B", "", ""),
        )
        link(s, g)
        link(g, a, "x == 0")
        link(g, b, "x != 0")
        process = Process("P", "P")
        for node in (s, g, a, b):
            process[node.id] = node
        bpmn = Bpmn()
        bpmn.processes["P"] = process
        result = gcc(tmp_path, build(bpmn).unwrap().c_code)
        assert result.returncode == 0, result.stderr

    def test_cbmc_verifies_valid_workflow(self, tmp_path):
        out = run_cbmc(tmp_path, build(linear_bpmn("x = 1")).unwrap())
        assert "VERIFICATION SUCCESSFUL" in out

    def test_cbmc_finds_invalid_cwp_move(self, tmp_path):
        # x == 2 satisfies no CWP edge, so the CWP is in no state
        out = run_cbmc(tmp_path, build(linear_bpmn("x = 2")).unwrap())
        assert "VERIFICATION FAILED" in out

    def test_cbmc_checks_initial_cwp_state(self, tmp_path):
        # With the initial x = 0, init puts the CWP in A. A task that changes
        # nothing but runs update must be a stay, which needs the initial state
        out = run_cbmc(tmp_path, build(linear_bpmn("x = 0")).unwrap())
        assert "VERIFICATION SUCCESSFUL" in out

    @pytest.mark.parametrize("bpmn_file", ["workflow.bpmn", "face2face_open.bpmn"])
    def test_face2face_builds_and_compiles(self, tmp_path, bpmn_file):
        state, cwp, bpmn = face2face(bpmn_file)
        outputs = build(bpmn, cwp, state).unwrap()
        assert outputs.bound == calculate_cbmc_bound(bpmn) > 0
        result = gcc(tmp_path, outputs.c_code)
        assert result.returncode == 0, result.stderr

    def test_missing_inputs(self):
        for builder in (
            CbmcBuilder(),
            CbmcBuilder().with_cwp(simple_cwp()).with_bpmn(linear_bpmn()),
            CbmcBuilder().with_state(make_state()).with_bpmn(linear_bpmn()),
            CbmcBuilder().with_state(make_state()).with_cwp(simple_cwp()),
        ):
            result = builder.build()
            assert isinstance(result, Failure)
            assert isinstance(result.failure(), NotInitializedError)

    def test_missing_input_names(self):
        error = CbmcBuilder().build().failure()
        assert error.var_name == "CbmcBuilder.state"

    def test_empty_cwp(self):
        result = build(linear_bpmn(), cwp=Cwp())
        assert isinstance(result.failure(), CbmcBuildError)

    def test_bpmn_without_start_event(self):
        result = build(Bpmn())
        assert isinstance(result.failure(), CbmcBuildError)

    def test_unsupported_behavior_is_an_error(self):
        result = build(linear_bpmn("do :: x = 1 od"))
        assert isinstance(result.failure(), BpmnCbmcUnsupportedElementError)

    def test_setters_return_builder(self):
        builder = CbmcBuilder()
        assert builder.with_state(make_state()) is builder
        assert builder.with_cwp(simple_cwp()) is builder
        assert builder.with_bpmn(linear_bpmn()) is builder


def test_given_face2face_when_built_then_covers_only_in_reachability_block():
    state = make_state(open(FACE2FACE + "state.txt").read())
    cwp = CwpXmlParser.from_xml(
        ET.parse(FACE2FACE + "cwp.xml").getroot(), state
    ).unwrap()
    bpmn = bpmnmethods.from_xml(
        ET.parse(FACE2FACE + "workflow.bpmn").getroot(), state
    ).unwrap()

    c_code = (
        CbmcBuilder()
        .with_state(state)
        .with_cwp(cwp)
        .with_bpmn(bpmn)
        .build()
        .unwrap()
        .c_code
    )

    block = c_code[c_code.index("#ifdef REACHABILITY") : c_code.index("int main")]
    assert c_code.count("__CPROVER_cover(") == block.count("__CPROVER_cover(") == 7
    assert "CWP_Start)" not in block
    assert "CWP_Negotiations" in block
