# type: ignore
import xml.etree.ElementTree as ET

import pytest
from returns.pipeline import is_successful

from bpmncwpverify.builder.cbmc_bound import compute_unwind_bound
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


def make_bpmn(nodes, edges, processes=1):
    """
    nodes: dict of id -> kind ("start", "end", "task", "xor", "and")
    edges: list of (source id, target id)
    """
    process = Process("p", "p")
    made = {}
    for id, kind in nodes.items():
        if kind == "start":
            node = StartEvent(id, id, "", "")
        elif kind == "end":
            node = EndEvent(id, id, "", "")
        elif kind == "task":
            node = Task(id, id, "")
        elif kind == "xor":
            node = ExclusiveGatewayNode(id, id)
        else:
            node = ParallelGatewayNode(id, id)
        made[id] = node
        process[id] = node
    for source, target in edges:
        flow = SequenceFlow(f"{source}_{target}", "")
        flow.source_node = made[source]
        flow.target_node = made[target]
        made[source].add_out_flow(flow)
        made[target].add_in_flow(flow)
        process[flow.id] = flow
    bpmn = Bpmn()
    bpmn.processes[process.id] = process
    return bpmn


def test_straight_line():
    # s, t1, t2, e each fire once
    bpmn = make_bpmn(
        {"s": "start", "t1": "task", "t2": "task", "e": "end"},
        [("s", "t1"), ("t1", "t2"), ("t2", "e")],
    )
    assert compute_unwind_bound(bpmn) == 4


def test_start_and_end_only():
    bpmn = make_bpmn({"s": "start", "e": "end"}, [("s", "e")])
    assert compute_unwind_bound(bpmn) == 2


def test_empty_bpmn():
    assert compute_unwind_bound(Bpmn()) == 0


def test_exclusive_takes_longest_branch():
    # s, x, then the long branch a1 a2 (2), e = 5. The short branch b is 1.
    bpmn = make_bpmn(
        {
            "s": "start",
            "x": "xor",
            "a1": "task",
            "a2": "task",
            "b": "task",
            "m": "xor",
            "e": "end",
        },
        [
            ("s", "x"),
            ("x", "a1"),
            ("a1", "a2"),
            ("a2", "m"),
            ("x", "b"),
            ("b", "m"),
            ("m", "e"),
        ],
    )
    # s, x, a1, a2, m, e
    assert compute_unwind_bound(bpmn) == 6


def test_exclusive_branches_ending_separately():
    # s, x, then either one task and its end (2) or an end (1): 2 + 2 = 4
    bpmn = make_bpmn(
        {"s": "start", "x": "xor", "t": "task", "e1": "end", "e2": "end"},
        [("s", "x"), ("x", "t"), ("t", "e1"), ("x", "e2")],
    )
    assert compute_unwind_bound(bpmn) == 4


def test_parallel_adds_branches_and_counts_tail_once():
    # s, fork, branch a (2 tasks) + branch b (1 task), join, tail t, e
    # = 1 + 1 + (2 + 1) + 1 + 1 + 1 = 8
    bpmn = make_bpmn(
        {
            "s": "start",
            "f": "and",
            "a1": "task",
            "a2": "task",
            "b": "task",
            "j": "and",
            "t": "task",
            "e": "end",
        },
        [
            ("s", "f"),
            ("f", "a1"),
            ("a1", "a2"),
            ("a2", "j"),
            ("f", "b"),
            ("b", "j"),
            ("j", "t"),
            ("t", "e"),
        ],
    )
    assert compute_unwind_bound(bpmn) == 8


def test_exclusive_inside_parallel_branch():
    # s, fork, branch a is a choice of 1 or 2 tasks around an exclusive pair
    # (x, 2 tasks, m = 4), branch b is 1 task, join, e: 1+1+4+1+1+1 = 9
    bpmn = make_bpmn(
        {
            "s": "start",
            "f": "and",
            "x": "xor",
            "a1": "task",
            "a2": "task",
            "c": "task",
            "m": "xor",
            "b": "task",
            "j": "and",
            "e": "end",
        },
        [
            ("s", "f"),
            ("f", "x"),
            ("x", "a1"),
            ("a1", "a2"),
            ("a2", "m"),
            ("x", "c"),
            ("c", "m"),
            ("m", "j"),
            ("f", "b"),
            ("b", "j"),
            ("j", "e"),
        ],
    )
    assert compute_unwind_bound(bpmn) == 9


def test_nested_parallel():
    # s, outer fork, branch a: inner fork + (p + q) + inner join = 4,
    # branch b: 1 task, outer join, e = 1+1+4+1+1+1 = 9
    bpmn = make_bpmn(
        {
            "s": "start",
            "f1": "and",
            "f2": "and",
            "p": "task",
            "q": "task",
            "j2": "and",
            "b": "task",
            "j1": "and",
            "e": "end",
        },
        [
            ("s", "f1"),
            ("f1", "f2"),
            ("f2", "p"),
            ("f2", "q"),
            ("p", "j2"),
            ("q", "j2"),
            ("j2", "j1"),
            ("f1", "b"),
            ("b", "j1"),
            ("j1", "e"),
        ],
    )
    # s, f1, [f2, p, q, j2] + [b], j1, e
    assert compute_unwind_bound(bpmn) == 1 + 1 + 4 + 1 + 1 + 1


def test_loop_adds_retries_of_cycle():
    # s, t, x, e is 4 on the path. The loop x -> r -> x is a cycle of 2 nodes
    # (x and r), retried twice: 4 + 2 * 2 = 8
    bpmn = make_bpmn(
        {"s": "start", "t": "task", "x": "xor", "r": "task", "e": "end"},
        [("s", "t"), ("t", "x"), ("x", "r"), ("r", "x"), ("x", "e")],
    )
    assert compute_unwind_bound(bpmn) == 8


def test_loop_retries_parameter():
    bpmn = make_bpmn(
        {"s": "start", "t": "task", "x": "xor", "r": "task", "e": "end"},
        [("s", "t"), ("t", "x"), ("x", "r"), ("r", "x"), ("x", "e")],
    )
    assert compute_unwind_bound(bpmn, retries=0) == 4
    assert compute_unwind_bound(bpmn, retries=1) == 6
    assert compute_unwind_bound(bpmn, retries=5) == 14


def test_loop_back_to_earlier_task_takes_longest_cycle():
    # s, a, b, x, e = 5 on the path. The loop returns to a through x -> a:
    # the cycle through a is a, b, x = 3 nodes. 5 + 2 * 3 = 11
    bpmn = make_bpmn(
        {"s": "start", "a": "task", "b": "task", "x": "xor", "e": "end"},
        [("s", "a"), ("a", "b"), ("b", "x"), ("x", "a"), ("x", "e")],
    )
    assert compute_unwind_bound(bpmn) == 11


def test_two_loops_add():
    # s, x1, x2, e = 4; loop one x1 -> r1 -> x1 is 2 nodes, loop two x2 -> r2 -> x2
    # is 2 nodes: 4 + 2 * (2 + 2) = 12
    bpmn = make_bpmn(
        {
            "s": "start",
            "x1": "xor",
            "r1": "task",
            "x2": "xor",
            "r2": "task",
            "e": "end",
        },
        [
            ("s", "x1"),
            ("x1", "r1"),
            ("r1", "x1"),
            ("x1", "x2"),
            ("x2", "r2"),
            ("r2", "x2"),
            ("x2", "e"),
        ],
    )
    assert compute_unwind_bound(bpmn) == 12


def test_loop_around_parallel_section_counts_both_branches():
    # Path: s, x, f, a, b, j, y, e = 8. y loops back to x. The cycle is one
    # path round: x, f, a, j, y = 5 nodes (the other branch is not added, a
    # cycle is a single path). 8 + 2 * 5 = 18
    bpmn = make_bpmn(
        {
            "s": "start",
            "x": "xor",
            "f": "and",
            "a": "task",
            "b": "task",
            "j": "and",
            "y": "xor",
            "e": "end",
        },
        [
            ("s", "x"),
            ("x", "f"),
            ("f", "a"),
            ("f", "b"),
            ("a", "j"),
            ("b", "j"),
            ("j", "y"),
            ("y", "x"),
            ("y", "e"),
        ],
    )
    assert compute_unwind_bound(bpmn) == 18


def test_nested_loops():
    # Path: s, x1, x2, y, e = 5. Inner loop x2 -> r2 -> x2 is 2 nodes. Outer
    # loop returns to x1 from y: x1, x2, y = 3 nodes. 5 + 2 * (2 + 3) = 15
    bpmn = make_bpmn(
        {
            "s": "start",
            "x1": "xor",
            "x2": "xor",
            "r2": "task",
            "y": "xor",
            "e": "end",
        },
        [
            ("s", "x1"),
            ("x1", "x2"),
            ("x2", "r2"),
            ("r2", "x2"),
            ("x2", "y"),
            ("y", "x1"),
            ("y", "e"),
        ],
    )
    assert compute_unwind_bound(bpmn) == 15


def test_several_start_events_take_largest():
    # one process, two starts: the short one is 2 steps, the long one is 4
    bpmn = make_bpmn(
        {
            "s1": "start",
            "e1": "end",
            "s2": "start",
            "t": "task",
            "u": "task",
            "e2": "end",
        },
        [("s1", "e1"), ("s2", "t"), ("t", "u"), ("u", "e2")],
    )
    assert compute_unwind_bound(bpmn) == 4


def test_several_processes_take_largest():
    short = make_bpmn({"s": "start", "e": "end"}, [("s", "e")])
    long = make_bpmn({"s": "start", "t": "task", "e": "end"}, [("s", "t"), ("t", "e")])
    long.processes["q"] = long.processes.pop("p")
    short.processes.update(long.processes)
    assert compute_unwind_bound(short) == 3


@pytest.mark.parametrize("name", ["workflow.bpmn", "face2face_open.bpmn"])
def test_face2face(name):
    # Path with loops cut: start, task 1, fork, task 2 + task 3, join,
    # exclusive gateway, task 6, fork, 7a + 7b, join, end = 13.
    # Loop back to the first fork, straight from the gateway: the cycle is
    # fork, task 2, join, gateway = 4 nodes.
    # Loops back to the gateway from tasks 4 and 5: gateway, task 4 = 2 nodes.
    # 13 + 2 * (4 + 2) = 25
    state = State.from_str(open(FACE2FACE + "state.txt").read()).unwrap()
    root = ET.parse(FACE2FACE + name).getroot()
    result = bpmnmethods.from_xml(root, state)
    assert is_successful(result)
    assert compute_unwind_bound(result.unwrap()) == 25
