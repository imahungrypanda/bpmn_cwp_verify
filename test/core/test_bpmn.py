# type: ignore
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

import pytest
from defusedxml import ElementTree
from returns.result import Failure, Success

from bpmncwpverify.core.accessmethods.bpmnmethods import from_xml
from bpmncwpverify.core.bpmn import BPMN_XML_NAMESPACE, StartEvent, Task
from bpmncwpverify.core.error import (
    BpmnMissingEventsError,
    BpmnNoElementNameError,
    BpmnNoSwimLaneNameError,
    FeelAssignTypeError,
    FeelBehaviorTypeError,
    FeelConditionTypeError,
    FeelSyntaxError,
    FeelUnsupportedError,
)
from bpmncwpverify.core.feel_tree import BinaryOp, Name, Number, TripleList
from bpmncwpverify.core.state import State, StateBuilder


def create_bpmn_definition():
    """Create a basic BPMN definitions root element."""
    root = Element(
        "bpmn:definitions",
        attrib={
            "xmlns:bpmn": BPMN_XML_NAMESPACE["bpmn"],
            "id": "Definitions_1",
            "targetNamespace": "http://example.com/schema/bpmn",
        },
    )
    collab = SubElement(root, "bpmn:collaboration", attrib={"id": "Collaboration_1"})
    return root, collab


def add_process(collab: Element, process_id="Process_1"):
    """Add a collaboration and participant to the BPMN definition."""
    SubElement(
        collab,
        "bpmn:participant",
        attrib={
            "id": "Participant_1",
            "name": "Test Participant",
            "processRef": process_id,
        },
    )


def add_process_with_elements(root, elements):
    """Add a process with specified elements to the BPMN definition."""
    process = SubElement(
        root, "bpmn:process", attrib={"id": "Process_1", "isExecutable": "false"}
    )
    for element in elements:
        process.append(element)


def test_complete_bpmn_with_no_start_or_end_event():
    state = StateBuilder().build()
    root, collab = create_bpmn_definition()
    add_process(collab)
    task = Element("bpmn:task", attrib={"id": "Task_1", "name": "Test Task"})
    add_process_with_elements(root, [task])

    bpmn = tostring(root, encoding="unicode")
    parsed_root = ElementTree.fromstring(bpmn)
    result = from_xml(parsed_root, state)

    assert isinstance(result, Failure)
    exception = result.failure()
    assert isinstance(exception, BpmnMissingEventsError)


def test_complete_bpmn_with_no_end_event():
    state = StateBuilder().build()
    root, collab = create_bpmn_definition()
    add_process(collab)

    start_event = Element("bpmn:startEvent", attrib={"id": "se1"})
    outgoing = SubElement(start_event, "bpmn:outgoing")
    outgoing.text = "flow1"
    gateway = Element("bpmn:exclusiveGateway", attrib={"id": "eg1"})
    sequence_flow = Element(
        "bpmn:sequenceFlow",
        attrib={"id": "flow1", "sourceRef": "se1", "targetRef": "eg1"},
    )

    add_process_with_elements(root, [start_event, gateway, sequence_flow])

    bpmn = tostring(root, encoding="unicode")
    parsed_root = ElementTree.fromstring(bpmn)
    result = from_xml(parsed_root, state)

    assert isinstance(result, Failure)
    exception = result.failure()
    assert isinstance(exception, BpmnMissingEventsError)


def test_complete_bpmn_with_good_process():
    state = StateBuilder().build()
    root, collab = create_bpmn_definition()
    add_process(collab)

    start_event = Element(
        "bpmn:startEvent", attrib={"id": "startevent_1", "name": "Start"}
    )
    outgoing = SubElement(start_event, "bpmn:outgoing")
    outgoing.text = "flow1"
    end_event = Element("bpmn:endEvent", attrib={"id": "event_e1", "name": "End"})
    sequence_flow = Element(
        "bpmn:sequenceFlow",
        attrib={"id": "flow1", "sourceRef": "startevent_1", "targetRef": "event_e1"},
    )

    add_process_with_elements(root, [start_event, end_event, sequence_flow])

    bpmn = tostring(root, encoding="unicode")
    parsed_root = ElementTree.fromstring(bpmn)
    result = from_xml(parsed_root, state)

    assert isinstance(result, Success)
    assert result.unwrap().processes["Process_1"].name == "Test Participant"


def test_from_xml(mocker):
    mock_start_event_element = mocker.Mock()
    mock_start_event_element.attrib.get.return_value = "TestId"
    mock_msg_event_def = mocker.Mock()
    mock_msg_event_def.attrib.get.return_value = "test mock msg event def"
    mock_timer_event_def = mocker.Mock()
    mock_timer_event_def.attrib.get.return_value = None
    mock_start_event_element.find.side_effect = lambda x, _: {
        "bpmn:messageEventDefinition": mock_msg_event_def,
        "bpmn:timerEventDefinition": mock_timer_event_def,
    }.get(x)

    start_event = StartEvent.from_xml(mock_start_event_element)

    assert isinstance(start_event, StartEvent)
    assert start_event.message_event_definition == "test mock msg event def"
    assert start_event.message_timer_definition is None


RESOURCES = Path(__file__).parent.parent / "resources"

DOOR_STATE = """
enum Door {open closed}
enum Light {on off}

var door: Door = closed
var light: Light = off
var count: byte = 0
"""


def door_workflow(behavior, condition):
    """start -> task -> exclusive gateway -> end (flow carries the condition)"""
    root, collab = create_bpmn_definition()
    add_process(collab)
    start = Element("bpmn:startEvent", attrib={"id": "start", "name": "Start"})
    task = Element("bpmn:task", attrib={"id": "task", "name": "Task"})
    SubElement(task, "bpmn:documentation").text = behavior
    gateway = Element("bpmn:exclusiveGateway", attrib={"id": "gate", "name": "Gate"})
    end = Element("bpmn:endEvent", attrib={"id": "end", "name": "End"})
    flows = [
        Element(
            "bpmn:sequenceFlow",
            attrib={"id": "f1", "sourceRef": "start", "targetRef": "task"},
        ),
        Element(
            "bpmn:sequenceFlow",
            attrib={"id": "f2", "sourceRef": "task", "targetRef": "gate"},
        ),
        Element(
            "bpmn:sequenceFlow",
            attrib={
                "id": "f3",
                "name": condition,
                "sourceRef": "gate",
                "targetRef": "end",
            },
        ),
    ]
    add_process_with_elements(root, [start, task, gateway, end, *flows])
    return ElementTree.fromstring(tostring(root, encoding="unicode"))


def test_workflow_with_feel_holds_feel_trees():
    state = State.from_str(DOOR_STATE).unwrap()
    behavior = "((light, [], choose [on, off]),\n(count, [count], count + 1))"
    root = door_workflow(behavior, "door = open and count < 3")

    bpmn = from_xml(root, state).unwrap()

    process = bpmn.processes["Process_1"]
    task = process.all_items()["task"]
    assert isinstance(task.behavior_tree, TripleList)
    assert [t.target for t in task.behavior_tree.triples] == ["light", "count"]
    flow = process.get_flows()["f3"]
    assert flow.expression == "door = open and count < 3"
    assert flow.expression_tree == BinaryOp(
        "and",
        BinaryOp("=", Name("door"), Name("open")),
        BinaryOp("<", Name("count"), Number(3)),
    )


@pytest.mark.parametrize(
    "behavior, condition, error",
    [
        ("light off", "count < 3", FeelSyntaxError),
        ("light = off", "count < 3", FeelBehaviorTypeError),
        ("if\n:: true -> light = off\nfi", "count < 3", FeelUnsupportedError),
        ("(door, [], 1)", "count < 3", FeelAssignTypeError),
        ("(door, [], open)", "count == 3", FeelSyntaxError),
        ("(door, [], open)", "count < 3 && door = open", FeelSyntaxError),
        ("(door, [], open)", "count + 3", FeelConditionTypeError),
    ],
)
def test_workflow_not_in_feel_fails_to_load_with_feel_error(behavior, condition, error):
    state = State.from_str(DOOR_STATE).unwrap()

    result = from_xml(door_workflow(behavior, condition), state)

    assert isinstance(result, Failure)
    assert isinstance(result.failure(), error)


@pytest.mark.parametrize(
    "folder, bpmn_file",
    [
        ("face2face", "workflow.bpmn"),
        ("face2face", "face2face_open.bpmn"),
        ("phware", "workflow_good.bpmn"),
        ("simple_example", "simple_open.bpmn"),
    ],
)
def test_feel_fixture_loads_with_feel_trees(folder, bpmn_file):
    base = RESOURCES / "feel" / folder
    state = State.from_str((base / "state.txt").read_text()).unwrap()

    bpmn = from_xml(ElementTree.parse(base / bpmn_file).getroot(), state).unwrap()

    items = [i for p in bpmn.processes.values() for i in p.all_items().values()]
    flows = [f for p in bpmn.processes.values() for f in p.get_flows().values()]
    tasks = [i for i in items if isinstance(i, Task)]
    assert any(task.behavior_tree is not None for task in tasks)
    assert all(bool(t.behavior.strip()) == (t.behavior_tree is not None) for t in tasks)
    assert all(bool(f.expression) == (f.expression_tree is not None) for f in flows)


@pytest.mark.parametrize(
    "folder, bpmn_file",
    [
        ("face2face", "workflow.bpmn"),
        ("phware", "workflow.bpmn"),
        ("simple_example", "simple_open.bpmn"),
    ],
)
def test_old_format_fixture_fails_to_load_with_feel_error(folder, bpmn_file):
    base = RESOURCES / folder
    state = State.from_str((base / "state.txt").read_text()).unwrap()

    result = from_xml(ElementTree.parse(base / bpmn_file).getroot(), state)

    assert isinstance(result, Failure)
    assert isinstance(
        result.failure(),
        FeelSyntaxError | FeelUnsupportedError | FeelBehaviorTypeError,
    )


@pytest.mark.parametrize(
    "folder, bpmn_file, error",
    [
        ("phware", "workflow.bpmn", BpmnNoElementNameError),
        ("simple_example", "test_bpmn.bpmn", BpmnNoSwimLaneNameError),
    ],
)
def test_feel_copy_of_invalid_fixture_still_gives_its_bpmn_error(
    folder, bpmn_file, error
):
    base = RESOURCES / "feel" / folder
    state = State.from_str((base / "state.txt").read_text()).unwrap()

    result = from_xml(ElementTree.parse(base / bpmn_file).getroot(), state)

    assert isinstance(result, Failure)
    assert isinstance(result.failure(), error)
