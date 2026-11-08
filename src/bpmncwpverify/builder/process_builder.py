from returns.functions import not_
from returns.pipeline import is_successful
from returns.result import Failure, Result, Success

from bpmncwpverify.core.bpmn import Node, Process, SequenceFlow, Task
from bpmncwpverify.core.error import Error, FlowExpressionError, get_error_message
from bpmncwpverify.core.expr import ExpressionListener
from bpmncwpverify.core.state import State
from bpmncwpverify.visitors.bpmnchecks.bpmnvalidate import validate_process


class ProcessBuilder:
    __slots__ = ["_process", "_state"]

    def __init__(self, id: str, name: str, state: State) -> None:
        self._process = Process(id, name)
        self._state = state

    def with_element(self, element: SequenceFlow | Node) -> "ProcessBuilder":
        self._process[element.id] = element
        return self

    def with_boundary_events(self) -> "ProcessBuilder":
        all_items = self._process.all_items()

        for bpmn_object in all_items.values():
            if isinstance(bpmn_object, Task.BoundaryEvent):
                parent_id = bpmn_object.parent_task
                assert parent_id in all_items, (
                    f"Boundary event '{bpmn_object.id}' references a missing parent task ID: {parent_id}"
                )

                parent_task = all_items[parent_id]
                assert isinstance(parent_task, Task), (
                    f"Boundary event '{bpmn_object.id}' is attached to non-Task object: {type(parent_task).__name__}"
                )

                parent_task.add_boundary_event(bpmn_object)

        return self

    def with_process_flow(
        self,
        flow_id: str,
        source_ref: str,
        target_ref: str,
        expression: str | None,
    ) -> Result["ProcessBuilder", Error]:
        flow = self._process[flow_id]
        source_node = self._process[source_ref]
        target_node = self._process[target_ref]

        assert isinstance(flow, SequenceFlow)
        assert isinstance(source_node, Node)
        assert isinstance(target_node, Node)

        if expression:
            result = ExpressionListener.type_check(expression, self._state)
            if not_(is_successful)(result):
                return Failure(
                    FlowExpressionError(
                        flow_id, expression, get_error_message(result.failure())
                    )
                )
            assert result.unwrap() == "bool", (
                f"Expected Expression type to be bool on flow: {flow_id}"
            )
            flow.expression = expression

        flow.source_node = source_node
        flow.target_node = target_node

        source_node.add_out_flow(flow)
        target_node.add_in_flow(flow)
        return Success(self)

    def build(self) -> Result[Process, Error]:
        return validate_process(self._process)
