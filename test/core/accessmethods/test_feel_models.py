# type: ignore
from pathlib import Path
from xml.etree.ElementTree import parse

from returns.result import Failure, Success

from bpmncwpverify.core.accessmethods import bpmnmethods
from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.bpmn import Task
from bpmncwpverify.core.error import (
    FeelUnknownNameError,
    FeelUnsupportedError,
)
from bpmncwpverify.core.feel_tree import Behavior, FeelNode
from bpmncwpverify.core.state import State

FEEL = Path(__file__).parents[2] / "resources" / "feel"


def _state() -> State:
    return State.from_str((FEEL / "state.txt").read_text()).unwrap()


def _bpmn(text: str | None = None):
    path = FEEL / "test_bpmn.bpmn"
    root = parse(path).getroot() if text is None else None
    if text is not None:
        from xml.etree.ElementTree import fromstring

        root = fromstring(text)
    return bpmnmethods.from_xml(root, _state())


def _items(bpmn):
    return [i for p in bpmn.processes.values() for i in p.all_items().values()]


def test_feel_bpmn_holds_trees():
    bpmn = _bpmn().unwrap()
    items = _items(bpmn)
    task = next(i for i in items if isinstance(i, Task))
    assert isinstance(task.behavior, Behavior)
    flows = [f for i in items for f in i.out_flows if f.expression]
    assert len(flows) == 2
    assert all(isinstance(f.expression, FeelNode) for f in flows)


def test_feel_bpmn_unknown_name_stops_load():
    text = (
        (FEEL / "test_bpmn.bpmn").read_text().replace("(x, [x], x + 1)", "(x, [x], q)")
    )
    result = _bpmn(text)
    assert isinstance(result, Failure)
    assert result.failure() == FeelUnknownNameError("q") or isinstance(
        result.failure(), FeelUnknownNameError
    )


def test_feel_bpmn_unsupported_stops_load():
    text = (
        (FEEL / "test_bpmn.bpmn")
        .read_text()
        .replace("(x, [x], x + 1)", "(x, [x], f(x))")
    )
    result = _bpmn(text)
    assert isinstance(result.failure(), FeelUnsupportedError)


def test_feel_bpmn_bad_condition_type_stops_load():
    text = (
        (FEEL / "test_bpmn.bpmn").read_text().replace("not (x &gt; 5)", "x + 1 and x")
    )
    assert isinstance(_bpmn(text), Failure)


def test_legacy_strings_still_load():
    path = (
        Path(__file__).parents[2] / "resources" / "simple_example" / "simple_open.bpmn"
    )
    bpmn = bpmnmethods.from_xml(parse(path).getroot(), _state()).unwrap()
    items = _items(bpmn)
    task = next(i for i in items if isinstance(i, Task))
    assert isinstance(task.behavior, str)


def test_feel_cwp_holds_trees():
    cwp = CwpXmlParser.from_xml(parse(FEEL / "test_cwp.xml").getroot(), _state())
    assert isinstance(cwp, Success)
    exprs = [e.expression for e in cwp.unwrap().edges.values() if e.id != "Init_Edge"]
    assert len(exprs) == 2
    assert all(isinstance(e, FeelNode) for e in exprs)


def test_feel_cwp_error_stops_load():
    text = (
        (FEEL / "test_cwp.xml").read_text().replace("not (x &amp;gt; 5)", "q and true")
    )
    from xml.etree.ElementTree import fromstring

    result = CwpXmlParser.from_xml(fromstring(text), _state())
    assert isinstance(result.failure(), FeelUnknownNameError)


def test_legacy_cwp_edges_stay_strings():
    path = Path(__file__).parents[2] / "resources" / "simple_example" / "test_cwp.xml"
    cwp = CwpXmlParser.from_xml(parse(path).getroot(), _state()).unwrap()
    assert all(isinstance(e.expression, str) for e in cwp.edges.values())
