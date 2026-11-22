from xml.etree import ElementTree

import pytest

from bpmncwpverify.builder.cbmc_bound import compute_bound
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
    Small helper to wire up a Bpmn: node("s", StartEvent), then edge("s", "t")
    """

    def __init__(self) -> None:
        self.bpmn = Bpmn()
        self._process = Process("p0", "p0")
        self.bpmn.processes["p0"] = self._process
        self._nodes: dict[str, Node] = {}

    def node(self, name: str, kind: str) -> "Graph":
        node: Node
        if kind == "start":
            node = StartEvent(name, name, "", "")
        elif kind == "end":
            node = EndEvent(name, name, "", "")
        elif kind == "task":
            node = Task(name, name, "")
        elif kind == "xor":
            node = ExclusiveGatewayNode(name, name)
        else:
            node = ParallelGatewayNode(name, name)
        self._nodes[name] = node
        self._process[name] = node
        return self

    def edge(self, source: str, target: str) -> "Graph":
        flow = SequenceFlow(f"{source}_{target}", "")
        flow.source_node = self._nodes[source]
        flow.target_node = self._nodes[target]
        flow.source_node.add_out_flow(flow)
        flow.target_node.add_in_flow(flow)
        self._process[flow.id] = flow
        return self

    def chain(self, *names: str) -> "Graph":
        for source, target in zip(names, names[1:]):
            self.edge(source, target)
        return self


def _line() -> Graph:
    g = Graph()
    g.node("s", "start").node("a", "task").node("b", "task").node("e", "end")
    return g.chain("s", "a", "b", "e")


def test_empty_bpmn_has_bound_zero():
    # nothing can fire
    assert compute_bound(Bpmn()) == 0


def test_straight_line():
    # start, two tasks, end: one pass each
    assert compute_bound(_line().bpmn) == 4


def test_loop_back_to_task():
    # s -> a -> x -> (e | a). Acyclic path: s, a, x, e = 4.
    # The loop comes back into a: cycle a, x = 2 steps, retried twice = 4.
    g = Graph()
    g.node("s", "start").node("a", "task").node("x", "xor").node("e", "end")
    g.chain("s", "a", "x", "e").edge("x", "a")
    assert compute_bound(g.bpmn) == 4 + 2 * 2
    assert compute_bound(g.bpmn, retries=0) == 4
    assert compute_bound(g.bpmn, retries=5) == 4 + 2 * 5


def test_self_loop():
    # a task that loops to itself through an xor: cycle is a, x
    g = Graph()
    g.node("s", "start").node("t", "task").node("x", "xor").node("e", "end")
    g.chain("s", "t", "x", "e").edge("x", "t")
    assert compute_bound(g.bpmn) == 4 + 2 * 2


def test_flow_from_node_to_itself():
    # the cycle is the one node
    g = Graph()
    g.node("s", "start").node("x", "xor").node("e", "end")
    g.chain("s", "x", "e").edge("x", "x")
    assert compute_bound(g.bpmn) == 3 + 1 * 2


def test_two_loops_into_same_node_use_longest_cycle():
    # s -> x -> (e | a -> x | b -> c -> x). The longest path to the end event
    # is s, x, e = 3; the loop branches are cut and don't end at an end event.
    # The cycles through x are x, a = 2 and x, b, c = 3, so 3 * 2 more.
    g = Graph()
    g.node("s", "start").node("x", "xor").node("a", "task").node("b", "task")
    g.node("c", "task").node("e", "end")
    g.chain("s", "x", "e").chain("x", "a", "x").chain("x", "b", "c", "x")
    assert compute_bound(g.bpmn) == 3 + 3 * 2


def test_exclusive_gateway_takes_longest_branch():
    # s, x, then a (1 step) or b, c, d (3 steps), merged at m, then e.
    # s, x, b, c, d, m, e = 7
    g = Graph()
    g.node("s", "start").node("x", "xor").node("a", "task").node("b", "task")
    g.node("c", "task").node("d", "task").node("m", "xor").node("e", "end")
    g.chain("s", "x", "a", "m", "e").chain("x", "b", "c", "d", "m")
    assert compute_bound(g.bpmn) == 7


def test_exclusive_gateway_branches_ending_separately():
    # one branch ends at once, the other goes through two tasks
    g = Graph()
    g.node("s", "start").node("x", "xor").node("e1", "end").node("a", "task")
    g.node("b", "task").node("e2", "end")
    g.chain("s", "x", "e1").chain("x", "a", "b", "e2")
    assert compute_bound(g.bpmn) == 5


def test_parallel_branches_add_up():
    # s, fork, (a, b: 2 + c: 1), join, e. Branches each take their own
    # passes, so 1 + 1 + 3 + 1 + 1 = 7
    g = Graph()
    g.node("s", "start").node("f", "par").node("a", "task").node("b", "task")
    g.node("c", "task").node("j", "par").node("e", "end")
    g.chain("s", "f", "a", "b", "j", "e").chain("f", "c", "j")
    assert compute_bound(g.bpmn) == 7


def test_part_after_join_counts_once():
    # two branches of one task, then a three-step tail after the join:
    # s, f, a, b, j, t1, t2, e = 8. Counting the tail per branch would give 11.
    g = Graph()
    g.node("s", "start").node("f", "par").node("a", "task").node("b", "task")
    g.node("j", "par").node("t1", "task").node("t2", "task").node("e", "end")
    g.chain("s", "f", "a", "j", "t1", "t2", "e").chain("f", "b", "j")
    assert compute_bound(g.bpmn) == 8


def test_parallel_branches_ending_without_join():
    # each branch ends at its own end event: s, f, (a, e1), (b, e2) = 6
    g = Graph()
    g.node("s", "start").node("f", "par").node("a", "task").node("b", "task")
    g.node("e1", "end").node("e2", "end")
    g.chain("s", "f", "a", "e1").chain("f", "b", "e2")
    assert compute_bound(g.bpmn) == 6


def test_exclusive_choice_inside_parallel_branch():
    # branch 1 is x then a (1) or b, c (2), merging at m: x, b, c, m = 4.
    # branch 2 is d = 1. s, f, 4, 1, j, e = 9
    g = Graph()
    g.node("s", "start").node("f", "par").node("x", "xor").node("a", "task")
    g.node("b", "task").node("c", "task").node("m", "xor").node("d", "task")
    g.node("j", "par").node("e", "end")
    g.chain("s", "f", "x", "a", "m", "j", "e").chain("x", "b", "c", "m")
    g.chain("f", "d", "j")
    assert compute_bound(g.bpmn) == 9


def test_nested_parallel():
    # outer branch 1: a, inner fork g, (b, c), inner join k = 1 + 1 + 2 + 1 = 5
    # outer branch 2: d = 1. s, f, 5, 1, j, e = 10
    g = Graph()
    g.node("s", "start").node("f", "par").node("a", "task").node("g", "par")
    g.node("b", "task").node("c", "task").node("k", "par").node("d", "task")
    g.node("j", "par").node("e", "end")
    g.chain("s", "f", "a", "g", "b", "k", "j", "e")
    g.chain("g", "c", "k").chain("f", "d", "j")
    assert compute_bound(g.bpmn) == 10


def test_nested_parallel_sharing_a_join():
    # the inner branches go straight into the outer join: f, a, g, b, c, d, j
    # s, f, then branch a, g, b, c (4) and branch d (1), j, e = 9
    g = Graph()
    g.node("s", "start").node("f", "par").node("a", "task").node("g", "par")
    g.node("b", "task").node("c", "task").node("d", "task").node("j", "par")
    g.node("e", "end")
    g.chain("s", "f", "a", "g", "b", "j", "e")
    g.chain("g", "c", "j").chain("f", "d", "j")
    assert compute_bound(g.bpmn) == 9


def test_loop_around_parallel_section():
    # s, t, f, (a | b), j, x, e = 8 on the acyclic part.
    # x loops back to f (cut). Cycle f, a, j, x = 4, so 4 * 2 more.
    g = Graph()
    g.node("s", "start").node("t", "task").node("f", "par").node("a", "task")
    g.node("b", "task").node("j", "par").node("x", "xor").node("e", "end")
    g.chain("s", "t", "f", "a", "j", "x", "e").chain("f", "b", "j").edge("x", "f")
    assert compute_bound(g.bpmn) == 8 + 4 * 2


def test_nested_loops():
    # s, a, b, x2, x1, e = 6 acyclic. Inner loop x2 -> b: cycle b, x2 = 2.
    # Outer loop x1 -> a: cycle a, b, x2, x1 = 4. 6 + (2 + 4) * 2 = 18
    g = Graph()
    g.node("s", "start").node("a", "task").node("b", "task").node("x2", "xor")
    g.node("x1", "xor").node("e", "end")
    g.chain("s", "a", "b", "x2", "x1", "e").edge("x2", "b").edge("x1", "a")
    assert compute_bound(g.bpmn) == 6 + (2 + 4) * 2


def test_largest_over_start_events_and_processes():
    # a second start event in the same process leads into the line, with an
    # extra task: s2, z, b, e = 4 < 4? make it longer: s2, z1, z2, b, e = 5
    g = _line()
    g.node("s2", "start").node("z1", "task").node("z2", "task")
    g.chain("s2", "z1", "z2", "b")
    assert compute_bound(g.bpmn) == 5

    # another process with 3 steps does not beat the 4 of the line
    other = Process("p1", "p1")
    start, end = StartEvent("os", "os", "", ""), EndEvent("oe", "oe", "", "")
    task = Task("ot", "ot", "")
    for source, target in ((start, task), (task, end)):
        flow = SequenceFlow(f"{source.id}_{target.id}", "")
        flow.source_node, flow.target_node = source, target
        source.add_out_flow(flow)
        target.add_in_flow(flow)
        other[flow.id] = flow
    for node in (start, task, end):
        other[node.id] = node
    line = _line().bpmn
    line.processes["p1"] = other
    assert compute_bound(line) == 4

    # and a longer one wins
    task.name = "unused"
    longer = Process("p2", "p2")
    nodes: list[Node] = [StartEvent("a0", "a0", "", "")]
    nodes += [Task(f"a{i}", "", "") for i in range(1, 8)]
    nodes.append(EndEvent("a8", "a8", "", ""))
    for node in nodes:
        longer[node.id] = node
    for source, target in zip(nodes, nodes[1:]):
        flow = SequenceFlow(f"{source.id}_{target.id}", "")
        flow.source_node, flow.target_node = source, target
        source.add_out_flow(flow)
        target.add_in_flow(flow)
        longer[flow.id] = flow
    line.processes["p2"] = longer
    assert compute_bound(line) == 9


@pytest.mark.parametrize("bpmn_file", ["workflow.bpmn", "face2face_open.bpmn"])
def test_face2face(bpmn_file):
    # Acyclic part: start, task, fork, 2 tasks, join, xor = 7, then the longest
    # branch: task, fork, 2 tasks, join, end = 6. 13 in all.
    # Loops: back to the fork, cycle fork, task, join, xor = 4 (the parallel
    # branches are one cycle's worth, not summed). Back to the xor from the two
    # retry tasks: cycle xor, task = 2. 13 + (4 + 2) * 2 = 25.
    with open(FACE2FACE + "state.txt") as f:
        state = State.from_str(f.read()).unwrap()
    root = ElementTree.parse(FACE2FACE + bpmn_file).getroot()
    bpmn = bpmnmethods.from_xml(root, state).unwrap()
    assert compute_bound(bpmn) == 25


def test_loop_with_no_way_out_still_has_a_bound():
    # s -> a -> b -> a, no end event: nothing reaches an end, so count the
    # path up to the cut: s, a, b = 3, plus the cycle a, b = 2 twice
    g = Graph()
    g.node("s", "start").node("a", "task").node("b", "task")
    g.chain("s", "a", "b", "a")
    assert compute_bound(g.bpmn) == 3 + 2 * 2
