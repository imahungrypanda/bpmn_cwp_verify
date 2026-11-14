from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState, CwpVisitor
from bpmncwpverify.core.error import CwpGraphConnError


class CwpConnectivityVisitor(CwpVisitor):
    __slots__ = "visited"

    def __init__(self) -> None:
        self.visited: set[CwpState] = set()

    def visit_state(self, state: CwpState) -> bool:
        self.visited.add(state)
        return True

    def visit_edge(self, edge: CwpEdge) -> bool:
        # This determines if an edge is a leaf node
        if edge.dest in self.visited:
            edge.is_leaf = True
            return False
        return True

    def end_visit_cwp(self, model: Cwp) -> None:
        # This checks to see if any part of the graph is not connected
        if self.visited != set(model.states.values()) | {model.start_state}:
            raise Exception(CwpGraphConnError())
