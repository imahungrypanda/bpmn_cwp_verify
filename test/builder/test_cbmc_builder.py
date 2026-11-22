# type: ignore
import subprocess
from xml.etree.ElementTree import fromstring

import pytest
from returns.result import Failure

from bpmncwpverify.builder.cbmc_bound import compute_cbmc_bound
from bpmncwpverify.builder.cbmc_builder import CbmcBuilder
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

FACE2FACE = "./test/resources/face2face/"

STATE_TXT = """
enum Color { red green }
const limit: byte = 3
var x: byte = 0 {0 1 2 3}
var c: Color = red
var flag: bool = false
"""


class Graph:
    def __init__(self):
        self.process = Process("p", "p")
        self.nodes = {}

    def _add(self, node):
        self.nodes[node.id] = node
        self.process[node.id] = node
        return self

    def start(self, *ids):
        for id in ids:
            self._add(StartEvent(id, id, "", ""))
        return self

    def end(self, *ids):
        for id in ids:
            self._add(EndEvent(id, id, "", ""))
        return self

    def task(self, *ids):
        for id in ids:
            self._add(Task(id, id, ""))
        return self

    def xor(self, *ids):
        for id in ids:
            self._add(ExclusiveGatewayNode(id, id))
        return self

    def flow(self, *ids, expression=""):
        for source, target in zip(ids, ids[1:]):
            flow = SequenceFlow(f"{source}_{target}", "")
            flow.expression = expression
            flow.source_node = self.nodes[source]
            flow.target_node = self.nodes[target]
            self.nodes[source].add_out_flow(flow)
            self.nodes[target].add_in_flow(flow)
            self.process[flow.id] = flow
        return self

    def bpmn(self):
        bpmn = Bpmn()
        bpmn.processes[self.process.id] = self.process
        return bpmn


def _link(cwp, src, dest, expr):
    edge = CwpEdge(f"e{len(cwp.edges)}", f"e{len(cwp.edges)}")
    edge.expression = expr
    edge.source = src
    edge.dest = dest
    src.out_edges.append(edge)
    dest.in_edges.append(edge)
    cwp.edges[edge.id] = edge


def _cwp():
    cwp = Cwp()
    for n in ("init", "done"):
        cwp.states[n] = CwpState(n, n)
    init_edge = CwpEdge("Init_Edge", "init_edge")
    init_edge.expression = "x == 0"
    init_edge.dest = cwp.states["init"]
    cwp.states["init"].in_edges.append(init_edge)
    cwp.start_state = cwp.states["init"]
    cwp.end_states = [cwp.states["done"]]
    _link(cwp, cwp.states["init"], cwp.states["done"], "x == 1")
    return cwp


def _state():
    return State.from_str(STATE_TXT).unwrap()


def _build(graph):
    return (
        CbmcBuilder()
        .with_state(_state())
        .with_cwp(_cwp())
        .with_bpmn(graph.bpmn())
        .build_program()
    )


def _cbmc(tmp_path, program):
    src = tmp_path / "prog.c"
    src.write_text(program.c_code)
    return subprocess.run(
        ["cbmc", str(src), "--unwind", str(program.unwind)],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _straight():
    return Graph().start("s").task("t").end("e").flow("s", "t", "e")


def _xor():
    return (
        Graph()
        .start("s")
        .xor("g")
        .task("a", "b")
        .end("e")
        .flow("s", "g")
        .flow("g", "a", "e", expression="x == 0")
        .flow("g", "b", "e", expression="x != 0")
    )


@pytest.mark.parametrize("graph", [_straight, _xor], ids=["straight", "xor"])
def test_builds_c_that_verifies(tmp_path, graph):
    program = _build(graph()).unwrap()
    result = _cbmc(tmp_path, program)
    assert result.returncode == 0, result.stdout
    assert "VERIFICATION SUCCESSFUL" in result.stdout


def test_bound_matches_compute_cbmc_bound():
    g = _xor()
    program = _build(g).unwrap()
    assert program.bound == compute_cbmc_bound(g.bpmn())
    assert program.unwind == program.bound + 1
    assert f"{program.bound}u" in program.c_code


def test_declares_state():
    c = _build(_straight()).unwrap().c_code
    assert "#define limit 3" in c
    assert "enum Color { green, red };" in c
    assert "unsigned char x = 0;" in c
    assert "enum Color c = red;" in c
    assert "_Bool flag = false;" in c
    assert "#include <stdbool.h>" in c


def test_main_calculates_cwp_state_before_loop():
    c = _build(_straight()).unwrap().c_code
    main = c[c.index("int main(void)") :]
    assert main.index("cwp_calculate_state();") < main.index("for (")
    assert "bpmn_step();" in main
    # the CWP functions are defined before main uses them
    assert c.index("void cwp_calculate_state") < c.index("int main(void)")


def test_main_loop_stops_when_all_ended():
    c = _build(_straight()).unwrap().c_code
    assert "!(ended_p)" in c


def test_build_returns_just_the_c():
    builder = (
        CbmcBuilder()
        .with_state(_state())
        .with_cwp(_cwp())
        .with_bpmn(_straight().bpmn())
    )
    assert builder.build().unwrap() == builder.build_program().unwrap().c_code


def test_initial_cwp_state_is_checked(tmp_path):
    # x starts at 0 so the CWP's start state is active; a state where no CWP
    # state holds is caught when main() computes the starting state
    state = State.from_str(
        STATE_TXT.replace("var x: byte = 0", "var x: byte = 2")
    ).unwrap()
    program = (
        CbmcBuilder()
        .with_state(state)
        .with_cwp(_cwp())
        .with_bpmn(_straight().bpmn())
        .build_program()
        .unwrap()
    )
    result = _cbmc(tmp_path, program)
    assert "VERIFICATION FAILED" in result.stdout
    assert "initial values" in result.stdout


@pytest.mark.parametrize("missing", ["state", "cwp", "bpmn"])
def test_missing_input_is_an_error(missing):
    builder = CbmcBuilder()
    if missing != "state":
        builder.with_state(_state())
    if missing != "cwp":
        builder.with_cwp(_cwp())
    if missing != "bpmn":
        builder.with_bpmn(_straight().bpmn())
    result = builder.build()
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), NotInitializedError)
    assert result.failure().var_name == f"CbmcBuilder.{missing}"


def test_nothing_set_is_an_error():
    assert isinstance(CbmcBuilder().build().failure(), NotInitializedError)


def test_bpmn_without_processes_is_an_error():
    result = (
        CbmcBuilder().with_state(_state()).with_cwp(_cwp()).with_bpmn(Bpmn()).build()
    )
    assert isinstance(result.failure(), CbmcBuildError)


def test_visitor_error_is_returned():
    g = Graph().start("s").task("t").end("e").flow("s", "t", "e")
    g.nodes["t"].msg_boundary_events = [Task.BoundaryEvent("b", "b", "", "", "t")]
    result = _build(g)
    assert isinstance(result.failure(), BpmnCbmcUnsupportedElementError)


@pytest.mark.parametrize("name", ["workflow", "face2face_open"])
def test_face2face_builds(name):
    with open(FACE2FACE + "state.txt") as f:
        state = State.from_str(f.read()).unwrap()
    with open(FACE2FACE + "cwp.xml") as f:
        cwp = CwpXmlParser.from_xml(fromstring(f.read()), state).unwrap()
    with open(f"{FACE2FACE}{name}.bpmn") as f:
        bpmn = bpmnmethods.from_xml(fromstring(f.read()), state).unwrap()
    result = (
        CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn).build_program()
    )
    if isinstance(result, Failure):
        # parallel gateways arrive with a later subtask
        assert isinstance(result.failure(), BpmnCbmcUnsupportedElementError)
        pytest.skip("parallel gateways not supported by the BPMN visitor yet")
    program = result.unwrap()
    assert program.bound == 25
    assert "cwp_calculate_state();" in program.c_code


def test_given_face2face_when_build_then_reachability_covers_present():
    from returns.unsafe import unsafe_perform_io

    from bpmncwpverify.builder.cbmc_builder import CbmcBuilder
    from bpmncwpverify.core.accessmethods import bpmnmethods
    from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
    from bpmncwpverify.core.state import State
    from bpmncwpverify.util.file import element_tree_from_string

    base = "./test/resources/face2face/"

    def read(name):
        with open(base + name) as f:
            return f.read()

    def xml(name):
        return unsafe_perform_io(element_tree_from_string(read(name)).unwrap())

    state = State.from_str(read("state.txt")).unwrap()
    cwp = CwpXmlParser.from_xml(xml("cwp.xml"), state).unwrap()
    bpmn = bpmnmethods.from_xml(xml("workflow.bpmn"), state).unwrap()

    c_code = (
        CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn).build().unwrap()
    )

    assert c_code.count("#ifdef REACHABILITY") == c_code.count("#endif")
    assert c_code.count("/* BPMN end event ") == 2
    assert c_code.count("/* CWP state ") == len(cwp.states) - 1
    assert f"/* CWP state {cwp.start_state.name} */" not in c_code
