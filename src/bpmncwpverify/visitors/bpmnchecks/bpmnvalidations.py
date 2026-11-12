import re

from returns.result import Failure, Result, Success

from bpmncwpverify.core.bpmn import (
    BpmnElement,
    BpmnVisitor,
    EndEvent,
    Event,
    ExclusiveGatewayNode,
    Flow,
    GatewayNode,
    IntermediateEvent,
    MessageFlow,
    Node,
    ParallelGatewayNode,
    Process,
    SequenceFlow,
    StartEvent,
    Task,
)
from bpmncwpverify.core.error import (
    BpmnFlowIncomingError,
    BpmnFlowOutgoingError,
    BpmnFlowStartEventError,
    BpmnGraphConnError,
    BpmnInvalidIdError,
    BpmnMissingEventsError,
    BpmnMsgEndEventError,
    BpmnMsgGatewayError,
    BpmnMsgSrcError,
    BpmnMsgStartEventError,
    BpmnMsgTargetError,
    BpmnSeqFlowEndEventError,
    BpmnSeqFlowNoExprError,
    BpmnTaskFlowError,
    Error,
)


class ProcessConnectivityVisitor(BpmnVisitor):
    __slots__ = "visited"

    def __init__(self) -> None:
        self.visited: set[BpmnElement] = set()

    def visit_start_event(self, event: StartEvent) -> bool:
        self.visited.add(event)
        return True

    def visit_end_event(self, event: EndEvent) -> bool:
        self.visited.add(event)
        return True

    def visit_intermediate_event(self, event: IntermediateEvent) -> bool:
        self.visited.add(event)
        return True

    def visit_task(self, task: Task) -> bool:
        self.visited.add(task)
        return True

    def visit_boundary_event(self, boundary_event: Task.BoundaryEvent) -> bool:
        self.visited.add(boundary_event)
        return True

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        self.visited.add(gateway)
        return True

    def visit_parallel_gateway(self, gateway: ParallelGatewayNode) -> bool:
        self.visited.add(gateway)
        return True

    def end_visit_process(self, process: Process) -> None:
        # Ensure all items in the process graph are visited
        if set(process.all_items().values()) != self.visited:
            raise Exception(BpmnGraphConnError())


class ValidateSeqFlowVisitor(BpmnVisitor):
    def _validate_out_flows(self, gateway: GatewayNode) -> None:
        for out_flow in gateway.out_flows:
            if not out_flow.expression:
                raise Exception(BpmnSeqFlowNoExprError(gateway.id, out_flow.id))

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        self._validate_out_flows(gateway)
        return True

    def visit_task(self, task: Task) -> bool:
        if not (task.in_flows and task.out_flows):
            raise Exception(BpmnTaskFlowError(task.id))
        return True

    def visit_end_event(self, event: EndEvent) -> bool:
        if event.out_flows:
            raise Exception(BpmnSeqFlowEndEventError(event.id))
        return True


class ValidateMsgsVisitor(BpmnVisitor):
    def _ensure_in_messages(self, node: Event, obj_type: str) -> None:
        if node.in_msgs:
            if not node.message_event_definition:
                raise Exception(BpmnMsgTargetError(obj_type, node.id))

    def _ensure_out_messages(self, node: Event, obj_type: str) -> None:
        if node.out_msgs:
            if not node.message_event_definition:
                raise Exception(BpmnMsgSrcError(obj_type, node.id))

    def visit_start_event(self, event: StartEvent) -> bool:
        self._ensure_in_messages(event, "start event")
        return True

    def visit_end_event(self, event: EndEvent) -> bool:
        if event.in_msgs:
            raise Exception(BpmnMsgEndEventError(event.id))
        self._ensure_out_messages(event, "end event")
        return True

    def _validate_gateway_no_msgs(
        self, gateway: GatewayNode, gateway_type: str
    ) -> bool:
        if gateway.in_msgs or gateway.out_msgs:
            raise Exception(BpmnMsgGatewayError(gateway_type, gateway.id))
        return True

    def visit_parallel_gateway(self, gateway: ParallelGatewayNode) -> bool:
        return self._validate_gateway_no_msgs(gateway, "ParallelGatewayNode")

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        return self._validate_gateway_no_msgs(gateway, "ExclusiveGatewayNode")

    def visit_intermediate_event(self, event: IntermediateEvent) -> bool:
        self._ensure_in_messages(event, "intermediate event")
        self._ensure_out_messages(event, "intermediate event")
        return True


class ValidateBpmnIncomingFlows(BpmnVisitor):
    def _check_in_flows(self, element: Node) -> bool:
        if not element.in_flows:
            raise Exception(BpmnFlowIncomingError(element.id))
        return True

    def visit_end_event(self, event: EndEvent) -> bool:
        return self._check_in_flows(event)

    def visit_intermediate_event(self, event: IntermediateEvent) -> bool:
        return self._check_in_flows(event)

    def visit_task(self, task: Task) -> bool:
        return self._check_in_flows(task)

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        return self._check_in_flows(gateway)

    def visit_parallel_gateway(self, gateway: ParallelGatewayNode) -> bool:
        return self._check_in_flows(gateway)


class ValidateBpmnOutgoingFlows(BpmnVisitor):
    def _check_out_flows(self, element: Node) -> bool:
        if not element.out_flows:
            raise Exception(BpmnFlowOutgoingError(element.id))
        return True

    def visit_start_event(self, event: StartEvent) -> bool:
        return self._check_out_flows(event)

    def visit_intermediate_event(self, event: IntermediateEvent) -> bool:
        return self._check_out_flows(event)

    def visit_task(self, task: Task) -> bool:
        return self._check_out_flows(task)

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        return self._check_out_flows(gateway)

    def visit_parallel_gateway(self, gateway: ParallelGatewayNode) -> bool:
        return self._check_out_flows(gateway)


class ValidateStartEventFlows(BpmnVisitor):
    def visit_start_event(self, event: StartEvent) -> bool:
        if event.in_flows:
            raise Exception(BpmnFlowStartEventError(event.id))
        if event.out_msgs:
            raise Exception(BpmnFlowStartEventError(event.id))
        if event.in_msgs and not event.message_event_definition:
            raise Exception(BpmnMsgStartEventError(event.id))
        return False


class SetFlowLeafs(BpmnVisitor):
    __slots__ = "visited"

    def __init__(self) -> None:
        self.visited: set[BpmnElement] = set()

    def visit_start_event(self, event: StartEvent) -> bool:
        self.visited.add(event)
        return True

    def visit_end_event(self, event: EndEvent) -> bool:
        self.visited.add(event)
        return True

    def visit_intermediate_event(self, event: IntermediateEvent) -> bool:
        self.visited.add(event)
        return True

    def visit_task(self, task: Task) -> bool:
        self.visited.add(task)
        return True

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        self.visited.add(gateway)
        return True

    def visit_parallel_gateway(self, gateway: ParallelGatewayNode) -> bool:
        self.visited.add(gateway)
        return True

    def process_flow(self, flow: Flow) -> bool:
        if flow.target_node in self.visited:
            flow.is_leaf = True
            return False
        return True

    def visit_sequence_flow(self, flow: SequenceFlow) -> bool:
        return self.process_flow(flow)


class ValidateIdVisitor(BpmnVisitor):
    def _is_id_valid(self, item: BpmnElement) -> bool:
        return bool(re.fullmatch(r"[\w_-]+", item.id))

    def visit_start_event(self, event: StartEvent) -> bool:
        if not self._is_id_valid(event):
            raise Exception(BpmnInvalidIdError(event.id))
        return True

    def visit_process(self, process: Process) -> bool:
        if not self._is_id_valid(process):
            raise Exception(BpmnInvalidIdError(process.id))
        return True

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        if not self._is_id_valid(gateway):
            raise Exception(BpmnInvalidIdError(gateway.id))
        return True

    def visit_intermediate_event(self, event: IntermediateEvent) -> bool:
        if not self._is_id_valid(event):
            raise Exception(BpmnInvalidIdError(event.id))
        return True

    def visit_parallel_gateway(self, gateway: ParallelGatewayNode) -> bool:
        if not self._is_id_valid(gateway):
            raise Exception(BpmnInvalidIdError(gateway.id))
        return True

    def visit_sequence_flow(self, flow: SequenceFlow) -> bool:
        if not self._is_id_valid(flow):
            raise Exception(BpmnInvalidIdError(flow.id))
        return True

    def visit_task(self, task: Task) -> bool:
        if not self._is_id_valid(task):
            raise Exception(BpmnInvalidIdError(task.id))
        return True

    def visit_message_flow(self, flow: MessageFlow) -> bool:
        if not self._is_id_valid(flow):
            raise Exception(BpmnInvalidIdError(flow.id))
        return True

    def visit_end_event(self, event: EndEvent) -> bool:
        if not self._is_id_valid(event):
            raise Exception(BpmnInvalidIdError(event.id))
        return True


##########################
# validation functions
##########################
def validate_start_end_events(process: Process) -> Result[Process, Error]:
    start_events = sum(
        isinstance(itm, StartEvent) for itm in process.all_items().values()
    )
    end_events = sum(isinstance(itm, EndEvent) for itm in process.all_items().values())

    # Determine if there is a valid starting point
    starting_point = start_events > 0 or any(
        itm.in_msgs for itm in process.all_items().values()
    )

    if not starting_point or end_events == 0:
        return Failure(BpmnMissingEventsError(start_events, end_events))

    return Success(process)
