import graphviz

from bpmncwpverify.core.bpmn import (
    Bpmn,
    BpmnVisitor,
    EndEvent,
    ExclusiveGatewayNode,
    IntermediateEvent,
    MessageFlow,
    ParallelGatewayNode,
    SequenceFlow,
    StartEvent,
    Task,
)


def dot_node(graph: graphviz.Digraph, id: str, name: str) -> None:
    graph.node(id, name)  # type: ignore[unused-ignore]


def dot_edge(graph: graphviz.Digraph, src: str, dst: str, label: str) -> None:
    graph.edge(src, dst, label=label)  # type: ignore[unused-ignore]


class GraphVizVisitor(BpmnVisitor):
    __slots__ = "dot"

    def __init__(self, process_number: int) -> None:
        self.dot = graphviz.Digraph(comment=f"Process graph {process_number}")

    def visit_start_event(self, event: StartEvent) -> bool:
        dot_node(self.dot, event.id, event.name)
        return True

    def visit_end_event(self, event: EndEvent) -> bool:
        dot_node(self.dot, event.id, event.name)
        return True

    def visit_intermediate_event(self, event: IntermediateEvent) -> bool:
        dot_node(self.dot, event.id, event.name)
        return True

    def visit_task(self, task: Task) -> bool:
        dot_node(self.dot, task.id, task.name)
        return True

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        dot_node(self.dot, gateway.id, gateway.name)
        return True

    def visit_parallel_gateway(self, gateway: ParallelGatewayNode) -> bool:
        dot_node(self.dot, gateway.id, gateway.name)
        return True

    def end_visit_sequence_flow(self, flow: SequenceFlow) -> None:
        dot_edge(self.dot, flow.source_node.id, flow.target_node.id, flow.name)

    def end_visit_message_flow(self, flow: MessageFlow) -> None:
        dot_edge(self.dot, flow.source_node.id, flow.target_node.id, flow.name)

    def end_visit_bpmn(self, bpmn: Bpmn) -> None:
        for _msg_id, msg_flow in bpmn.inter_process_msgs.items():
            self.dot.edge(  # type: ignore[unused-ignore]
                msg_flow.source_node.id, msg_flow.target_node.id, label="message_flow"
            )
