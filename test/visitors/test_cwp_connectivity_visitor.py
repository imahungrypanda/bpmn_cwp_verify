# type: ignore
import pytest

from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState
from bpmncwpverify.core.error import CwpGraphConnError
from bpmncwpverify.visitors.cwp_connectivity_visitor import CwpConnectivityVisitor


@pytest.fixture
def states_and_edges():
    """
    s0 -> s1 -> s2 -> s3
    where s0 = start_state
    """
    states = []
    for id in range(4):
        node = CwpState(id=str(id), name=str(id))
        states.append(node)

    edges = []
    for id, node in enumerate(states):
        edge = CwpEdge(id=f"edge{id}", name=f"edge{id}")
        if id != len(states) - 1:
            edge.source = node
            edge.dest = states[id + 1]
            edges.append(edge)

    for id, edge in enumerate(edges):
        states[id].out_edges = [edge]

    start_state = states[0]
    edges = {edge.id: edge for edge in edges}
    states = {node.id: node for node in states}
    return start_state, edges, states


def test_cwp_connectivity_valid(states_and_edges):
    start_state, states, edges = states_and_edges
    visitor = CwpConnectivityVisitor()
    cwp = Cwp()
    cwp.start_state = start_state
    cwp.edges = states
    cwp.states = edges

    cwp.accept(visitor)


def test_cwp_connectivity_invalid(states_and_edges):
    start_state, states, edges = states_and_edges

    # This time, the start state doesn't have any edges, so the other states
    # won't be visited
    start_state.out_edges = []

    visitor = CwpConnectivityVisitor()
    cwp = Cwp()
    cwp.start_state = start_state
    cwp.edges = states
    cwp.states = edges

    with pytest.raises(Exception) as exc_info:
        cwp.accept(visitor)

    assert isinstance(exc_info.value.args[0], CwpGraphConnError)
