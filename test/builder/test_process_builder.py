# type: ignore
import pytest
from returns.result import Failure, Success

from bpmncwpverify.builder.process_builder import ProcessBuilder
from bpmncwpverify.core.bpmn import EndEvent, Node, SequenceFlow, StartEvent, Task
from bpmncwpverify.core.error import (
    FeelAssignTypeError,
    FeelBehaviorTypeError,
    FeelConditionTypeError,
    FeelInvalidTargetError,
    FeelOperatorTypeError,
    FeelSyntaxError,
    FeelUnknownNameError,
    FeelUnsupportedError,
)
from bpmncwpverify.core.feel_tree import (
    BinaryOp,
    Name,
    Number,
    Triple,
    TripleList,
)
from bpmncwpverify.core.state import State


def test_add_element(mocker):
    mock_element = mocker.MagicMock()
    mock_element.id = "1"

    builder = ProcessBuilder(mocker.MagicMock(), mocker.MagicMock(), mocker.MagicMock())

    mock_process = mocker.MagicMock()
    builder._process = mock_process

    builder.with_element(mock_element)

    mock_process.__setitem__.assert_called_once_with("1", mock_element)


def test_build_graph(mocker):
    mock_process = mocker.MagicMock()

    class MockNode(Node):
        def __init__(self, id):
            self.id = id
            self.out_flows = []
            self.in_flows = []

        def add_out_flow(self, flow):
            self.out_flows.append(flow)

        def add_in_flow(self, flow):
            self.in_flows.append(flow)

    element_1 = mocker.MagicMock(
        attrib={"id": "flow_1", "sourceRef": "node_1", "targetRef": "node_2"}
    )
    element_2 = mocker.MagicMock(
        attrib={"id": "flow_2", "sourceRef": "node_2", "targetRef": "node_1"}
    )

    flow_1 = mocker.MagicMock(spec=SequenceFlow, element=element_1, expression="")
    flow_2 = mocker.MagicMock(spec=SequenceFlow, element=element_2, expression="")

    node_1 = MockNode(id="node_1")
    node_2 = MockNode(id="node_2")

    mock_process.__getitem__.side_effect = lambda key: {
        "flow_1": flow_1,
        "flow_2": flow_2,
        "node_1": node_1,
        "node_2": node_2,
    }[key]

    mock_process.element.findall.return_value = [element_1, element_2]

    builder = ProcessBuilder(mocker.Mock(), mocker.Mock(), mocker.Mock())
    builder._process = mock_process

    builder.with_process_flow("flow_1", "node_1", "node_2", None)
    builder.with_process_flow("flow_2", "node_2", "node_1", None)

    assert flow_1.source_node == node_1
    assert flow_1.target_node == node_2
    assert flow_2.source_node == node_2
    assert flow_2.target_node == node_1
    assert node_1.out_flows == [flow_1]
    assert node_2.in_flows == [flow_1]
    assert node_2.out_flows == [flow_2]
    assert node_1.in_flows == [flow_2]


DOOR_STATE = """
enum Door {open closed}
enum Light {on off}

var door: Door = closed
var light: Light = off
var count: byte = 0
"""


def _door_state() -> State:
    return State.from_str(DOOR_STATE).unwrap()


def _two_nodes_builder() -> tuple[ProcessBuilder, SequenceFlow]:
    builder = ProcessBuilder("p", "p", _door_state())
    flow = SequenceFlow("flow_1", "flow_1")
    builder.with_element(StartEvent("node_1", "node_1", "", ""))
    builder.with_element(EndEvent("node_2", "node_2", "", ""))
    builder.with_element(flow)
    return builder, flow


def test_flow_condition_is_parsed_and_stored_as_feel():
    builder, flow = _two_nodes_builder()

    result = builder.with_process_flow(
        "flow_1", "node_1", "node_2", "door = open and count < 3"
    )

    assert isinstance(result, Success)
    assert flow.expression == "door = open and count < 3"
    assert flow.expression_tree == BinaryOp(
        "and",
        BinaryOp("=", Name("door"), Name("open")),
        BinaryOp("<", Name("count"), Number(3)),
    )


def test_flow_without_condition_has_no_tree():
    builder, flow = _two_nodes_builder()

    builder.with_process_flow("flow_1", "node_1", "node_2", "")

    assert flow.expression_tree is None


@pytest.mark.parametrize(
    "expression, error",
    [
        ("door == open && count < 3", FeelSyntaxError),
        ("count < 3 || door = open", FeelSyntaxError),
        ("for i in [1, 2] return i", FeelUnsupportedError),
        ("count + 1", FeelConditionTypeError),
        ("door = 1", FeelOperatorTypeError),
        ("nothing = 1", FeelUnknownNameError),
    ],
)
def test_bad_flow_condition_fails_with_feel_error(expression, error):
    builder, flow = _two_nodes_builder()

    result = builder.with_process_flow("flow_1", "node_1", "node_2", expression)

    assert isinstance(result, Failure)
    assert isinstance(result.failure(), error)
    assert flow.expression_tree is None


def _linear_builder(behavior: str) -> tuple[ProcessBuilder, Task]:
    builder = ProcessBuilder("p", "p", _door_state())
    task = Task("task", "task", behavior)
    builder.with_element(StartEvent("start", "start", "", ""))
    builder.with_element(task)
    builder.with_element(EndEvent("end", "end", "", ""))
    builder.with_element(SequenceFlow("f1", "f1"))
    builder.with_element(SequenceFlow("f2", "f2"))
    builder.with_process_flow("f1", "start", "task", "").unwrap()
    builder.with_process_flow("f2", "task", "end", "").unwrap()
    return builder, task


def test_task_behavior_is_parsed_and_stored_as_feel():
    builder, task = _linear_builder("(door, [], open)")

    assert isinstance(builder.build(), Success)
    assert task.behavior_tree == Triple("door", (), Name("open"))


def test_task_behavior_triple_list_is_stored_as_feel():
    builder, task = _linear_builder(
        "((light, [], choose [on, off]),\n(count, [count], count + 1))"
    )

    assert isinstance(builder.build(), Success)
    assert isinstance(task.behavior_tree, TripleList)
    assert [t.target for t in task.behavior_tree.triples] == ["light", "count"]


def test_task_without_behavior_has_no_tree():
    builder, task = _linear_builder("")

    assert isinstance(builder.build(), Success)
    assert task.behavior_tree is None


@pytest.mark.parametrize(
    "behavior, error",
    [
        ("door = open", FeelBehaviorTypeError),
        ("count = count + 1", FeelBehaviorTypeError),
        ("if\n:: true -> door = open\nfi", FeelUnsupportedError),
        ("(door, [], 1)", FeelAssignTypeError),
        ("(nothing, [], 1)", FeelInvalidTargetError),
    ],
)
def test_bad_task_behavior_fails_with_feel_error(behavior, error):
    builder, task = _linear_builder(behavior)

    result = builder.build()

    assert isinstance(result, Failure)
    assert isinstance(result.failure(), error)
    assert task.behavior_tree is None


@pytest.fixture
def get_pb_task_boundevent(mocker):
    pb = ProcessBuilder("test_id", "test_name", mocker.Mock())
    pb._process = mocker.MagicMock()

    task_id = "task_id"
    boundary_event_id = "boundary_event_id"

    task = mocker.Mock(spec=Task)
    task.boundary_events = []
    task.id = task_id

    boundary_event = mocker.Mock(spec=Task.BoundaryEvent)
    boundary_event.parent_task = "task_id"
    boundary_event.id = boundary_event_id

    all_items_data = {task_id: task, boundary_event_id: boundary_event}
    all_items = mocker.Mock()
    all_items.return_value = all_items_data
    all_items.get.side_effect = lambda x: all_items_data.get(x)
    pb._process.all_items = all_items
    pb._process.__getitem__.side_effect = lambda x: all_items_data[x]

    return pb, task, boundary_event


def test_with_boundary_events_valid(get_pb_task_boundevent):
    pb, task, boundary_event = get_pb_task_boundevent

    pb.with_boundary_events()

    task.add_boundary_event.assert_called_once_with(boundary_event)


def test_with_boundary_events_no_parent_task(get_pb_task_boundevent):
    pb, _, boundary_event = get_pb_task_boundevent
    all_items_data = {"boundary_event_id": boundary_event}

    pb._process.all_items.return_value = all_items_data
    pb._process.all_items.get.side_effect = lambda x: all_items_data.get(x)

    with pytest.raises(AssertionError) as exc_info:
        pb.with_boundary_events()

    assert (
        exc_info.value.args[0]
        == "Boundary event 'boundary_event_id' references a missing parent task ID: task_id"
    )


def test_with_boundary_events_parent_not_task(get_pb_task_boundevent, mocker):
    pb, _, boundary_event = get_pb_task_boundevent

    class MyClass:
        pass

    not_task = MyClass()
    all_items_data = {"boundary_event_id": boundary_event, "task_id": not_task}

    pb._process.all_items.return_value = all_items_data
    pb._process.all_items.get.side_effect = lambda x: all_items_data.get(x)

    with pytest.raises(AssertionError) as exc_info:
        pb.with_boundary_events()

    assert (
        exc_info.value.args[0]
        == "Boundary event 'boundary_event_id' is attached to non-Task object: MyClass"
    )
