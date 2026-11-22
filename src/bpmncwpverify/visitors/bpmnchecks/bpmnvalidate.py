from returns.pipeline import flow
from returns.pointfree import bind_result
from returns.result import Failure, Result, Success

from bpmncwpverify.core.bpmn import Bpmn, MessageFlow, Process, SequenceFlow
from bpmncwpverify.core.error import (
    BpmnMsgFlowSamePoolError,
    BpmnNoElementNameError,
    BpmnNoSwimLaneNameError,
    Error,
)
from bpmncwpverify.visitors.bpmnchecks.bpmnvalidations import (
    validate_start_end_events,
)
from bpmncwpverify.visitors.bpmnchecks.checkmethods import (
    check_connectivity,
    set_leaf_flows,
    validate_bpmn_ids,
    validate_bpmn_incoming_flows,
    validate_bpmn_outgoing_flows,
    validate_msgs,
    validate_seq_flows,
    validate_start_event_flows,
)


def validate_bpmn(bpmn: Bpmn) -> Result[Bpmn, Error]:
    return flow(
        bpmn,
        validate_msg_flow_pool,
        bind_result(validate_process_names),
        bind_result(validate_element_names),
    )


def validate_msg_flow_pool(bpmn: Bpmn) -> Result[Bpmn, Error]:
    for msg in bpmn.inter_process_msgs.values():
        for process in bpmn.processes.values():
            if (
                msg.target_node.id in process.all_items()
                and msg.source_node.id in process.all_items()
            ):
                return Failure(BpmnMsgFlowSamePoolError(msg.id))

    return Success(bpmn)


def validate_process_names(bpmn: Bpmn) -> Result[Bpmn, Error]:
    no_name_ids: list[str] = []
    for id in bpmn.processes.values():
        process_name = id.name
        process_id = id.id

        if process_name == process_id:
            no_name_ids.append(process_id)

    if no_name_ids:
        return Failure(BpmnNoSwimLaneNameError(no_name_ids))

    return Success(bpmn)


def validate_element_names(bpmn: Bpmn) -> Result[Bpmn, Error]:
    no_name_ids: list[str] = []
    for id in bpmn.id_to_element.values():
        element_name = id.name
        element_id = id.id

        if element_name == element_id and not (
            isinstance(id, SequenceFlow) or isinstance(id, MessageFlow)
        ):
            no_name_ids.append(element_id)

    if no_name_ids:
        return Failure(BpmnNoElementNameError(no_name_ids))

    return Success(bpmn)


def validate_process(process: Process) -> Result[Process, Error]:
    result: Result[Process, Error] = flow(
        process,
        validate_start_end_events,
        bind_result(set_leaf_flows),
        bind_result(check_connectivity),
        bind_result(validate_msgs),
        bind_result(validate_seq_flows),
        bind_result(validate_bpmn_incoming_flows),
        bind_result(validate_bpmn_outgoing_flows),
        bind_result(validate_start_event_flows),
        bind_result(validate_bpmn_ids),
    )
    return result
