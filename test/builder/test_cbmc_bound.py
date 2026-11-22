# type: ignore
from xml.etree.ElementTree import fromstring

import pytest

from bpmncwpverify.builder.cbmc_bound import compute_cbmc_bound
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


class Graph:
    """
    Small helper to build a process from node ids, e.g. g.start("s").task("a")
    """

    def __init__(self):
        self.process = Process("p", "p")
        self.nodes = {}

    def _add(self, node):
        self.nodes[node.id] = node
        self.process[node.id] = node
        return self

    def start(self, *ids):
        for id in ids:
            self._add(StartEvent(id, id, "", ""))
        return self

    def end(self, *ids):
        for id in ids:
            self._add(EndEvent(id, id, "", ""))
        return self

    def task(self, *ids):
        for id in ids:
            self._add(Task(id, id, ""))
        return self

    def xor(self, *ids):
        for id in ids:
            self._add(ExclusiveGatewayNode(id, id))
        return self

    def par(self, *ids):
        for id in ids:
            self._add(ParallelGatewayNode(id, id))
        return self

    def flow(self, *ids):
        """
        Connect the given nodes in a chain
        """
        for source, target in zip(ids, ids[1:]):
            flow = SequenceFlow(f"{source}_{target}", "")
            flow.source_node = self.nodes[source]
            flow.target_node = self.nodes[target]
            self.nodes[source].add_out_flow(flow)
            self.nodes[target].add_in_flow(flow)
            self.process[flow.id] = flow
        return self

    def bpmn(self):
        bpmn = Bpmn()
        bpmn.processes[self.process.id] = self.process
        return bpmn


def bound(graph, **kwargs):
    return compute_cbmc_bound(graph.bpmn(), **kwargs)


def test_empty_bpmn_has_no_passes():
    assert compute_cbmc_bound(Bpmn()) == 0


def test_straight_line():
    # start, a, b, c, end are 5 nodes, one pass each
    g = Graph().start("s").task("a", "b", "c").end("e")
    g.flow("s", "a", "b", "c", "e")
    assert bound(g) == 5


def test_straight_line_ignores_retries():
    # no loops, so the retries don't matter
    g = Graph().start("s").task("a").end("e")
    g.flow("s", "a", "e")
    assert bound(g, retries=10) == 3


def test_exclusive_gateway_takes_longest_branch():
    # s, x, then the longer branch (a, b), then m, e: 1 + 1 + 2 + 1 + 1.
    # The short branch (c) isn't added, only one branch runs on a path
    g = Graph().start("s").xor("x", "m").task("a", "b", "c").end("e")
    g.flow("s", "x", "a", "b", "m", "e")
    g.flow("x", "c", "m")
    assert bound(g) == 6


def test_exclusive_gateway_branches_ending_separately():
    # s, x, then a, e1 (2) or b, c, e2 (3): 1 + 1 + 3
    g = Graph().start("s").xor("x").task("a", "b", "c")
    g.end("e1").end("e2")
    g.flow("s", "x", "a", "e1")
    g.flow("x", "b", "c", "e2")
    assert bound(g) == 5


def test_loop_adds_cycle_times_retries():
    # Path is s, a, x, e = 4. The loop x -> b -> x is a cycle of x and b,
    # 2 nodes, and it's allowed 2 retries: 4 + 2 * 2
    g = Graph().start("s").task("a", "b").xor("x").end("e")
    g.flow("s", "a", "x", "e")
    g.flow("x", "b", "x")
    assert bound(g) == 8


def test_loop_retries_parameter():
    # same graph as above with 5 retries: 4 + 5 * 2, and with none, just 4
    g = Graph().start("s").task("a", "b").xor("x").end("e")
    g.flow("s", "a", "x", "e")
    g.flow("x", "b", "x")
    assert bound(g, retries=5) == 14
    assert bound(g, retries=0) == 4


def test_loop_uses_longest_cycle_through_the_node():
    # Two loops come back to x: through b (2 nodes with x) and through c, d
    # (3 nodes with x). The longest is 3. Path s, x, e is 3, plus 3 * 2
    g = Graph().start("s").task("b", "c", "d").xor("x").end("e")
    g.flow("s", "x", "e")
    g.flow("x", "b", "x")
    g.flow("x", "c", "d", "x")
    assert bound(g) == 9


def test_loop_back_branch_does_not_count_as_path_to_end():
    # The loop branch (b, c) is longer than the exit (e) but doesn't reach the end
    # event, so the path is s, x, e = 3. Cycle is x, b, c = 3: 3 + 3 * 2
    g = Graph().start("s").task("b", "c").xor("x").end("e")
    g.flow("s", "x", "e")
    g.flow("x", "b", "c", "x")
    assert bound(g) == 9


def test_parallel_branches_are_added():
    # s, fork, a, b, join, e: the branches take a pass each, so 1 + 1 + 1 + 1 + 1 + 1
    g = Graph().start("s").par("f", "j").task("a", "b").end("e")
    g.flow("s", "f", "a", "j", "e")
    g.flow("f", "b", "j")
    assert bound(g) == 6


def test_parallel_branches_of_different_length_are_all_added():
    # s, f, (a1, a2) + (b) + (c1, c2, c3), j, e = 1 + 1 + 6 + 1 + 1
    g = Graph().start("s").par("f", "j").task("a1", "a2", "b", "c1", "c2", "c3")
    g.end("e")
    g.flow("s", "f", "a1", "a2", "j", "e")
    g.flow("f", "b", "j")
    g.flow("f", "c1", "c2", "c3", "j")
    assert bound(g) == 10


def test_after_the_join_is_counted_once():
    # The two branches both lead to j, then t1, t2, e. Those 3 count once, not
    # once per branch: s, f, a, b, j, t1, t2, e = 8
    g = Graph().start("s").par("f", "j").task("a", "b", "t1", "t2").end("e")
    g.flow("s", "f", "a", "j", "t1", "t2", "e")
    g.flow("f", "b", "j")
    assert bound(g) == 8


def test_parallel_fork_without_join_adds_each_branch_to_its_end():
    # Each branch ends on its own: s, f, (a, e1) + (b, e2) = 2 + 2 + 2
    g = Graph().start("s").par("f").task("a", "b").end("e1", "e2")
    g.flow("s", "f", "a", "e1")
    g.flow("f", "b", "e2")
    assert bound(g) == 6


def test_exclusive_gateway_inside_parallel_branch():
    # Branch one is x then the longer of (a1, a2) or (b): x, a1, a2, m = 4.
    # Branch two is c = 1. s, f, 4 + 1, j, e = 1 + 1 + 5 + 1 + 1
    g = Graph().start("s").par("f", "j").xor("x", "m").task("a1", "a2", "b", "c")
    g.end("e")
    g.flow("s", "f", "x", "a1", "a2", "m", "j", "e")
    g.flow("x", "b", "m")
    g.flow("f", "c", "j")
    assert bound(g) == 9


def test_nested_parallel_gateways():
    # Outer branches: [inner fork f2, a, b, join j2] = 4 and [c] = 1.
    # s, f1, 4 + 1, j1, e = 1 + 1 + 5 + 1 + 1
    g = Graph().start("s").par("f1", "j1", "f2", "j2").task("a", "b", "c").end("e")
    g.flow("s", "f1", "f2", "a", "j2", "j1", "e")
    g.flow("f2", "b", "j2")
    g.flow("f1", "c", "j1")
    assert bound(g) == 9


def test_parallel_fork_inside_loop_is_one_branch_in_the_cycle():
    # The loop goes back from y to x, around the fork and join. A cycle is a
    # single path around, so it takes one branch of the fork.
    # Path: s, x, f, a, b, j, y, e = 8 (the branches are added).
    # Cycle: x, f, a, j, y = 5. 8 + 5 * 2
    g = Graph().start("s").xor("x", "y").par("f", "j").task("a", "b").end("e")
    g.flow("s", "x", "f", "a", "j", "y", "e")
    g.flow("f", "b", "j")
    g.flow("y", "x")
    assert bound(g) == 8 + 5 * 2


def test_nested_loops_each_add_their_own_cycle():
    # Path: s, x1, x2, e = 4. Inner loop x2 -> a -> x2 is 2 nodes. Outer loop
    # x1 -> x2 -> b -> x1 is 3 nodes. 4 + (2 + 3) * 2
    g = Graph().start("s").xor("x1", "x2").task("a", "b").end("e")
    g.flow("s", "x1", "x2", "e")
    g.flow("x2", "a", "x2")
    g.flow("x2", "b", "x1")
    assert bound(g) == 14


def test_largest_start_event_wins():
    # Two start events in one process, one with a path of 2 and one with 4
    g = Graph().start("s1", "s2").task("a", "b").end("e1", "e2")
    g.flow("s1", "e1")
    g.flow("s2", "a", "b", "e2")
    assert bound(g) == 4


def test_largest_process_wins():
    short = Graph().start("s").end("e")
    short.flow("s", "e")
    long = Graph().start("s").task("a", "b").end("e")
    long.flow("s", "a", "b", "e")
    long.process.id = "q"
    bpmn = short.bpmn()
    bpmn.processes["q"] = long.process
    assert compute_cbmc_bound(bpmn) == 4


@pytest.mark.parametrize("name", ["workflow", "face2face_open"])
def test_face2face(name):
    # Path: start, 1, fork, 3 + 2 (branches added), join, x, 6, fork, 7a + 7b,
    # join, end = 13.
    # Loops: x is come back to from tasks 4 and 5: x, 5 = 2 nodes. The fork
    # is come back to from x: fork, 3, join, x = 4 nodes (one branch).
    # 13 + (2 + 4) * 2 = 25
    directory = "./test/resources/face2face/"
    with open(directory + "state.txt") as state_file:
        state = State.from_str(state_file.read()).unwrap()
    with open(f"{directory}{name}.bpmn") as bpmn_file:
        bpmn = bpmnmethods.from_xml(fromstring(bpmn_file.read()), state).unwrap()

    assert compute_cbmc_bound(bpmn) == 25
