# type: ignore
import pytest
from returns.functions import not_
from returns.pipeline import is_successful
from returns.result import Success

from bpmncwpverify.builder.cwp_builder import CwpBuilder
from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState
from bpmncwpverify.core.error import (
    CwpNoEndStatesError,
    CwpNoParentEdgeError,
    FeelConditionTypeError,
    FeelSyntaxError,
    FeelUnknownNameError,
    FeelUnsupportedError,
)
from bpmncwpverify.core.feel_tree import BinaryOp, Boolean, Name, Number
from bpmncwpverify.core.state import State


@pytest.fixture
def builder():
    return CwpBuilder()


def create_mock_state(mocker, state_id, out_edges=None, in_edges=None):
    state = mocker.MagicMock()
    state.id = state_id
    state.out_edges = out_edges or []
    state.in_edges = in_edges or []
    return state


def create_mock_edge(mocker, name, dest=None):
    edge = mocker.MagicMock()
    edge.name = name
    edge.dest = dest
    edge.is_leaf = False
    return edge


def test_gen_edge_name(builder):
    assert builder.gen_edge_name() == "EdgeA"
    assert builder.gen_edge_name() == "EdgeB"
    assert builder.gen_edge_name() == "EdgeC"


def _door_state():
    return State.from_str(
        "enum Door {open closed}\nvar door: Door = closed\nvar count: byte = 0"
    ).unwrap()


def _builder_with_edge():
    builder = CwpBuilder()
    edge = CwpEdge("edge", "EdgeA")
    builder._cwp.edges["edge"] = edge
    return builder, edge


def test_check_expression(mocker):
    builder, edge = _builder_with_edge()

    builder.check_expression(
        mocker.Mock(),
        "<div>door = open and</div><div>count = 3</div>",
        "edge",
        _door_state(),
    )

    assert edge.expression == "door = open and count = 3"
    assert edge.expression_tree == BinaryOp(
        "and",
        BinaryOp("=", Name("door"), Name("open")),
        BinaryOp("=", Name("count"), Number(3)),
    )


@pytest.mark.parametrize(
    "expression, error",
    [
        ("door == open", FeelSyntaxError),
        ("door = open &amp;&amp; count = 3", FeelSyntaxError),
        ("count = 1 || count = 2", FeelSyntaxError),
        ("some x in [1] satisfies x > 0", FeelUnsupportedError),
        ("count + 1", FeelConditionTypeError),
        ("light = on", FeelUnknownNameError),
    ],
)
def test_check_expression_with_bad_feel_raises_feel_error(mocker, expression, error):
    builder, edge = _builder_with_edge()

    with pytest.raises(Exception) as exc_info:
        builder.check_expression(mocker.Mock(), expression, "edge", _door_state())

    assert isinstance(exc_info.value.args[0], error)
    assert edge.expression_tree is None


def test_with_start_edge_stores_init_condition_as_feel():
    builder = CwpBuilder()
    start = CwpState("s", "s")
    start.out_edges.append(CwpEdge("e", "EdgeB"))
    builder._cwp.states["s"] = start
    builder.find_start_state()
    edge = CwpEdge("Init_Edge", "EdgeA")
    edge.expression = "door == closed && count == 0"

    builder.with_start_edge(edge)

    assert edge.expression == "door = closed and count = 0"
    assert edge.expression_tree == BinaryOp(
        "and",
        BinaryOp("=", Name("door"), Name("closed")),
        BinaryOp("=", Name("count"), Number(0)),
    )


def test_with_start_edge_without_variables_is_true():
    builder = CwpBuilder()
    start = CwpState("s", "s")
    start.out_edges.append(CwpEdge("e", "EdgeB"))
    builder._cwp.states["s"] = start
    builder.find_start_state()
    edge = CwpEdge("Init_Edge", "EdgeA")

    builder.with_start_edge(edge)

    assert edge.expression_tree == Boolean(True)


def test_check_expression_no_parent(mocker):
    builder = CwpBuilder()
    builder._cwp = Cwp()
    builder._cwp.edges = {"edge": mocker.MagicMock()}

    with pytest.raises(Exception) as exc_info:
        builder.check_expression(
            mocker.Mock(), mocker.Mock(), mocker.Mock(), mocker.Mock()
        )

    assert isinstance(exc_info.value.args[0], CwpNoParentEdgeError)


def test_with_edge(mocker):
    builder = CwpBuilder()
    builder._cwp = Cwp()
    source = mocker.MagicMock()
    source.out_edges = []
    dest = mocker.MagicMock()
    dest.in_edges = []
    builder._cwp.states = {"node1": source, "node2": dest}

    mock_edge = mocker.MagicMock()
    mock_edge.id = "edge1"

    builder.with_edge(mock_edge, "node1", "node2")

    mock_edge.set_source.assert_called_once_with(source)
    mock_edge.set_dest.assert_called_once_with(dest)

    assert builder._cwp.edges[mock_edge.id] == mock_edge
    assert len(dest.in_edges) == 1
    assert len(source.out_edges) == 1


def test_find_start_state(mocker):
    states: dict[str, CwpState] = {
        "state1": mocker.MagicMock(
            spec=CwpState, in_edges=[], out_edges=["edge1"], init_state=False
        ),
        "state2": mocker.MagicMock(
            spec=CwpState, in_edges=["edge1"], out_edges=["edge2"], init_state=False
        ),
        "state3": mocker.MagicMock(
            spec=CwpState, in_edges=["edge2"], out_edges=[], init_state=False
        ),
    }

    mock_cwp = mocker.MagicMock()
    mock_cwp.states = states

    obj = CwpBuilder()
    obj._cwp = mock_cwp
    obj._cwp.states = states

    result = obj.find_start_state()

    assert result._cwp.start_state == states["state1"]
    assert mock_cwp.states["state1"].init_state


def test_build(mocker):
    states: dict[str, CwpState] = {
        "state1": mocker.MagicMock(
            spec=CwpState, in_edges=["Init_Edge"], out_edges=["edge1"], init_state=True
        ),
        "state2": mocker.MagicMock(
            spec=CwpState, in_edges=["edge1"], out_edges=["edge2"], init_state=False
        ),
        "state3": mocker.MagicMock(
            spec=CwpState, in_edges=["edge2"], out_edges=[], init_state=False
        ),
    }
    edges = {
        "Init_Edge": mocker.MagicMock(),
        "edge1": mocker.MagicMock(),
        "edge2": mocker.MagicMock(),
    }

    mock_cwp = mocker.MagicMock()
    mock_cwp.states = states
    mock_cwp.start_state = states["state1"]

    obj = CwpBuilder()
    obj._cwp = mock_cwp
    obj._cwp.states = states
    obj._cwp.edges = edges
    mock_cwp.accept = mocker.MagicMock()

    result = obj.build()

    assert isinstance(result, Success)
    assert result.unwrap() == mock_cwp

    start_state = states["state1"]
    end_states = [states["state3"]]
    assert mock_cwp.start_state == start_state
    assert list(end_states) == [states["state3"]]

    mock_cwp.accept.assert_called_once()

    new_edge = CwpEdge(mocker.MagicMock(), mocker.MagicMock())
    states["state1"].init_state = False
    states["state3"].out_edges = [new_edge]

    result = obj.build()

    assert not_(is_successful)(result)
    assert isinstance(result.failure(), CwpNoEndStatesError)
