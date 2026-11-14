# type: ignore
from xml.etree.ElementTree import Element

import pytest

from bpmncwpverify.builder.bpmn_builder import BpmnBuilder
from bpmncwpverify.core.bpmn import Node


def test_add_message_valid_input(mocker):
    mock_bpmn = mocker.MagicMock()
    mock_source_node = mocker.MagicMock(spec=Node)
    mock_target_node = mocker.MagicMock(spec=Node)
    mock_msg_flow = mocker.MagicMock(spec=Element)

    mock_bpmn.get_element_from_id_mapping.side_effect = lambda x: {
        "source_id": mock_source_node,
        "target_id": mock_target_node,
    }[x]

    builder = BpmnBuilder()
    builder._bpmn = mock_bpmn

    builder.with_message(mock_msg_flow, "source_id", "target_id")

    mock_bpmn.add_inter_process_msg.assert_called_once()
    mock_bpmn.store_element.assert_called_once()
    assert mock_source_node.add_out_msg.called
    assert mock_target_node.add_in_msg.called


def test_add_message_missing_refs(mocker):
    mock_bpmn = mocker.MagicMock()
    mock_msg_flow = mocker.MagicMock(spec=Element)

    builder = BpmnBuilder()
    builder._bpmn = mock_bpmn

    with pytest.raises(Exception) as exc_info:
        builder.with_message(mock_msg_flow, None, "target_id")

    assert isinstance(exc_info.value, AssertionError)


def test_add_message_invalid_nodes(mocker):
    mock_bpmn = mocker.Mock()
    mock_msg_flow = mocker.MagicMock(spec=Element)
    mock_bpmn.get_element_from_id_mapping.side_effect = lambda x: {
        "source_id": "invalid_node",
        "target_id": "invalid_node",
    }[x]

    builder = BpmnBuilder()
    builder._bpmn = mock_bpmn

    with pytest.raises(Exception) as exc_info:
        builder.with_message(mock_msg_flow, "source_id", "target_id")

    assert isinstance(exc_info.value, AssertionError)


def test_check_messages_empty(mocker):
    mock_bpmn = mocker.MagicMock()

    mock_bpmn.inter_process_msgs.values.return_value = []

    mock_process = mocker.MagicMock()
    mock_process.all_items.return_value = []
    mock_bpmn.processes.values.return_value = [mock_process]

    obj = mocker.MagicMock()
    obj._bpmn = mock_bpmn

    obj._msg_connects_diff_pools()
