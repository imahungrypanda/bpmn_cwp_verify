# type: ignore
from xml.etree.ElementTree import parse

import pytest

from bpmncwpverify.builder.cbmc_bound import compute_unwinding_bound
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

FACE2FACE = "./test/resources/face2face/"


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


def _bpmn(*processes):
    """
    Each process is (nodes, edges): nodes maps id to kind (start, end, task, xor,
    par), and edges is a list of (source, target) ids.
    """
    bpmn = Bpmn()
    for i, (kinds, edges) in enumerate(processes):
        process = Process(f"p{i}", f"p{i}")
        nodes = {id: _node(kind, id) for id, kind in kinds.items()}
        for node in nodes.values():
            process[node.id] = node
        for j, (source, target) in enumerate(edges):
            flow = SequenceFlow(f"p{i}_f{j}", "")
            flow.source_node, flow.target_node = nodes[source], nodes[target]
            nodes[source].add_out_flow(flow)
            nodes[target].add_in_flow(flow)
            process[flow.id] = flow
        bpmn.processes[process.id] = process
    return bpmn


def test_empty_bpmn_has_bound_zero():
    # nothing can fire
    assert compute_unwinding_bound(Bpmn()) == 0


def test_straight_line():
    # start, task, task, end: 4 nodes, 4 steps
    bpmn = _bpmn(
        (
            {"s": "start", "a": "task", "b": "task", "e": "end"},
            [("s", "a"), ("a", "b"), ("b", "e")],
        )
    )
    assert compute_unwinding_bound(bpmn) == 4


def test_exclusive_gateway_takes_longest_branch():
    # s, x, then branch a-b (2) or c (1), then merge task m and end e:
    # s x a b m e = 6, since only one branch runs
    bpmn = _bpmn(
        (
            {
                "s": "start",
                "x": "xor",
                "a": "task",
                "b": "task",
                "c": "task",
                "m": "task",
                "e": "end",
            },
            [
                ("s", "x"),
                ("x", "a"),
                ("a", "b"),
                ("b", "m"),
                ("x", "c"),
                ("c", "m"),
                ("m", "e"),
            ],
        )
    )
    assert compute_unwinding_bound(bpmn) == 6


def test_parallel_branches_add_and_join_tail_counts_once():
    # s, fork, branch a (1), branch b-c (2), join, tail t, end e:
    # s fork a b c join t e = 8; every branch step takes a pass of its own
    bpmn = _bpmn(
        (
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
    )
    assert compute_unwinding_bound(bpmn) == 8


def test_simple_loop_adds_cycle_times_retries():
    # s x t e, with t looping back to x. Path: s x t e = 4 steps (t is
    # reached once, the back edge is cut). Cycle through x is x, t = 2.
    bpmn = _bpmn(
        (
            {"s": "start", "x": "xor", "t": "task", "e": "end"},
            [("s", "x"), ("x", "t"), ("t", "x"), ("x", "e")],
        )
    )
    assert compute_unwinding_bound(bpmn, retries=0) == 3
    assert compute_unwinding_bound(bpmn) == 3 + 2 * 2
    assert compute_unwinding_bound(bpmn, retries=5) == 3 + 2 * 5


def test_loop_back_to_start_of_work_uses_longest_cycle():
    # s x a b y e; y goes back to x either directly (cycle x a b y = 4)
    # or through c (cycle x a b y c = 5). Longest is 5.
    # Path: s x a b y e = 6, with c a dead end after y: s x a b y c = 6 too.
    bpmn = _bpmn(
        (
            {
                "s": "start",
                "x": "xor",
                "a": "task",
                "b": "task",
                "y": "xor",
                "c": "task",
                "e": "end",
            },
            [
                ("s", "x"),
                ("x", "a"),
                ("a", "b"),
                ("b", "y"),
                ("y", "x"),
                ("y", "c"),
                ("c", "x"),
                ("y", "e"),
            ],
        )
    )
    assert compute_unwinding_bound(bpmn, retries=1) == 6 + 5


def test_nested_loops_add_instead_of_multiplying():
    # s o i t e. i loops on itself through t (cycle i t = 2) and o loops
    # through i (cycle o i = 2, the inner loop is counted on its own).
    # Path: s o i t e = 5 with both back edges cut, so 5 + (2 + 2) * 2 = 13
    bpmn = _bpmn(
        (
            {"s": "start", "o": "xor", "i": "xor", "t": "task", "e": "end"},
            [("s", "o"), ("o", "i"), ("i", "t"), ("t", "i"), ("i", "o"), ("t", "e")],
        )
    )
    assert compute_unwinding_bound(bpmn) == 13


def test_loop_through_parallel_fork():
    # s f a b j e, f and j parallel, with a loop from after the join back to f
    # through exclusive x. Path: s f a b j x e = 7 (branches add: a and b).
    # Cycle through f: f a j x = 4. Retries 2: 7 + 8 = 15.
    bpmn = _bpmn(
        (
            {
                "s": "start",
                "f": "par",
                "a": "task",
                "b": "task",
                "j": "par",
                "x": "xor",
                "e": "end",
            },
            [
                ("s", "f"),
                ("f", "a"),
                ("f", "b"),
                ("a", "j"),
                ("b", "j"),
                ("j", "x"),
                ("x", "f"),
                ("x", "e"),
            ],
        )
    )
    assert compute_unwinding_bound(bpmn) == 15


def test_nested_forks():
    # s f1 [a | f2 [b | c] j2 d] j1 e
    # s f1 a f2 b c j2 d j1 e = 10: the inner branches add, and j2's tail d
    # counts once, then j1's tail e once
    bpmn = _bpmn(
        (
            {
                "s": "start",
                "f1": "par",
                "a": "task",
                "f2": "par",
                "b": "task",
                "c": "task",
                "j2": "par",
                "d": "task",
                "j1": "par",
                "e": "end",
            },
            [
                ("s", "f1"),
                ("f1", "a"),
                ("f1", "f2"),
                ("f2", "b"),
                ("f2", "c"),
                ("b", "j2"),
                ("c", "j2"),
                ("j2", "d"),
                ("a", "j1"),
                ("d", "j1"),
                ("j1", "e"),
            ],
        )
    )
    assert compute_unwinding_bound(bpmn) == 10


def test_exclusive_choice_inside_parallel_branch():
    # s f [x (a | a2 a3) | b] j e: the branch with x takes its longer side,
    # x a2 a3 = 3, plus b = 1: s f x a2 a3 b j e = 8
    bpmn = _bpmn(
        (
            {
                "s": "start",
                "f": "par",
                "x": "xor",
                "a": "task",
                "a2": "task",
                "a3": "task",
                "b": "task",
                "j": "par",
                "e": "end",
            },
            [
                ("s", "f"),
                ("f", "x"),
                ("f", "b"),
                ("x", "a"),
                ("x", "a2"),
                ("a2", "a3"),
                ("a", "j"),
                ("a3", "j"),
                ("b", "j"),
                ("j", "e"),
            ],
        )
    )
    assert compute_unwinding_bound(bpmn) == 8


def test_largest_process_and_start_event_win():
    # process 0 is 3 steps (s a e); process 1 has two start events, one with
    # 2 steps (s e) and one with 5 (s2 a b c e). The largest is 5.
    bpmn = _bpmn(
        (
            {"s": "start", "a": "task", "e": "end"},
            [("s", "a"), ("a", "e")],
        ),
        (
            {
                "s": "start",
                "e": "end",
                "s2": "start",
                "a": "task",
                "b": "task",
                "c": "task",
                "e2": "end",
            },
            [("s", "e"), ("s2", "a"), ("a", "b"), ("b", "c"), ("c", "e2")],
        ),
    )
    assert compute_unwinding_bound(bpmn) == 5


@pytest.mark.parametrize("file", ["workflow.bpmn", "face2face_open.bpmn"])
def test_face2face(file):
    # Without loops the longest path is 13: start, task, fork, 2 branch tasks,
    # join, exclusive, then task, fork, 2 tasks, join, end. The loops are the
    # fork-to-exclusive cycle (4 nodes) and the tasks that loop back to the
    # exclusive gateway (2 nodes), 6 * 2 retries = 12, so 25.
    with open(FACE2FACE + "state.txt") as state_file:
        state = State.from_str(state_file.read()).unwrap()
    bpmn = bpmnmethods.from_xml(parse(FACE2FACE + file).getroot(), state).unwrap()
    assert compute_unwinding_bound(bpmn, retries=0) == 13
    assert compute_unwinding_bound(bpmn) == 25
