# type: ignore
import pytest

from bpmncwpverify.core.error import (
    BpmnMsgFlowSamePoolError,
    BpmnNoElementNameError,
    BpmnNoSwimLaneNameError,
)
from bpmncwpverify.visitors.bpmnchecks.bpmnvalidate import validate_bpmn


@pytest.fixture
def setup_bpmn(mocker):
    """Fixture to set up a mock BPMN object."""
    bpmn = mocker.MagicMock()

    process1 = mocker.MagicMock()
    process1.accept = mocker.MagicMock()
    process1.all_items.return_value = ["node1", "node2"]
    process2 = mocker.MagicMock()
    process2.accept = mocker.MagicMock()
    process2.all_items.return_value = ["node3", "node4"]

    bpmn.processes = {"process1": process1, "process2": process2}

    bpmn.id_to_element = {}

    msg1 = mocker.MagicMock()
    msg1.id = "msg1"
    msg1.source_node.id = "node1"
    msg1.target_node.id = "node3"

    msg2 = mocker.MagicMock()
    msg2.id = "msg2"
    msg2.source_node.id = "node2"
    msg2.target_node.id = "node4"

    bpmn.inter_process_msgs = {"msg1": msg1, "msg2": msg2}

    return bpmn


def test_validate_bpmn_no_error(mocker, setup_bpmn):
    bpmn = setup_bpmn

    validate_bpmn(bpmn)


def test_validate_bpmn_msg_same_pool_error(mocker, setup_bpmn):
    bpmn = setup_bpmn

    bpmn.inter_process_msgs["msg2"].target_node.id = "node1"  # Same pool as target_node

    result = validate_bpmn(bpmn)

    # Check the exception type and message
    assert isinstance(result.failure(), BpmnMsgFlowSamePoolError)
    assert result.failure().msg_id == "msg2"


def test_validate_bpmn_no_name_error(mocker, setup_bpmn):
    bpmn = setup_bpmn

    mock_element = mocker.MagicMock()
    mock_element.id = "Event_id"
    mock_element.name = "Event_id"

    bpmn.id_to_element["Event_id"] = mock_element

    result = validate_bpmn(bpmn)

    assert isinstance(result.failure(), BpmnNoElementNameError)


def test_validate_bpmn_no_swimlane_error(mocker, setup_bpmn):
    bpmn = setup_bpmn
    bpmn.processes["process1"].name = "Process1"
    bpmn.processes["process1"].id = "Process1"

    result = validate_bpmn(bpmn)

    assert isinstance(result.failure(), BpmnNoSwimLaneNameError)
