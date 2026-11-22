from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from bpmncwpverify.builder.cbmc_bound import compute_bound
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

FACE2FACE = Path(__file__).parent.parent / "resources" / "face2face"


class Graph:
    """Small helper to build one process from node names and edges"""

    def __init__(self, process_id: str = "p") -> None:
        self.process = Process(process_id, process_id)
        self.nodes: dict[str, object] = {}
        self._flows = 0

    def add(self, kind: str, *names: str) -> "Graph":
        for name in names:
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
            self.process[name] = node
            self.nodes[name] = node
        return self

    def edge(self, *names: str) -> "Graph":
        for src, dst in zip(names, names[1:]):
            self._flows += 1
            flow = SequenceFlow(f"f{self._flows}", "")
            flow.source_node = self.nodes[src]
            flow.target_node = self.nodes[dst]
            self.nodes[src].add_out_flow(flow)
            self.nodes[dst].add_in_flow(flow)
            self.process[flow.id] = flow
        return self


def bpmn_of(*graphs: Graph) -> Bpmn:
    bpmn = Bpmn()
    for g in graphs:
        bpmn.processes[g.process.id] = g.process
    return bpmn


def test_straight_line():
    # start, task, end: three nodes, one pass each
    g = Graph().add("start", "s").add("task", "t").add("end", "e").edge("s", "t", "e")
    assert compute_bound(bpmn_of(g)) == 3


def test_no_processes():
    assert compute_bound(Bpmn()) == 0


def test_loop_adds_cycle_times_retries():
    # s t x e is 4 nodes without the loop. x goes back to t, so the cycle is
    # t, x: 2 nodes, run 2 more times: 4 + 2 * 2
    g = (
        Graph()
        .add("start", "s")
        .add("task", "t")
        .add("xor", "x")
        .add("end", "e")
        .edge("s", "t", "x", "e")
        .edge("x", "t")
    )
    assert compute_bound(bpmn_of(g)) == 8


@pytest.mark.parametrize("retries,expected", [(0, 4), (1, 6), (2, 8), (5, 14)])
def test_loop_retries_parameter(retries, expected):
    # 4 for the path plus 2 nodes in the cycle for each retry
    g = (
        Graph()
        .add("start", "s")
        .add("task", "t")
        .add("xor", "x")
        .add("end", "e")
        .edge("s", "t", "x", "e")
        .edge("x", "t")
    )
    assert compute_bound(bpmn_of(g), retries=retries) == expected


def test_exclusive_takes_longest_branch():
    # s x then either a b e1 (3) or c e2 (2): s x a b e1 is 5
    g = (
        Graph()
        .add("start", "s")
        .add("xor", "x")
        .add("task", "a", "b", "c")
        .add("end", "e1", "e2")
        .edge("s", "x", "a", "b", "e1")
        .edge("x", "c", "e2")
    )
    assert compute_bound(bpmn_of(g)) == 5


def test_parallel_adds_branches_and_counts_join_once():
    # s f, branches a and b are 1 each and add up to 2, then the join j and
    # the end e once: 2 + 2 + 2
    g = (
        Graph()
        .add("start", "s")
        .add("par", "f", "j")
        .add("task", "a", "b")
        .add("end", "e")
        .edge("s", "f", "a", "j", "e")
        .edge("f", "b", "j")
    )
    assert compute_bound(bpmn_of(g)) == 6


def test_parallel_uneven_branches():
    # branches of 2 (a1 a2) and 1 (b) add up to 3: s f + 3 + j e = 7
    g = (
        Graph()
        .add("start", "s")
        .add("par", "f", "j")
        .add("task", "a1", "a2", "b")
        .add("end", "e")
        .edge("s", "f", "a1", "a2", "j", "e")
        .edge("f", "b", "j")
    )
    assert compute_bound(bpmn_of(g)) == 7


def test_parallel_branches_ending_separately():
    # no join: s f, a e1 (2), b e2 (2): both branches run on their own, 6
    g = (
        Graph()
        .add("start", "s")
        .add("par", "f")
        .add("task", "a", "b")
        .add("end", "e1", "e2")
        .edge("s", "f", "a", "e1")
        .edge("f", "b", "e2")
    )
    assert compute_bound(bpmn_of(g)) == 6


def test_exclusive_inside_parallel_branch():
    # branch 1 is x then the longer of a (1) and c d (2): 3. Branch 2 is b: 1.
    # s f + 3 + 1 + j e = 8
    g = (
        Graph()
        .add("start", "s")
        .add("par", "f", "j")
        .add("xor", "x")
        .add("task", "a", "c", "d", "b")
        .add("end", "e")
        .edge("s", "f", "x", "a", "j", "e")
        .edge("x", "c", "d", "j")
        .edge("f", "b", "j")
    )
    assert compute_bound(bpmn_of(g)) == 8


def test_nested_parallel():
    # s f1; branch 1 is f2, a b (2), j2, c: 5; branch 2 is d: 1; then j1 e.
    # 2 + 5 + 1 + 2 = 10
    g = (
        Graph()
        .add("start", "s")
        .add("par", "f1", "j1", "f2", "j2")
        .add("task", "a", "b", "c", "d")
        .add("end", "e")
        .edge("s", "f1", "f2", "a", "j2", "c", "j1", "e")
        .edge("f2", "b", "j2")
        .edge("f1", "d", "j1")
    )
    assert compute_bound(bpmn_of(g)) == 10


def test_nested_loops():
    # path s h1 h2 x2 x1 e is 6. x2 goes back to h2: cycle h2 x2 is 2. x1 goes
    # back to h1: cycle h1 h2 x2 x1 is 4, without taking x2's way back to h2.
    # 6 + (2 + 4) * 2 = 18
    g = (
        Graph()
        .add("start", "s")
        .add("task", "h1", "h2")
        .add("xor", "x2", "x1")
        .add("end", "e")
        .edge("s", "h1", "h2", "x2", "x1", "e")
        .edge("x2", "h2")
        .edge("x1", "h1")
    )
    assert compute_bound(bpmn_of(g)) == 18


def test_loop_takes_longest_cycle_through_node():
    # t has two ways back: from x (cycle t x is 2) and from x3 (cycle
    # t x x2 y x3 is 5, the longest). The longest path, until it hits the way
    # back, is s t x x2 y x3: 6. 6 + 5 * 2 = 16
    g = (
        Graph()
        .add("start", "s")
        .add("task", "t", "y")
        .add("xor", "x", "x2", "x3")
        .add("end", "e")
        .edge("s", "t", "x", "e")
        .edge("x", "t")
        .edge("x", "x2", "y", "x3", "t")
    )
    assert compute_bound(bpmn_of(g)) == 16


def test_largest_over_processes_and_start_events():
    short = Graph("a").add("start", "s1").add("end", "e1").edge("s1", "e1")
    long = (
        Graph("b")
        .add("start", "s2", "s3")
        .add("task", "t1", "t2")
        .add("end", "e2")
        .edge("s2", "t1", "t2", "e2")  # 4
        .edge("s3", "e2")  # 2
    )
    assert compute_bound(bpmn_of(short, long)) == 4


def _face2face(name: str) -> Bpmn:
    state = State.from_str((FACE2FACE / "state.txt").read_text()).unwrap()
    return bpmnmethods.from_xml(
        ET.fromstring((FACE2FACE / name).read_text()), state
    ).unwrap()


@pytest.mark.parametrize("name", ["workflow.bpmn", "face2face_open.bpmn"])
def test_face2face(name):
    # Path: start, task 1, fork, tasks 2 and 3 (add up to 2), join, exclusive,
    # task 6, fork, tasks 7a and 7b (2), join, end: 13. Loops: back to the
    # first fork (fork, task, join, exclusive: 4) and back to the exclusive
    # gateway (exclusive, task 4 or 5: 2). 13 + (4 + 2) * 2 = 25
    assert compute_bound(_face2face(name)) == 25
    assert compute_bound(_face2face(name), retries=0) == 13
