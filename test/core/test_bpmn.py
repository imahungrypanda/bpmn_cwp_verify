# type: ignore
from xml.etree.ElementTree import Element, SubElement, tostring

from defusedxml import ElementTree
from returns.result import Failure, Success

from bpmncwpverify.core.accessmethods.bpmnmethods import from_xml
from bpmncwpverify.core.bpmn import BPMN_XML_NAMESPACE, StartEvent
from bpmncwpverify.core.error import BpmnMissingEventsError
from bpmncwpverify.core.state import StateBuilder


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
