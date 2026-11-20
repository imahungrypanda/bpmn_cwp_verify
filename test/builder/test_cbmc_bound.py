# type: ignore
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

FACE2FACE = "test/resources/face2face/"


def _node(kind, id):
    if kind == "start":
        return StartEvent(id, id, "", "")
    if kind == "end":
        return EndEvent(id, id, "", "")
    if kind == "task":
        return Task(id, id, "")
    if kind == "xor":
        return ExclusiveGatewayNode(id, id)
    return ParallelGatewayNode(id, id)


def _bpmn(nodes, edges):
    """
    nodes: {id: kind}, edges: [(source id, target id)]
    All nodes go in one process.
    """
    process = Process("p", "p")
    built = {id: _node(kind, id) for id, kind in nodes.items()}
    for node in built.values():
        process[node.id] = node
    for i, (src, dst) in enumerate(edges):
        flow = SequenceFlow(f"f{i}", f"f{i}")
        flow.source_node, flow.target_node = built[src], built[dst]
        built[src].add_out_flow(flow)
        built[dst].add_in_flow(flow)
        process[flow.id] = flow
    bpmn = Bpmn()
    bpmn.processes["p"] = process
    return bpmn


def test_empty_bpmn_needs_no_passes():
    assert compute_bound(Bpmn()) == 0


def test_straight_line():
    # start, a, b, end each fire once
    bpmn = _bpmn(
        {"s": "start", "a": "task", "b": "task", "e": "end"},
        [("s", "a"), ("a", "b"), ("b", "e")],
    )
    assert compute_bound(bpmn) == 4


def test_loop_adds_cycle_length_times_retries():
    # s, a, g, e is the loop-free path (4). g -> a is a loop through a and g
    # (cycle of 2), so each retry adds 2.
    bpmn = _bpmn(
        {"s": "start", "a": "task", "g": "xor", "e": "end"},
        [("s", "a"), ("a", "g"), ("g", "e"), ("g", "a")],
    )
    assert compute_bound(bpmn, retries=0) == 4
    assert compute_bound(bpmn, retries=1) == 6
    assert compute_bound(bpmn) == 8  # default of 2 retries


def test_loop_uses_longest_cycle_through_the_node():
    # Two ways back into a: via g -> a (cycle a, g = 2) and via
    # g -> b -> c -> a (cycle a, g, b, c = 4). The longest, 4, is added once.
    bpmn = _bpmn(
        {"s": "start", "a": "task", "g": "xor", "b": "task", "c": "task", "e": "end"},
        [
            ("s", "a"),
            ("a", "g"),
            ("g", "e"),
            ("g", "a"),
            ("g", "b"),
            ("b", "c"),
            ("c", "a"),
        ],
    )
    # loop-free: c's edge back to a is a dead end, so s, a, g, b, c = 5;
    # plus 4 * 2 retries
    assert compute_bound(bpmn) == 13


def test_two_loops_are_added():
    # s, a, g1, b, g2, e = 6 without loops. g1 -> a is a cycle of 2 (a, g1),
    # g2 -> b is a cycle of 2 (b, g2): 6 + 2*2 + 2*2
    bpmn = _bpmn(
        {"s": "start", "a": "task", "g1": "xor", "b": "task", "g2": "xor", "e": "end"},
        [
            ("s", "a"),
            ("a", "g1"),
            ("g1", "a"),
            ("g1", "b"),
            ("b", "g2"),
            ("g2", "b"),
            ("g2", "e"),
        ],
    )
    assert compute_bound(bpmn) == 14


def test_exclusive_gateway_takes_longest_branch():
    # s, g, then the long branch b, c, then e: 5. The short branch a would be 4.
    bpmn = _bpmn(
        {"s": "start", "g": "xor", "a": "task", "b": "task", "c": "task", "e": "end"},
        [("s", "g"), ("g", "a"), ("a", "e"), ("g", "b"), ("b", "c"), ("c", "e")],
    )
    assert compute_bound(bpmn) == 5


def test_exclusive_gateway_with_separate_end_events():
    # branches end on their own end events; longest is s, g, a, b, e1 = 5
    bpmn = _bpmn(
        {"s": "start", "g": "xor", "a": "task", "b": "task", "e1": "end", "e2": "end"},
        [("s", "g"), ("g", "a"), ("a", "b"), ("b", "e1"), ("g", "e2")],
    )
    assert compute_bound(bpmn) == 5


def test_parallel_branches_are_added_and_tail_counted_once():
    # s, fork = 2; branches a (1) + b, c (2) = 3; join, t, e = 3 after the join
    bpmn = _bpmn(
        {
            "s": "start",
            "f": "par",
            "a": "task",
            "b": "task",
            "c": "task",
            "j": "par",
            "t": "task",
            "e": "end",
        },
        [
            ("s", "f"),
            ("f", "a"),
            ("f", "b"),
            ("b", "c"),
            ("a", "j"),
            ("c", "j"),
            ("j", "t"),
            ("t", "e"),
        ],
    )
    assert compute_bound(bpmn) == 8


def test_parallel_branches_ending_separately():
    # No join: s, fork, then each branch to its own end event: 2 + 2 + 2
    bpmn = _bpmn(
        {"s": "start", "f": "par", "a": "task", "e1": "end", "b": "task", "e2": "end"},
        [("s", "f"), ("f", "a"), ("a", "e1"), ("f", "b"), ("b", "e2")],
    )
    assert compute_bound(bpmn) == 6


def test_exclusive_gateway_inside_parallel_branch():
    # s, f = 2. Branch 1 is a (1). Branch 2 is g plus its longest side b, c
    # = 3. Join, e = 2. Total 2 + 1 + 3 + 2 = 8
    bpmn = _bpmn(
        {
            "s": "start",
            "f": "par",
            "a": "task",
            "g": "xor",
            "b": "task",
            "c": "task",
            "d": "task",
            "j": "par",
            "e": "end",
        },
        [
            ("s", "f"),
            ("f", "a"),
            ("f", "g"),
            ("g", "b"),
            ("b", "c"),
            ("c", "j"),
            ("g", "d"),
            ("d", "j"),
            ("a", "j"),
            ("j", "e"),
        ],
    )
    assert compute_bound(bpmn) == 8


def test_nested_parallel_gateways():
    # s, f1 = 2. Branch a = 1. Branch 2: f2, b, c, j2 = 4. Then j1, e = 2.
    # 2 + 1 + 4 + 2 = 9
    bpmn = _bpmn(
        {
            "s": "start",
            "f1": "par",
            "a": "task",
            "f2": "par",
            "b": "task",
            "c": "task",
            "j2": "par",
            "j1": "par",
            "e": "end",
        },
        [
            ("s", "f1"),
            ("f1", "a"),
            ("a", "j1"),
            ("f1", "f2"),
            ("f2", "b"),
            ("f2", "c"),
            ("b", "j2"),
            ("c", "j2"),
            ("j2", "j1"),
            ("j1", "e"),
        ],
    )
    assert compute_bound(bpmn) == 9


def test_largest_start_event_wins():
    # start 1 reaches 3 nodes, start 2 reaches 4; the larger one is the bound
    bpmn = _bpmn(
        {
            "s1": "start",
            "a": "task",
            "e1": "end",
            "s2": "start",
            "b": "task",
            "c": "task",
            "e2": "end",
        },
        [("s1", "a"), ("a", "e1"), ("s2", "b"), ("b", "c"), ("c", "e2")],
    )
    assert compute_bound(bpmn) == 4


def test_largest_process_wins():
    small = _bpmn({"s": "start", "e": "end"}, [("s", "e")])
    large = _bpmn({"s": "start", "a": "task", "e": "end"}, [("s", "a"), ("a", "e")])
    small.processes["q"] = large.processes["p"]
    assert compute_bound(small) == 3


@pytest.mark.parametrize("file", ["workflow.bpmn", "face2face_open.bpmn"])
def test_face2face(file):
    # Without loops: start, task 1, fork (3), tasks 2 and 3 (2), join,
    # exclusive gateway, task 6, fork, 7a, 7b, join, end = 13.
    # Loops: back into "payment and terms agreed" via tasks 4 or 5 (cycle of 2),
    # and into the first fork from that gateway (fork, task 2 or 3, join,
    # gateway = 4). That is 6, times 2 retries = 12.
    with open(FACE2FACE + "state.txt") as f:
        state = State.from_str(f.read()).unwrap()
    with open(FACE2FACE + file) as f:
        bpmn = bpmnmethods.from_xml(ET.fromstring(f.read()), state).unwrap()
    assert compute_bound(bpmn, retries=0) == 13
    assert compute_bound(bpmn) == 25
