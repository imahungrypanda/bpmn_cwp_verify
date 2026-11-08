from returns.result import Result

from bpmncwpverify.core.bpmn import Bpmn, MessageFlow, Node, Process
from bpmncwpverify.core.error import (
    Error,
)
from bpmncwpverify.visitors.bpmnchecks.bpmnvalidate import validate_bpmn


class BpmnBuilder:
    __slots__ = "_bpmn"

    def __init__(self) -> None:
        self._bpmn = Bpmn()

    def build(self) -> Result[Bpmn, Error]:
        result: Result[Bpmn, Error] = validate_bpmn(self._bpmn)
        return result

    def with_process(self, process: Process) -> "BpmnBuilder":
        self._bpmn.processes[process.id] = process
        return self

    def with_message(
        self, message: MessageFlow, source_ref: str, target_ref: str
    ) -> "BpmnBuilder":
        self._bpmn.add_inter_process_msg(message)
        self._bpmn.store_element(message)

        from_node, to_node = (
            self._bpmn.get_element_from_id_mapping(source_ref),
            self._bpmn.get_element_from_id_mapping(target_ref),
        )

        assert isinstance(from_node, Node) and isinstance(to_node, Node)

        message.target_node, message.source_node = to_node, from_node
        from_node.add_out_msg(message)
        to_node.add_in_msg(message)
        return self

    def with_process_elements(self) -> "BpmnBuilder":
        """
        Ensures that all elements from every process are accessible at the BPMN level.
        This allows inter-process elements to be linked via message flows.
        """
        for process in self._bpmn.processes.values():
            for item in list(process.all_items().values()) + list(
                process.get_flows().values()
            ):
                self._bpmn.store_element(item)
        return self
