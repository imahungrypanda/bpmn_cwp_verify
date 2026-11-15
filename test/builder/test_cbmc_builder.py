import shutil
import subprocess
from xml.etree.ElementTree import parse

import pytest
from returns.result import Failure, Success

from bpmncwpverify.builder.cbmc_bound import get_unwinding_bound
from bpmncwpverify.builder.cbmc_builder import CbmcBuilder
from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.bpmn import (
    Bpmn,
    EndEvent,
    ExclusiveGatewayNode,
    Node,
    Process,
    SequenceFlow,
    StartEvent,
    Task,
)
from bpmncwpverify.core.cwp import Cwp
from bpmncwpverify.core.error import (
    BpmnCbmcUnsupportedError,
    CbmcBuildError,
    NotInitializedError,
)
from bpmncwpverify.core.state import State

SIMPLE = "test/resources/simple_example/"
STATE_STR = "var x: int = 0\n"
ENUM_STATE_STR = (
    "enum Color {red green}\n"
    "const limit: byte = 3\n"
    "var c: Color = red\n"
    "var flag: bool = false\n"
    "var n: byte = 0\n"
)


class Graph:
    def __init__(self) -> None:
        self.process = Process("p", "p")
        self._count = 0

    def add(self, node: Node) -> Node:
        self.process[node.id] = node
        return node

    def link(self, source: Node, target: Node, expression: str = "") -> None:
        self._count += 1
        flow = SequenceFlow(f"f{self._count}", "")
        flow.expression = expression
        flow.source_node, flow.target_node = source, target
        source.add_out_flow(flow)
        target.add_in_flow(flow)
        self.process[flow.id] = flow

    def bpmn(self) -> Bpmn:
        bpmn = Bpmn()
        bpmn.processes[self.process.id] = self.process
        return bpmn


def straight_line() -> Bpmn:
    g = Graph()
    s = g.add(StartEvent("s", "s", "", ""))
    a = g.add(Task("a", "a", ""))
    e = g.add(EndEvent("e", "e", "", ""))
    g.link(s, a)
    g.link(a, e)
    return g.bpmn()


def with_gateway() -> Bpmn:
    g = Graph()
    s = g.add(StartEvent("s", "s", "", ""))
    x = g.add(ExclusiveGatewayNode("x", "x"))
    a = g.add(Task("a", "a", ""))
    e = g.add(EndEvent("e", "e", "", ""))
    g.link(s, x)
    g.link(x, a, "x < 5")
    g.link(x, e, "x >= 5")
    g.link(a, e)
    return g.bpmn()


def simple_cwp(state: State) -> Cwp:
    return CwpXmlParser.from_xml(
        parse(SIMPLE + "test_cwp.xml").getroot(), state
    ).unwrap()


def builder(bpmn: Bpmn, state_str: str = STATE_STR) -> CbmcBuilder:
    state = State.from_str(state_str).unwrap()
    cwp = simple_cwp(State.from_str(STATE_STR).unwrap())
    return CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn)


def build_c(bpmn: Bpmn, state_str: str = STATE_STR) -> str:
    result = builder(bpmn, state_str).build()
    assert isinstance(result, Success)
    return result.unwrap()


def compiles(c: str, tmp_path) -> bool:
    gcc = shutil.which("gcc") or shutil.which("cc")
    if gcc is None:
        pytest.skip("no C compiler")
    src = tmp_path / "out.c"
    src.write_text(c)
    proc = subprocess.run(
        [gcc, "-fsyntax-only", "-Wall", str(src)], capture_output=True, text=True
    )
    return proc.returncode == 0


@pytest.mark.parametrize("make", [straight_line, with_gateway])
def test_c_compiles(make, tmp_path):
    c = build_c(make())
    assert compiles(c, tmp_path), c


def test_enum_const_and_var_declarations(tmp_path):
    c = build_c(straight_line(), ENUM_STATE_STR)
    assert "#define limit 3" in c
    assert "enum Color {green, red};" in c
    assert "enum Color c = red;" in c
    assert "bool flag = false;" in c
    assert "unsigned char n = 0;" in c
    assert c.index("enum Color c = red;") < c.index("int main(void)")


def test_main_sets_cwp_state_before_loop():
    c = build_c(straight_line())
    main = c[c.index("int main(void)") :]
    assert main.index("cwp_calculate_state();") < main.index("for (")
    assert "cwp_update_state();" in main[main.index("for (") :]


def test_loop_is_bounded_and_has_one_step_per_pass():
    bpmn = straight_line()
    c = build_c(bpmn)
    bound = get_unwinding_bound(bpmn)
    assert f"#define UNWINDING_BOUND {bound}" in c
    assert c.count("for (") == 1
    assert c.count("nondet_int();") == 1
    assert builder(bpmn).unwinding_bound() == Success(bound)


def test_state_declared_before_use():
    c = build_c(with_gateway())
    assert c.index("int x = 0;") < c.index("enabled_")


def test_missing_inputs_give_errors():
    bpmn = straight_line()
    state = State.from_str(STATE_STR).unwrap()
    cwp = simple_cwp(state)
    for b in (
        CbmcBuilder().with_cwp(cwp).with_bpmn(bpmn),
        CbmcBuilder().with_state(state).with_bpmn(bpmn),
        CbmcBuilder().with_state(state).with_cwp(cwp),
        CbmcBuilder(),
    ):
        result = b.build()
        assert isinstance(result, Failure)
        assert isinstance(result.failure(), NotInitializedError)
    assert isinstance(CbmcBuilder().unwinding_bound(), Failure)


def test_empty_cwp_is_an_error():
    state = State.from_str(STATE_STR).unwrap()
    result = (
        CbmcBuilder()
        .with_state(state)
        .with_cwp(Cwp())
        .with_bpmn(straight_line())
        .build()
    )
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), CbmcBuildError)


def test_unsupported_bpmn_error_is_passed_on():
    g = Graph()
    s = g.add(StartEvent("s", "s", "", ""))
    x = g.add(ExclusiveGatewayNode("x", "x"))
    e = g.add(EndEvent("e", "e", "", ""))
    g.link(s, x)
    g.link(x, e)  # a gateway flow needs a condition
    result = builder(g.bpmn()).build()
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), BpmnCbmcUnsupportedError)


def test_unknown_variable_type_is_an_error():
    state = State.from_str(STATE_STR).unwrap()
    state.vars[0].type_ = "float"
    result = (
        CbmcBuilder()
        .with_state(state)
        .with_cwp(simple_cwp(state))
        .with_bpmn(straight_line())
        .build()
    )
    assert isinstance(result, Failure)
    assert isinstance(result.failure(), CbmcBuildError)
