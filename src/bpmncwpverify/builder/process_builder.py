from returns.functions import not_
from returns.pipeline import is_successful
from returns.result import Failure, Result, Success

from bpmncwpverify.core.bpmn import Node, Process, SequenceFlow, Task
from bpmncwpverify.core.error import Error
from bpmncwpverify.core.feel import parse, type_check_behavior, type_check_condition
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
            parsed = parse(expression)
            if not_(is_successful)(parsed):
                return Failure(parsed.failure())
            tree = parsed.unwrap()
            checked = type_check_condition(tree, self._state)
            if not_(is_successful)(checked):
                return Failure(checked.failure())
            flow.expression = expression
            flow.expression_tree = tree

        flow.source_node = source_node
        flow.target_node = target_node

        source_node.add_out_flow(flow)
        target_node.add_in_flow(flow)
        return Success(self)

    def _with_behaviors(self) -> Result["ProcessBuilder", Error]:
        """Parses and type checks the FEEL behavior of every task."""
        for item in self._process.all_items().values():
            if not isinstance(item, Task) or not item.behavior.strip():
                continue
            parsed = parse(item.behavior)
            if not_(is_successful)(parsed):
                return Failure(parsed.failure())
            tree = parsed.unwrap()
            checked = type_check_behavior(tree, self._state)
            if not_(is_successful)(checked):
                return Failure(checked.failure())
            item.behavior_tree = tree
        return Success(self)

    def build(self) -> Result[Process, Error]:
        behaviors = self._with_behaviors()
        if not_(is_successful)(behaviors):
            return Failure(behaviors.failure())
        return validate_process(self._process)
