# type: ignore
from pathlib import Path
from xml.etree.ElementTree import parse

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

FACE2FACE = Path(__file__).parent.parent / "resources" / "face2face"


def make(kinds: str, edges: list[tuple[str, str]], prefix: str = "n") -> Bpmn:
    """
    kinds maps one letter per node to a type: s start, t task, e end,
    x exclusive gateway, p parallel gateway. Edges and node ids use "n0", "n1", ...
    (the prefix replaces the "n", so ids stay unique across processes)
    """
    bpmn = Bpmn()
    process = Process("p", "p")
    bpmn.processes["p"] = process
    classes = {
        "s": lambda i: StartEvent(i, i, "", ""),
        "e": lambda i: EndEvent(i, i, "", ""),
        "t": lambda i: Task(i, i, ""),
        "x": lambda i: ExclusiveGatewayNode(i, i),
        "p": lambda i: ParallelGatewayNode(i, i),
    }
    nodes: dict[str, Node] = {}
    for idx, kind in enumerate(kinds):
        node = classes[kind](f"{prefix}{idx}")
        nodes[node.id] = node
        process[node.id] = node
    for src, dst in edges:
        src, dst = prefix + src[1:], prefix + dst[1:]
        flow = SequenceFlow(f"{src}-{dst}", "")
        flow.source_node, flow.target_node = nodes[src], nodes[dst]
        nodes[src].add_out_flow(flow)
        nodes[dst].add_in_flow(flow)
        process[flow.id] = flow
    return bpmn


def test_straight_line():
    # start, task, task, end: four nodes, one step each
    bpmn = make("stte", [("n0", "n1"), ("n1", "n2"), ("n2", "n3")])
    assert compute_bound(bpmn) == 4


def test_empty_bpmn():
    # No start event, so nothing ever runs
    assert compute_bound(Bpmn()) == 0


def test_exclusive_takes_longest_branch():
    # s -> x -> (t -> t | t) -> t(merge) -> e. Longest branch has two tasks:
    # s, x, t, t, merge, e = 6, since CBMC tries each branch
    bpmn = make(
        "sxtttte",
        [
            ("n0", "n1"),
            ("n1", "n2"),
            ("n2", "n3"),
            ("n3", "n5"),
            ("n1", "n4"),
            ("n4", "n5"),
            ("n5", "n6"),
        ],
    )
    assert compute_bound(bpmn) == 6


def test_exclusive_branches_to_separate_ends():
    # s -> x -> e1 and x -> t -> e2: longest is s, x, t, e2 = 4
    bpmn = make(
        "sxete",
        [("n0", "n1"), ("n1", "n2"), ("n1", "n3"), ("n3", "n4")],
    )
    assert compute_bound(bpmn) == 4


def test_parallel_adds_branches_and_counts_tail_once():
    # s -> fork -> (t1, t2) -> join -> t -> e
    # s, fork = 2; branches add: 1 + 1 = 2; join, t, e = 3 after the join. Total 7
    bpmn = make(
        "spttpte",
        [
            ("n0", "n1"),
            ("n1", "n2"),
            ("n1", "n3"),
            ("n2", "n4"),
            ("n3", "n4"),
            ("n4", "n5"),
            ("n5", "n6"),
        ],
    )
    assert compute_bound(bpmn) == 7


def test_parallel_branches_of_unequal_length_are_summed():
    # s -> fork -> (t -> t | t) -> join -> e
    # s, fork = 2; branches 2 + 1 = 3; join, e = 2. Total 7. Each branch
    # takes passes of its own, so the shorter one is not hidden by the longer
    bpmn = make(
        "sptttpe",
        [
            ("n0", "n1"),
            ("n1", "n2"),
            ("n2", "n3"),
            ("n1", "n4"),
            ("n3", "n5"),
            ("n4", "n5"),
            ("n5", "n6"),
        ],
    )
    assert compute_bound(bpmn) == 7


def test_loop_adds_cycle_times_retries():
    # s -> t -> x -> e, x -> t (loop). Base: s, t, x, e = 4.
    # t is the loop head; the cycle t, x has 2 nodes
    bpmn = make("stxe", [("n0", "n1"), ("n1", "n2"), ("n2", "n3"), ("n2", "n1")])
    assert compute_bound(bpmn, retries=0) == 4
    assert compute_bound(bpmn, retries=1) == 6
    assert compute_bound(bpmn) == 8


def test_self_loop():
    # s -> t -> e with t -> t. Base 3; the cycle is the one node t: 3 + 1 * 2
    bpmn = make("ste", [("n0", "n1"), ("n1", "n2"), ("n1", "n1")])
    assert compute_bound(bpmn) == 5


def test_loop_uses_longest_cycle_into_head():
    # x -> a -> x is a short way back; x -> a -> b -> x is a long one. Both come
    # back into x, and the longest path from x to where they close is x, a, b = 3.
    # Base: s, x, e = 3 (a path that only loops back never reaches an end);
    # plus 3 * 2 = 9
    bpmn = make(
        "sxtte",
        [
            ("n0", "n1"),
            ("n1", "n4"),
            ("n1", "n2"),
            ("n2", "n1"),
            ("n2", "n3"),
            ("n3", "n1"),
        ],
    )
    assert compute_bound(bpmn) == 3 + 3 * 2


def test_nested_loops_each_count():
    # s -> a(x) -> b(x) -> t -> c(x) -> e; c -> b (inner loop), c -> a (outer)
    # Base: s, a, b, t, c, e = 6.
    # Inner: head b, longest path b, t, c = 3. Outer: head a, path a, b, t, c = 4
    # 6 + (3 + 4) * 2 = 20
    bpmn = make(
        "sxxtxe",
        [
            ("n0", "n1"),
            ("n1", "n2"),
            ("n2", "n3"),
            ("n3", "n4"),
            ("n4", "n5"),
            ("n4", "n2"),
            ("n4", "n1"),
        ],
    )
    assert compute_bound(bpmn) == 20


def test_nested_parallel():
    # s -> f1 -> (f2 -> (t, t) -> j2 | t) -> j1 -> e
    # n0 s, n1 f1, n2 f2, n3 t, n4 t, n5 j2, n6 t, n7 j1, n8 e
    # Inner fork: f2 + 1 + 1 + j2 = 4. Outer: s, f1 = 2, branches 4 + 1 = 5,
    # then j1, e = 2. Total 9
    bpmn = make(
        "spptt" + "ptpe",
        [
            ("n0", "n1"),
            ("n1", "n2"),
            ("n1", "n6"),
            ("n2", "n3"),
            ("n2", "n4"),
            ("n3", "n5"),
            ("n4", "n5"),
            ("n5", "n7"),
            ("n6", "n7"),
            ("n7", "n8"),
        ],
    )
    assert compute_bound(bpmn) == 9


def test_loop_around_parallel():
    # s -> f -> (t, t) -> j -> x -> e, x -> f. Base: s, f, t, t, j, x, e = 7
    # Head f, cycle through the loop: f, t, j, x = 4. 7 + 4 * 2 = 15
    bpmn = make(
        "spttpxe",
        [
            ("n0", "n1"),
            ("n1", "n2"),
            ("n1", "n3"),
            ("n2", "n4"),
            ("n3", "n4"),
            ("n4", "n5"),
            ("n5", "n6"),
            ("n5", "n1"),
        ],
    )
    assert compute_bound(bpmn) == 15


def test_largest_of_several_start_events():
    # Two processes: a 3-node line and a 5-node line. The bound is the larger
    bpmn = make("ste", [("n0", "n1"), ("n1", "n2")])
    other = make("sttte", [(f"n{i}", f"n{i + 1}") for i in range(4)], prefix="q")
    bpmn.processes["q"] = other.processes["p"]
    assert compute_bound(bpmn) == 5


def test_largest_of_several_start_events_in_one_process():
    # Two starts joining into one line: the longer start is 3 steps + 2 shared
    bpmn = make(
        "sstte",
        [("n0", "n2"), ("n1", "n3"), ("n2", "n3"), ("n3", "n4")],
    )
    assert compute_bound(bpmn) == 4


@pytest.mark.parametrize("name", ["workflow.bpmn", "face2face_open.bpmn"])
def test_face2face(name):
    # Base path: start, task 1, fork, task 3, task 2, join, gateway, task 6,
    # fork, 7a, 7b, join, end = 13. Loops: the gateway is entered back from
    # task 4/5 (cycle of 2) and the first fork from the gateway (fork, task,
    # join, gateway = 4). 13 + (2 + 4) * 2 = 25
    state = State.from_str((FACE2FACE / "state.txt").read_text()).unwrap()
    bpmn = bpmnmethods.from_xml(parse(FACE2FACE / name).getroot(), state).unwrap()
    assert compute_bound(bpmn, retries=0) == 13
    assert compute_bound(bpmn) == 25
