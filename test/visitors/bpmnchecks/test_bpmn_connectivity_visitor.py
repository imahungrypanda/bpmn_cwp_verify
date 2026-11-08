# type: ignore
import pytest

from bpmncwpverify.core.bpmn import Node
from bpmncwpverify.core.error import (
    BpmnMsgEndEventError,
    BpmnMsgGatewayError,
    BpmnMsgSrcError,
    BpmnMsgTargetError,
)
from bpmncwpverify.visitors.bpmnchecks.bpmnvalidations import ValidateMsgsVisitor


def test_ensure_in_and_out_messages(mocker):
    def setup_node(id, in_msgs=None, out_msgs=None, message_event_definition=""):
        node = mocker.Mock(spec=Node)
        node.id = id
        node.in_msgs = in_msgs or []
        node.out_msgs = out_msgs or []
        node.message_event_definition = message_event_definition
        return node

    visitor = ValidateMsgsVisitor()

    # Test ensure_in_messages - no message event definition
    test_node_in = setup_node("123", in_msgs=[1])
    with pytest.raises(
        Exception,
    ) as exc_info:
        visitor._ensure_in_messages(test_node_in, "event")
    assert isinstance(exc_info.value.args[0], BpmnMsgTargetError)
    assert "123" == str(exc_info.value.args[0].node_id)

    # Test ensure_in_messages - with message event definition
    test_node_in_def = setup_node(
        "123", in_msgs=[1], message_event_definition="test-id"
    )
    visitor._ensure_in_messages(test_node_in_def, "event")  # no error expected

    # Test ensure_out_messages - no message event definition
    test_node_out = setup_node("123", out_msgs=[1])
    with pytest.raises(
        Exception,
    ) as exc_info:
        visitor._ensure_out_messages(test_node_out, "event")
    assert isinstance(exc_info.value.args[0], BpmnMsgSrcError)
    assert "123" == str(exc_info.value.args[0].node_id)

    # Test ensure_out_messages - with message event definition
    test_node_out_def = setup_node(
        "123", out_msgs=[1], message_event_definition="test-id"
    )
    visitor._ensure_out_messages(test_node_out_def, "event")  # no error expected


def test_validate_gateway_no_msgs_no_messages(mocker):
    gateway = mocker.MagicMock()
    gateway.in_msgs = []
    gateway.out_msgs = []
    gateway.id = "gateway1"
    obj = ValidateMsgsVisitor()

    result = obj._validate_gateway_no_msgs(gateway, "TestGateway")

    assert result is True


def test_validate_gateway_no_msgs_with_incoming_messages(mocker):
    gateway = mocker.MagicMock()
    gateway.in_msgs = ["msg1"]
    gateway.out_msgs = []
    gateway.id = "gateway2"
    obj = ValidateMsgsVisitor()

    with pytest.raises(Exception) as exc_info:
        obj._validate_gateway_no_msgs(gateway, "TestGateway")

    assert isinstance(exc_info.value.args[0], BpmnMsgGatewayError)
    assert exc_info.value.args[0].gateway_id == "gateway2"
    assert exc_info.value.args[0].gateway_type == "TestGateway"


def test_validate_gateway_no_msgs_with_outgoing_messages(mocker):
    gateway = mocker.MagicMock()
    gateway.in_msgs = []
    gateway.out_msgs = ["msg1"]
    gateway.id = "gateway3"
    obj = ValidateMsgsVisitor()

    with pytest.raises(Exception) as exc_info:
        obj._validate_gateway_no_msgs(gateway, "TestGateway")

    assert isinstance(exc_info.value.args[0], BpmnMsgGatewayError)
    assert exc_info.value.args[0].gateway_id == "gateway3"
    assert exc_info.value.args[0].gateway_type == "TestGateway"


def test_validate_gateway_no_msgs_with_both_messages(mocker):
    gateway = mocker.MagicMock()
    gateway.in_msgs = ["msg1"]
    gateway.out_msgs = ["msg2"]
    gateway.id = "gateway4"
    obj = ValidateMsgsVisitor()

    with pytest.raises(Exception) as exc_info:
        obj._validate_gateway_no_msgs(gateway, "TestGateway")

    assert isinstance(exc_info.value.args[0], BpmnMsgGatewayError)
    assert exc_info.value.args[0].gateway_id == "gateway4"
    assert exc_info.value.args[0].gateway_type == "TestGateway"


def test_visit_end_event_no_incoming_messages(mocker):
    event = mocker.MagicMock()
    event.in_msgs = []
    event.id = "end_event_1"

    obj = ValidateMsgsVisitor()
    obj._ensure_out_messages = mocker.MagicMock(return_value=None)

    result = obj.visit_end_event(event)

    obj._ensure_out_messages.assert_called_once_with(event, "end event")  # type: ignore
    assert result is True


def test_visit_end_event_with_incoming_messages(mocker):
    event = mocker.MagicMock()
    event.in_msgs = ["msg1"]
    event.id = "end_event_2"

    obj = ValidateMsgsVisitor()
    obj._ensure_out_messages = mocker.MagicMock()

    with pytest.raises(Exception) as exc_info:
        obj.visit_end_event(event)

    assert isinstance(exc_info.value.args[0], BpmnMsgEndEventError)
    assert exc_info.value.args[0].event_id == "end_event_2"
    obj._ensure_out_messages.assert_not_called()  # type: ignore
