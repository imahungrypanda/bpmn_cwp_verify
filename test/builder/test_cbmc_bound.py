from xml.etree.ElementTree import parse

import pytest

from bpmncwpverify.builder.cbmc_bound import get_unwinding_bound
from bpmncwpverify.core.accessmethods import bpmnmethods
from bpmncwpverify.core.bpmn import (
    Bpmn,
    EndEvent,
    ExclusiveGatewayNode,
    Node,
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
    Small helper that wires nodes into a process, one process per Graph
    """

    def __init__(self, pid: str = "p") -> None:
        self.process = Process(pid, pid)
        self._count = 0

    def start(self, id: str) -> Node:
        return self._add(StartEvent(id, id, "", ""))

    def end(self, id: str) -> Node:
        return self._add(EndEvent(id, id, "", ""))

    def task(self, id: str) -> Node:
        return self._add(Task(id, id, ""))

    def xor(self, id: str) -> Node:
        return self._add(ExclusiveGatewayNode(id, id))

    def par(self, id: str) -> Node:
        return self._add(ParallelGatewayNode(id, id))

    def _add(self, node: Node) -> Node:
        self.process[node.id] = node
        return node

    def chain(self, *nodes: Node) -> None:
        for source, target in zip(nodes, nodes[1:]):
            self._count += 1
            flow = SequenceFlow(f"f{self._count}", "")
            flow.source_node, flow.target_node = source, target
            source.add_out_flow(flow)
            target.add_in_flow(flow)
            self.process[flow.id] = flow


def bound_of(*graphs: Graph, **kwargs: int) -> int:
    bpmn = Bpmn()
    for g in graphs:
        bpmn.processes[g.process.id] = g.process
    return get_unwinding_bound(bpmn, **kwargs)


def test_straight_line():
    # start, a, b, end: four nodes, one step each
    g = Graph()
    s, a, b, e = g.start("s"), g.task("a"), g.task("b"), g.end("e")
    g.chain(s, a, b, e)
    assert bound_of(g) == 4


def test_exclusive_gateway_takes_longest_branch():
    # s, x, then the long branch a, b, then m, e: 6. The short branch is 5 steps
    g = Graph()
    s, x, a, b, c = g.start("s"), g.xor("x"), g.task("a"), g.task("b"), g.task("c")
    m, e = g.xor("m"), g.end("e")
    g.chain(s, x, a, b, m)
    g.chain(x, c, m)
    g.chain(m, e)
    assert bound_of(g) == 6


def test_parallel_branches_are_added_and_tail_counted_once():
    # s, fork, (a, b) + (c), join, d, e: 1 + 1 + 3 + 1 + 1 + 1 = 8
    g = Graph()
    s, f, a, b, c = g.start("s"), g.par("f"), g.task("a"), g.task("b"), g.task("c")
    j, d, e = g.par("j"), g.task("d"), g.end("e")
    g.chain(s, f, a, b, j)
    g.chain(f, c, j)
    g.chain(j, d, e)
    assert bound_of(g) == 8


def test_parallel_branches_without_a_join_are_all_counted():
    # s, fork, then a, e1 and b, c, e2 run on their own: 1 + 1 + 2 + 3 = 7
    g = Graph()
    s, f = g.start("s"), g.par("f")
    a, e1, b, c, e2 = g.task("a"), g.end("e1"), g.task("b"), g.task("c"), g.end("e2")
    g.chain(s, f, a, e1)
    g.chain(f, b, c, e2)
    assert bound_of(g) == 7


def test_loop_adds_cycle_times_retries():
    # s, a, x, b, e is 5 steps. The loop x -> a -> x is a cycle of 2 (a and x),
    # taken 2 times by default: 5 + 2 * 2
    g = Graph()
    s, a, x, b, e = g.start("s"), g.task("a"), g.xor("x"), g.task("b"), g.end("e")
    g.chain(s, a, x, b, e)
    g.chain(x, a)
    assert bound_of(g) == 9


def test_loop_retries_parameter():
    # Same graph as above, with 5 retries: 5 + 2 * 5
    g = Graph()
    s, a, x, b, e = g.start("s"), g.task("a"), g.xor("x"), g.task("b"), g.end("e")
    g.chain(s, a, x, b, e)
    g.chain(x, a)
    assert bound_of(g, retries=5) == 15
    assert bound_of(g, retries=0) == 5


def test_loop_uses_longest_cycle_through_the_node():
    # Two ways round from x back to x: through a (cycle x, a = 2) and through
    # b, c (cycle x, b, c = 3). The longest is 3
    g = Graph()
    s, x, a, b, c, e = (
        g.start("s"),
        g.xor("x"),
        g.task("a"),
        g.task("b"),
        g.task("c"),
        g.end("e"),
    )
    g.chain(s, x, e)
    g.chain(x, a, x)
    g.chain(x, b, c, x)
    # The only path to an end is s, x, e = 3. The paths that run into a loop do
    # not end there, they are covered by the cycle: 3 + 3 * 2 retries
    assert bound_of(g) == 3 + 3 * 2


def test_nested_loops_add_each_loop_head():
    # s, h1, h2, a, x, y, e: x loops to h2 (h2, a, x = 3), y loops to h1
    # (h1, h2, a, x, y = 5). Straight path is 7. 7 + (3 + 5) * 2
    g = Graph()
    s, h1, h2, a = g.start("s"), g.xor("h1"), g.xor("h2"), g.task("a")
    x, y, e = g.xor("x"), g.xor("y"), g.end("e")
    g.chain(s, h1, h2, a, x, y, e)
    g.chain(x, h2)
    g.chain(y, h1)
    assert bound_of(g) == 7 + (3 + 5) * 2


def test_parallel_inside_exclusive_branch():
    # s, x, then either a (short) or fork f, (b) + (c), join j; then m, e.
    # Long branch: s, x, f, b, c, j, m, e = 8
    g = Graph()
    s, x, a, f, b, c = (
        g.start("s"),
        g.xor("x"),
        g.task("a"),
        g.par("f"),
        g.task("b"),
        g.task("c"),
    )
    j, m, e = g.par("j"), g.xor("m"), g.end("e")
    g.chain(s, x, a, m)
    g.chain(x, f, b, j)
    g.chain(f, c, j)
    g.chain(j, m, e)
    assert bound_of(g) == 8


def test_nested_parallel_gateways():
    # Outer fork f1 with branches (a) and (inner fork f2 with (b) + (c), join j2),
    # join j1, e. s, f1 = 2; a = 1; f2, b, c, j2 = 4; j1, e = 2. Total 9
    g = Graph()
    s, f1, a, f2, b, c = (
        g.start("s"),
        g.par("f1"),
        g.task("a"),
        g.par("f2"),
        g.task("b"),
        g.task("c"),
    )
    j2, j1, e = g.par("j2"), g.par("j1"), g.end("e")
    g.chain(s, f1, a, j1)
    g.chain(f1, f2, b, j2)
    g.chain(f2, c, j2)
    g.chain(j2, j1, e)
    assert bound_of(g) == 9


def test_loop_around_a_fork_counts_cycle_as_one_path():
    # s, x, f, (a) + (b), j, y, e: the straight path is 1+1+1+2+1+1+1 = 8.
    # y loops back to x. A cycle is one path, so x, f, a, j, y = 5: 8 + 5 * 2
    g = Graph()
    s, x, f, a, b = g.start("s"), g.xor("x"), g.par("f"), g.task("a"), g.task("b")
    j, y, e = g.par("j"), g.xor("y"), g.end("e")
    g.chain(s, x, f, a, j, y, e)
    g.chain(f, b, j)
    g.chain(y, x)
    assert bound_of(g) == 8 + 5 * 2


def test_largest_start_event_and_process_wins():
    # first process: 3 steps. Second process has two start events: 2 and 4 steps
    g1 = Graph("p1")
    g1.chain(g1.start("s1"), g1.task("a1"), g1.end("e1"))
    g2 = Graph("p2")
    s2, s3 = g2.start("s2"), g2.start("s3")
    g2.chain(s2, g2.end("e2"))
    g2.chain(s3, g2.task("a3"), g2.task("b3"), g2.end("e3"))
    assert bound_of(g1) == 3
    assert bound_of(g2) == 4
    assert bound_of(g1, g2) == 4


def test_no_processes():
    assert bound_of() == 0


@pytest.mark.parametrize("bpmn_file", ["workflow.bpmn", "face2face_open.bpmn"])
def test_face2face(bpmn_file):
    # Longest path to an end: start, 1, fork, 3, 2, join, xor, 6, fork, 7a, 7b,
    # join, end = 13. The loop back to the first fork is fork, task, join, xor
    # = 4 (one branch, since a cycle is one path) and the two loops back to the xor
    # are 2 each, so 13 + (4 + 2) * 2 = 25
    with open(FACE2FACE + "state.txt") as f:
        state = State.from_str(f.read()).unwrap()
    bpmn = bpmnmethods.from_xml(parse(FACE2FACE + bpmn_file).getroot(), state).unwrap()
    assert get_unwinding_bound(bpmn) == 25
