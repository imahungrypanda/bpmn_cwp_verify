# type: ignore
from xml.etree.ElementTree import fromstring

import pytest

from bpmncwpverify.builder.cbmc_bound import calculate_cbmc_bound
from bpmncwpverify.core.accessmethods import bpmnmethods
from bpmncwpverify.core.bpmn import (
    Bpmn,
    EndEvent,
    ExclusiveGatewayNode,
    ParallelGatewayNode,
    Process,
    SequenceFlow,
    StartEvent,
    Task,
)
from bpmncwpverify.core.state import State

FACE2FACE = "test/resources/face2face/"


class Graph:
    """
    Builds a one process Bpmn from node names and edges
    """

    def __init__(self):
        self.bpmn = Bpmn()
        self.process = Process("p", "p")
        self.bpmn.processes["p"] = self.process
        self.nodes = {}

    def start(self, name="s"):
        return self._add(StartEvent(name, name, "", ""))

    def end(self, name):
        return self._add(EndEvent(name, name, "", ""))

    def task(self, name):
        return self._add(Task(name, name, ""))

    def xor(self, name):
        return self._add(ExclusiveGatewayNode(name, name))

    def par(self, name):
        return self._add(ParallelGatewayNode(name, name))

    def _add(self, node):
        self.nodes[node.id] = node
        self.process[node.id] = node
        return node.id

    def chain(self, *names):
        for source, target in zip(names, names[1:]):
            self.edge(source, target)
        return self

    def edge(self, source, target):
        flow = SequenceFlow(f"{source}_{target}", "")
        flow.source_node = self.nodes[source]
        flow.target_node = self.nodes[target]
        self.nodes[source].add_out_flow(flow)
        self.nodes[target].add_in_flow(flow)
        self.process[flow.id] = flow
        return self


def test_empty_bpmn_has_no_steps():
    # nothing can fire, so no passes are needed
    assert calculate_cbmc_bound(Bpmn()) == 0


def test_straight_line():
    g = Graph()
    for n in ("s", "a", "b"):
        g.start() if n == "s" else g.task(n)
    g.end("e")
    g.chain("s", "a", "b", "e")
    # start, two tasks, end: one pass each
    assert calculate_cbmc_bound(g.bpmn) == 4


def test_start_straight_to_end():
    g = Graph()
    g.start()
    g.end("e")
    g.chain("s", "e")
    assert calculate_cbmc_bound(g.bpmn) == 2


def test_exclusive_gateway_takes_longest_branch():
    g = Graph()
    g.start()
    g.xor("x")
    for n in ("a", "b", "c"):
        g.task(n)
    g.end("e")
    g.chain("s", "x")
    g.chain("x", "a", "e")
    g.chain("x", "b", "c", "e")
    # s, x, then the longer branch b, c, then e: 5. Branch a is not added
    assert calculate_cbmc_bound(g.bpmn) == 5


def test_parallel_branches_add_and_join_counts_once():
    g = Graph()
    g.start()
    g.par("fork")
    g.par("join")
    for n in ("a", "b", "c", "d"):
        g.task(n)
    g.end("e")
    g.chain("s", "fork")
    g.chain("fork", "a", "join")
    g.chain("fork", "b", "c", "join")
    g.chain("join", "d", "e")
    # s + fork + (a = 1) + (b, c = 2) + join + d + e = 8
    assert calculate_cbmc_bound(g.bpmn) == 8


def test_parallel_branch_with_exclusive_gateway_inside():
    g = Graph()
    g.start()
    g.par("fork")
    g.par("join")
    g.xor("x")
    for n in ("a", "b", "c", "d"):
        g.task(n)
    g.end("e")
    g.chain("s", "fork")
    g.chain("fork", "a", "join")
    g.chain("fork", "x")
    g.chain("x", "b", "join")
    g.chain("x", "c", "d", "join")
    g.chain("join", "e")
    # branch 1 = a (1); branch 2 = x + longer c, d (3);
    # s + fork + 1 + 3 + join + e = 8
    assert calculate_cbmc_bound(g.bpmn) == 8


def test_nested_forks():
    g = Graph()
    g.start()
    for n in ("f1", "f2", "j1", "j2"):
        g.par(n)
    for n in ("a", "b", "c"):
        g.task(n)
    g.end("e")
    g.chain("s", "f1")
    g.chain("f1", "a", "j1")
    g.chain("f1", "f2")
    g.chain("f2", "b", "j2")
    g.chain("f2", "c", "j2")
    g.chain("j2", "j1")
    g.chain("j1", "e")
    # inner fork f2 + b + c + j2 = 4 in the second branch of f1; first branch = a.
    # s + f1 + 1 + 4 + j1 + e = 9
    assert calculate_cbmc_bound(g.bpmn) == 9


def test_fork_without_join_adds_branches():
    g = Graph()
    g.start()
    g.par("fork")
    g.end("e1")
    g.end("e2")
    g.task("a")
    g.chain("s", "fork")
    g.chain("fork", "a", "e1")
    g.chain("fork", "e2")
    # s + fork + (a, e1) + e2 = 5: every branch takes passes of its own
    assert calculate_cbmc_bound(g.bpmn) == 5


def test_simple_loop_adds_cycle_times_retries():
    g = Graph()
    g.start()
    g.xor("x")
    g.task("a")
    g.end("e")
    g.chain("s", "x", "a", "x")
    g.chain("x", "e")
    # without the loop: s, x, e = 3. The cycle x, a has 2 steps: 3 + 2 * 2 = 7
    assert calculate_cbmc_bound(g.bpmn) == 7


def test_loop_retries_parameter():
    g = Graph()
    g.start()
    g.xor("x")
    g.task("a")
    g.end("e")
    g.chain("s", "x", "a", "x")
    g.chain("x", "e")
    # 3 + 2 * retries
    assert calculate_cbmc_bound(g.bpmn, retries=0) == 3
    assert calculate_cbmc_bound(g.bpmn, retries=1) == 5
    assert calculate_cbmc_bound(g.bpmn, retries=5) == 13


def test_loop_uses_longest_cycle_through_the_node():
    g = Graph()
    g.start()
    g.xor("x")
    for n in ("a", "b", "c"):
        g.task(n)
    g.end("e")
    g.chain("s", "x")
    g.chain("x", "a", "x")
    g.chain("x", "b", "c", "x")
    g.chain("x", "e")
    # Longest path with the loops cut: s, x, b, c (c's edge back is a dead end) = 4.
    # Two cycles come back into x: x, a (2) and x, b, c (3).
    # Only the longest counts per node: 4 + 3 * 2 = 10
    assert calculate_cbmc_bound(g.bpmn) == 10


def test_loops_into_different_nodes_each_add():
    g = Graph()
    g.start()
    g.xor("x")
    g.xor("y")
    for n in ("a", "b"):
        g.task(n)
    g.end("e")
    g.chain("s", "x", "y")
    g.chain("y", "a", "x")
    g.chain("y", "b", "y")
    g.chain("y", "e")
    # s, x, y, e = 4. Into x: x, y, a = 3. Into y: y, b = 2.
    # 4 + (3 + 2) * 2 = 14
    assert calculate_cbmc_bound(g.bpmn) == 14


def test_self_edge_is_a_cycle_of_one():
    g = Graph()
    g.start()
    g.xor("x")
    g.end("e")
    g.chain("s", "x", "e")
    g.edge("x", "x")
    # s, x, e = 3, plus a cycle of just x: 3 + 1 * 2 = 5
    assert calculate_cbmc_bound(g.bpmn) == 5


def test_loop_through_parallel_fork_counts_one_path_of_the_cycle():
    g = Graph()
    g.start()
    g.par("fork")
    g.par("join")
    g.xor("x")
    for n in ("a", "b"):
        g.task(n)
    g.end("e")
    g.chain("s", "fork")
    g.chain("fork", "a", "join")
    g.chain("fork", "b", "join")
    g.chain("join", "x", "e")
    g.edge("x", "fork")
    # s, fork, a, b, join, x, e = 7. The cycle through fork is fork, a, join, x = 4
    # (the longest single path, as with a loop with no gateways): 7 + 4 * 2 = 15
    assert calculate_cbmc_bound(g.bpmn) == 15


def test_largest_start_event_wins():
    g = Graph()
    g.start("s1")
    g.start("s2")
    g.task("a")
    g.end("e")
    g.chain("s1", "e")
    g.chain("s2", "a", "e")
    # s1, e = 2 and s2, a, e = 3
    assert calculate_cbmc_bound(g.bpmn) == 3


def test_largest_process_wins():
    g = Graph()
    g.start()
    g.end("e")
    g.chain("s", "e")
    other = Process("q", "q")
    g.bpmn.processes["q"] = other
    start, task, end = (
        StartEvent("qs", "qs", "", ""),
        Task("qa", "qa", ""),
        EndEvent("qe", "qe", "", ""),
    )
    for node in (start, task, end):
        other[node.id] = node
    for source, target in ((start, task), (task, end)):
        flow = SequenceFlow(f"{source.id}_{target.id}", "")
        flow.source_node, flow.target_node = source, target
        source.add_out_flow(flow)
        target.add_in_flow(flow)
    # first process has 2 steps, second has 3
    assert calculate_cbmc_bound(g.bpmn) == 3


def test_boundary_event_is_another_way_out_of_its_task():
    g = Graph()
    g.start()
    g.task("a")
    g.end("e1")
    g.end("e2")
    g.task("handler")
    boundary = Task.BoundaryEvent("b", "b", "", "", "a")
    g.nodes["a"].add_boundary_event(boundary)
    g.nodes["b"] = boundary
    g.chain("s", "a", "e1")
    g.edge("b", "handler")
    g.chain("handler", "e2")
    # s, a, then either e1 (1) or the boundary event, handler, e2 (3): 2 + 3 = 5
    assert calculate_cbmc_bound(g.bpmn) == 5


@pytest.mark.parametrize("name", ["workflow", "face2face_open"])
def test_face2face(name):
    state = State.from_str(open(FACE2FACE + "state.txt").read()).unwrap()
    bpmn = bpmnmethods.from_xml(
        fromstring(open(FACE2FACE + name + ".bpmn").read()), state
    ).unwrap()
    # Without loops: start, task 1, fork, 2 tasks, join, exclusive gateway,
    # task 6, fork, 2 tasks, join, end = 13.
    # Loops: into the first fork, the cycle fork, task, join, exclusive
    # gateway is 4; into the exclusive gateway, the cycle with task 4 or 5 is 2.
    # 13 + (4 + 2) * 2 = 25
    assert calculate_cbmc_bound(bpmn) == 25
