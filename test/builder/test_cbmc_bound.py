from bpmncwpverify.builder.cbmc_bound import compute_unwind_bound
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


class Graph:
    """Small helper that wires nodes together the way ProcessBuilder does."""

    def __init__(self) -> None:
        self.process = Process("p", "p")
        self._flows = 0

    def start(self, id: str = "start") -> StartEvent:
        node = StartEvent(id, id, "", "")
        self.process[id] = node
        return node

    def end(self, id: str) -> EndEvent:
        node = EndEvent(id, id, "", "")
        self.process[id] = node
        return node

    def task(self, id: str) -> Task:
        node = Task(id, id, "")
        self.process[id] = node
        return node

    def xor(self, id: str) -> ExclusiveGatewayNode:
        node = ExclusiveGatewayNode(id, id)
        self.process[id] = node
        return node

    def par(self, id: str) -> ParallelGatewayNode:
        node = ParallelGatewayNode(id, id)
        self.process[id] = node
        return node

    def link(self, *nodes: Node) -> None:
        for source, target in zip(nodes, nodes[1:]):
            self._flows += 1
            flow = SequenceFlow(f"f{self._flows}", "")
            flow.source_node = source
            flow.target_node = target
            source.add_out_flow(flow)
            target.add_in_flow(flow)
            self.process[flow.id] = flow

    def bpmn(self, *others: "Graph") -> Bpmn:
        bpmn = Bpmn()
        for graph in (self, *others):
            bpmn.processes[graph.process.id] = graph.process
        return bpmn


def test_straight_line():
    # start, a, b, end run once each: 4 steps, +1 because --unwind N allows N-1 iterations
    g = Graph()
    start, a, b, end = g.start(), g.task("a"), g.task("b"), g.end("end")
    g.link(start, a, b, end)
    assert compute_unwind_bound(g.bpmn()) == 5


def test_empty_bpmn():
    # Nothing runs, so only the +1 is left
    assert compute_unwind_bound(Bpmn()) == 1


def test_exclusive_gateway_takes_longest_branch():
    # Only one branch runs, so the cost is the longer one (a1, a2), not both
    g = Graph()
    start, gw, end = g.start(), g.xor("gw"), g.end("end")
    a1, a2, b = g.task("a1"), g.task("a2"), g.task("b")
    merge = g.xor("merge")
    g.link(start, gw)
    g.link(gw, a1, a2, merge)
    g.link(gw, b, merge)
    g.link(merge, end)
    # start, gw, a1, a2, merge, end = 6
    assert compute_unwind_bound(g.bpmn()) == 7


def test_exclusive_split_to_separate_ends():
    # Branches never meet: start, gw, then max(a, b1 b2) end
    g = Graph()
    start, gw = g.start(), g.xor("gw")
    a, b1, b2 = g.task("a"), g.task("b1"), g.task("b2")
    g.link(start, gw)
    g.link(gw, a, g.end("e1"))
    g.link(gw, b1, b2, g.end("e2"))
    # start, gw, b1, b2, e2 = 5
    assert compute_unwind_bound(g.bpmn()) == 6


def test_parallel_gateway_adds_every_branch_and_counts_join_once():
    g = Graph()
    start, fork, join, end = g.start(), g.par("fork"), g.par("join"), g.end("end")
    a1, a2, b = g.task("a1"), g.task("a2"), g.task("b")
    g.link(start, fork)
    g.link(fork, a1, a2, join)
    g.link(fork, b, join)
    g.link(join, end)
    # start, fork, a1, a2, b, join, end = 7 (every token runs; join and end once)
    assert compute_unwind_bound(g.bpmn()) == 8


def test_loop_body_counted_twice():
    # start -> head -> body -> check -> (back to head | end)
    g = Graph()
    start, head, body = g.start(), g.xor("head"), g.task("body")
    check, end = g.xor("check"), g.end("end")
    g.link(start, head, body, check)
    g.link(check, head)
    g.link(check, end)
    # start 1 + loop {head, body, check} 3 nodes * 2 passes + end 1 = 8
    assert compute_unwind_bound(g.bpmn()) == 9


def test_loop_iterations_parameter():
    g = Graph()
    start, head, body = g.start(), g.xor("head"), g.task("body")
    check, end = g.xor("check"), g.end("end")
    g.link(start, head, body, check)
    g.link(check, head)
    g.link(check, end)
    # 1 + 3 * 3 + 1 = 11
    assert compute_unwind_bound(g.bpmn(), loop_iterations=3) == 12


def test_self_loop():
    # A task that loops on itself is a loop body of one node: 1 + 2 + 1 = 4
    g = Graph()
    start, t, end = g.start(), g.task("t"), g.end("end")
    g.link(start, t, end)
    g.link(t, t)
    assert compute_unwind_bound(g.bpmn()) == 5


def test_nested_loops_multiply():
    # start -> outer -> inner -> work -> in_check -(back)-> inner
    #                                   in_check -> out_check -(back)-> outer
    #                                               out_check -> end
    g = Graph()
    start, end = g.start(), g.end("end")
    outer, inner, work = g.xor("outer"), g.xor("inner"), g.task("work")
    in_check, out_check = g.xor("in_check"), g.xor("out_check")
    g.link(start, outer, inner, work, in_check, out_check, end)
    g.link(in_check, inner)
    g.link(out_check, outer)
    # outer-only nodes (outer, out_check) run 2 times each = 4
    # inner nodes (inner, work, in_check) run 2 * 2 = 4 times each = 12
    # start + end = 2; total 18
    assert compute_unwind_bound(g.bpmn()) == 19


def test_loop_containing_parallel_gateway():
    g = Graph()
    start, head, fork, join = g.start(), g.xor("head"), g.par("fork"), g.par("join")
    a, b, check, end = g.task("a"), g.task("b"), g.xor("check"), g.end("end")
    g.link(start, head, fork)
    g.link(fork, a, join)
    g.link(fork, b, join)
    g.link(join, check)
    g.link(check, head)
    g.link(check, end)
    # loop {head, fork, a, b, join, check} = 6 nodes * 2 = 12; start + end = 2
    assert compute_unwind_bound(g.bpmn()) == 15


def test_parallel_gateway_nested_in_exclusive_branch():
    # The expensive branch holds a fork; the cheap branch is a single task
    g = Graph()
    start, gw, merge, end = g.start(), g.xor("gw"), g.xor("merge"), g.end("end")
    fork, join = g.par("fork"), g.par("join")
    a, b, cheap = g.task("a"), g.task("b"), g.task("cheap")
    g.link(start, gw, fork)
    g.link(fork, a, join)
    g.link(fork, b, join)
    g.link(join, merge)
    g.link(gw, cheap, merge)
    g.link(merge, end)
    # start, gw, fork, a, b, join, merge, end = 8
    assert compute_unwind_bound(g.bpmn()) == 9


def test_nested_parallel_gateways():
    g = Graph()
    start, end = g.start(), g.end("end")
    f1, j1, f2, j2 = g.par("f1"), g.par("j1"), g.par("f2"), g.par("j2")
    a, b, c = g.task("a"), g.task("b"), g.task("c")
    g.link(start, f1)
    g.link(f1, a, j1)
    g.link(f1, f2)
    g.link(f2, b, j2)
    g.link(f2, c, j2)
    g.link(j2, j1)
    g.link(j1, end)
    # start, f1, a, f2, b, c, j2, j1, end = 9 (each join once)
    assert compute_unwind_bound(g.bpmn()) == 10


def test_boundary_event_path_is_added():
    g = Graph()
    start, task, end = g.start(), g.task("t"), g.end("end")
    boundary = Task.BoundaryEvent("b", "b", "", "", "t")
    handler, end2 = g.task("h"), g.end("end2")
    g.process["b"] = boundary
    task.add_boundary_event(boundary)
    g.link(start, task, end)
    g.link(boundary, handler, end2)
    # start, t, end + b, h, end2 = 6 (the event may fire as well as the task finishing)
    assert compute_unwind_bound(g.bpmn()) == 7


def test_processes_add_up():
    # Pools run concurrently, so their steps interleave in one run: 3 + 4 = 7
    g1 = Graph()
    g1.process = Process("p1", "p1")
    g1.link(g1.start(), g1.task("a"), g1.end("e"))
    g2 = Graph()
    g2.process = Process("p2", "p2")
    g2.link(g2.start(), g2.task("a"), g2.task("b"), g2.end("e"))
    assert compute_unwind_bound(g1.bpmn(g2)) == 8


def test_unreachable_nodes_ignored():
    g = Graph()
    g.link(g.start(), g.end("end"))
    g.task("orphan")
    assert compute_unwind_bound(g.bpmn()) == 3
