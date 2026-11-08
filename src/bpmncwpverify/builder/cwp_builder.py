from returns.functions import not_
from returns.pipeline import is_successful
from returns.result import Failure, Result, Success

from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState
from bpmncwpverify.core.error import (
    CwpMultStartStateError,
    CwpNoEndStatesError,
    CwpNoParentEdgeError,
    CwpNoStartStateError,
    Error,
)
from bpmncwpverify.core.expr import ExpressionListener
from bpmncwpverify.core.state import State
from bpmncwpverify.visitors.cwp_connectivity_visitor import CwpConnectivityVisitor


class CwpBuilder:
    __slots__ = ["_cur_edge_letter", "_cwp"]

    def __init__(self) -> None:
        self._cur_edge_letter = "A"
        self._cwp = Cwp()

    def gen_edge_name(self) -> str:
        ret = "Edge" + self._cur_edge_letter
        self._cur_edge_letter = chr(ord(self._cur_edge_letter) + 1)
        return ret

    def build(self) -> Result[Cwp, Error]:
        try:
            end_states = [
                state
                for state in self._cwp.states.values()
                if not state.out_edges and state.in_edges
            ]

            if not end_states:
                return Failure(CwpNoEndStatesError())

            # This step ensures connectivity of the graph and sets leaf edges
            visitor = CwpConnectivityVisitor()
            self._cwp.accept(visitor)

            return Success(self._cwp)
        except Exception as e:
            return Failure(e.args[0])

    def with_edge(
        self, edge: CwpEdge, source_ref: str, target_ref: str
    ) -> "CwpBuilder":
        source = self._cwp.states[source_ref]
        source.out_edges.append(edge)
        edge.set_source(source)

        dest = self._cwp.states[target_ref]
        dest.in_edges.append(edge)
        edge.set_dest(dest)
        self._cwp.edges[edge.id] = edge
        return self

    def check_expression(
        self,
        expr_checker: ExpressionListener,
        expression: str,
        parent: str,
        state: State,
    ) -> None:
        edge = self._cwp.edges.get(parent)
        if not edge:
            raise Exception(CwpNoParentEdgeError(parent))
        edge.expression = CwpEdge.cleanup_expression(expression)
        result = expr_checker.type_check(edge.expression, state)
        if not_(is_successful)(result):
            raise Exception(result.failure())

    def with_state(self, cwpState: CwpState) -> "CwpBuilder":
        self._cwp.states[cwpState.id] = cwpState
        return self

    def find_start_state(self) -> "CwpBuilder":
        found: bool = False
        start_states: list[CwpState] = []

        for cwpState in self._cwp.states.values():
            if not cwpState.in_edges and cwpState.out_edges:
                if found:
                    start_states.append(cwpState)
                self._cwp.start_state = cwpState
                self._cwp.start_state.init_state = True
                found = True

        if not found:
            raise Exception(CwpNoStartStateError())
        elif start_states:
            raise Exception(
                CwpMultStartStateError([state.id for state in start_states])
            )
        return self

    def with_start_edge(self, edge: CwpEdge) -> "CwpBuilder":
        dest = self._cwp.states[self._cwp.start_state.id]
        dest.in_edges.append(edge)
        edge.set_dest(dest)
        self._cwp.edges[edge.id] = edge
        return self
