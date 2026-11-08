from returns.result import Failure, Result, Success

from bpmncwpverify.core.bpmn import BpmnVisitor, Process
from bpmncwpverify.core.error import Error
from bpmncwpverify.visitors.bpmnchecks.bpmnvalidations import (
    ProcessConnectivityVisitor,
    SetFlowLeafs,
    ValidateBpmnIncomingFlows,
    ValidateBpmnOutgoingFlows,
    ValidateIdVisitor,
    ValidateMsgsVisitor,
    ValidateSeqFlowVisitor,
    ValidateStartEventFlows,
)


def validate_process_with_visitor(
    process: Process, visitor: BpmnVisitor
) -> Result[Process, Error]:
    try:
        process.accept(visitor)
        return Success(process)
    except Exception as e:
        return Failure(e.args[0])


def set_leaf_flows(process: Process) -> Result[Process, Error]:
    visitor = SetFlowLeafs()
    return validate_process_with_visitor(process, visitor)


def check_connectivity(process: Process) -> Result[Process, Error]:
    visitor = ProcessConnectivityVisitor()
    return validate_process_with_visitor(process, visitor)


def validate_msgs(process: Process) -> Result[Process, Error]:
    visitor = ValidateMsgsVisitor()
    return validate_process_with_visitor(process, visitor)


def validate_seq_flows(process: Process) -> Result[Process, Error]:
    visitor = ValidateSeqFlowVisitor()
    return validate_process_with_visitor(process, visitor)


def validate_bpmn_incoming_flows(process: Process) -> Result[Process, Error]:
    visitor = ValidateBpmnIncomingFlows()
    return validate_process_with_visitor(process, visitor)


def validate_bpmn_outgoing_flows(process: Process) -> Result[Process, Error]:
    visitor = ValidateBpmnOutgoingFlows()
    return validate_process_with_visitor(process, visitor)


def validate_start_event_flows(process: Process) -> Result[Process, Error]:
    visitor = ValidateStartEventFlows()
    return validate_process_with_visitor(process, visitor)


def validate_bpmn_ids(process: Process) -> Result[Process, Error]:
    visitor = ValidateIdVisitor()
    return validate_process_with_visitor(process, visitor)
