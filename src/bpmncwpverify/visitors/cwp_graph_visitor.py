import graphviz

from bpmncwpverify.core.cwp import CwpEdge, CwpState, CwpVisitor
from bpmncwpverify.visitors.bpmn_graph_visitor import dot_edge, dot_node


class CwpGraphVizVisitor(CwpVisitor):
    __slots__ = "dot"

    def __init__(self) -> None:
        self.dot = graphviz.Digraph(comment="cwp graph")

    def visit_state(self, state: CwpState) -> bool:
        dot_node(self.dot, state.name, state.name)
        return True

    def end_visit_state(self, state: CwpState) -> None:
        pass

    def visit_edge(self, edge: CwpEdge) -> bool:
        if edge.source:
            dot_edge(self.dot, edge.source.name, edge.dest.name, label=edge.expression)
        else:
            dot_edge(self.dot, "start", edge.dest.name, label=edge.expression)
        return True
