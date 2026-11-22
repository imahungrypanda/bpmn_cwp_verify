# type: ignore
import shutil
import subprocess

import pytest

from bpmncwpverify.builder.cbmc_builder import CbmcBuilder
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

STATE = """enum Color { red green }
const limit: byte = 3
var x: int = 0
var c: Color = red
"""

needs_cbmc = pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc missing")


def seq(src, dst, id, expression=""):
    flow = SequenceFlow(id, id)
    flow.expression = expression
    flow.source_node = src
    flow.target_node = dst
    src.add_out_flow(flow)
    dst.add_in_flow(flow)


def make_bpmn(*nodes):
    proc = Process("p", "p")
    for node in nodes:
        proc[node.id] = node
    bpmn = Bpmn()
    bpmn.processes["p"] = proc
    return bpmn


def straight():
    s, t, e = (
        StartEvent("S", "S", "", ""),
        Task("T", "T", ""),
        EndEvent("E", "E", "", ""),
    )
    seq(s, t, "f1")
    seq(t, e, "f2")
    return make_bpmn(s, t, e)


def with_gateway():
    s, g = StartEvent("S", "S", "", ""), ExclusiveGatewayNode("G", "G")
    a, b = EndEvent("A", "A", "", ""), EndEvent("B", "B", "", "")
    seq(s, g, "f1")
    seq(g, a, "f2", "x == 0")
    seq(g, b, "f3", "x != 0")
    return make_bpmn(s, g, a, b)


def make_cwp():
    cwp = Cwp()
    for name in ("Start", "Done"):
        cwp.states[name] = CwpState(name, name)
    edge = CwpEdge("e0", "Edge0")
    edge.expression = "x == 1"
    edge.set_source(cwp.states["Start"])
    edge.set_dest(cwp.states["Done"])
    cwp.states["Start"].out_edges.append(edge)
    cwp.states["Done"].in_edges.append(edge)
    cwp.edges["e0"] = edge
    cwp.start_state = cwp.states["Start"]
    cwp.end_states = [cwp.states["Done"]]
    return cwp


def builder(bpmn):
    return (
        CbmcBuilder()
        .with_state(State.from_str(STATE).unwrap())
        .with_cwp(make_cwp())
        .with_bpmn(bpmn)
    )


@pytest.mark.parametrize("make", [straight, with_gateway])
@needs_cbmc
def test_c_compiles_and_verifies(make, tmp_path):
    b = builder(make())
    c = b.build().unwrap()
    path = tmp_path / "prog.c"
    path.write_text(c)
    result = subprocess.run(
        ["cbmc", str(path), "--unwind", str(b.unwind().unwrap())],
        capture_output=True,
        text=True,
    )
    assert "VERIFICATION" in result.stdout, result.stdout + result.stderr
    assert result.returncode in (0, 10), result.stdout


def test_state_declarations():
    c = builder(straight()).build().unwrap()
    assert "#define limit 3" in c
    assert "enum Color { green, red };" in c
    assert "static int x = 0;" in c
    assert "static enum Color c = red;" in c


def test_cwp_state_calculated_before_loop():
    c = builder(straight()).build().unwrap()
    main = c[c.index("int main(void)") :]
    assert main.index("cwp_calculate_state();") < main.index("for (")
    assert main.index("tok_S = true;") < main.index("for (")
    assert "cwp_update_state();" in main[main.index("for (") :]
    assert "pass < 3u" in main


def test_bound_and_unwind():
    b = builder(straight())
    assert b.bound().unwrap() == 3
    assert b.unwind().unwrap() == 4
    assert "// cbmc --unwind 4" in b.build().unwrap()


def test_main_has_no_loop_over_transitions():
    c = builder(with_gateway()).build().unwrap()
    assert c[c.index("int main(void)") :].count("for (") == 1


@pytest.mark.parametrize("missing", ["state", "cwp", "bpmn"])
def test_missing_input(missing):
    b = builder(straight())
    setattr(b, missing, CbmcBuilder().__getattribute__(missing))
    error = b.build().failure()
    assert isinstance(error, NotInitializedError)
    assert error.var_name == f"CbmcBuilder.{missing}"


def test_unsupported_element_is_returned_as_error():
    s, g = StartEvent("S", "S", "", ""), ExclusiveGatewayNode("G", "G")
    seq(s, g, "f1")
    result = builder(make_bpmn(s, g)).build()
    assert isinstance(result.failure(), BpmnCbmcUnsupportedElementError)


def test_other_exceptions_become_build_error(mocker):
    mocker.patch(
        "bpmncwpverify.builder.cbmc_builder.CwpCbmcVisitor",
        side_effect=ValueError("boom"),
    )
    error = builder(straight()).build().failure()
    assert isinstance(error, CbmcBuildError)
    assert error.reason == "boom"
