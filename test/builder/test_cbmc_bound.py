# type: ignore
import xml.etree.ElementTree as ET

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


def _event(cls, id):
    return cls(id, id, "", "")


def _task(id):
    return Task(id, id, "")


def _gateway(kind, id):
    return {"x": ExclusiveGatewayNode, "p": ParallelGatewayNode}[kind](id, id)


def _build(nodes, edges, extra_processes=()):
    """
    nodes: list of (kind, id) with kind in s, t, e, x, p.
    edges: list of (source id, target id).
    """
    makers = {
        "s": lambda i: _event(StartEvent, i),
        "e": lambda i: _event(EndEvent, i),
        "t": _task,
        "x": lambda i: _gateway("x", i),
        "p": lambda i: _gateway("p", i),
    }
    bpmn = Bpmn()
    for pid, pnodes, pedges in [("proc", nodes, edges), *extra_processes]:
        process = Process(pid, pid)
        by_id = {}
        for kind, id in pnodes:
            by_id[id] = makers[kind](id)
            process[id] = by_id[id]
        for source, target in pedges:
            flow = SequenceFlow(f"{source}->{target}", "")
            flow.source_node = by_id[source]
            flow.target_node = by_id[target]
            by_id[source].add_out_flow(flow)
            by_id[target].add_in_flow(flow)
            process[flow.id] = flow
        bpmn.processes[pid] = process
    return bpmn


def test_straight_line():
    # start, t1, t2, end: four nodes, four passes, and no loop to add to that.
    bpmn = _build(
        [("s", "s"), ("t", "t1"), ("t", "t2"), ("e", "e")],
        [("s", "t1"), ("t1", "t2"), ("t2", "e")],
    )
    assert compute_bound(bpmn) == 4


def test_no_processes():
    assert compute_bound(Bpmn()) == 0


def test_loop_adds_cycle_times_retries():
    # Path s, t1, x, e is 4. The cycle x -> t2 -> x has two nodes, so with the
    # default two retries it adds 2 * 2.
    bpmn = _build(
        [("s", "s"), ("t", "t1"), ("x", "x"), ("t", "t2"), ("e", "e")],
        [("s", "t1"), ("t1", "x"), ("x", "e"), ("x", "t2"), ("t2", "x")],
    )
    assert compute_bound(bpmn) == 4 + 2 * 2


def test_retries_parameter():
    # Same graph as above: the path is 4 and the cycle is 2 nodes long.
    bpmn = _build(
        [("s", "s"), ("t", "t1"), ("x", "x"), ("t", "t2"), ("e", "e")],
        [("s", "t1"), ("t1", "x"), ("x", "e"), ("x", "t2"), ("t2", "x")],
    )
    assert compute_bound(bpmn, retries=0) == 4
    assert compute_bound(bpmn, retries=5) == 4 + 5 * 2


def test_loop_back_edge_is_not_a_path_to_the_end():
    # The only way out of the loop is through the end event: s, t, x, e = 4.
    # The edge x -> t is cut, and the cycle t, x is 2 nodes: 4 + 2 * 2.
    bpmn = _build(
        [("s", "s"), ("t", "t"), ("x", "x"), ("e", "e")],
        [("s", "t"), ("t", "x"), ("x", "t"), ("x", "e")],
    )
    assert compute_bound(bpmn) == 8


def test_exclusive_gateway_takes_longest_branch():
    # s, x, then either the long branch (t1, t2) or the short one (t3), then e.
    # Long: s, x, t1, t2, e = 5.
    bpmn = _build(
        [("s", "s"), ("x", "x"), ("t", "t1"), ("t", "t2"), ("t", "t3"), ("e", "e")],
        [
            ("s", "x"),
            ("x", "t1"),
            ("t1", "t2"),
            ("t2", "e"),
            ("x", "t3"),
            ("t3", "e"),
        ],
    )
    assert compute_bound(bpmn) == 5


def test_parallel_branches_are_added_and_join_counted_once():
    # s, fork, [t1, t2 | t3], join, t4, e. Branch steps add: 2 + 1.
    # s + fork + 3 + join + t4 + e = 8.
    bpmn = _build(
        [
            ("s", "s"),
            ("p", "fork"),
            ("t", "t1"),
            ("t", "t2"),
            ("t", "t3"),
            ("p", "join"),
            ("t", "t4"),
            ("e", "e"),
        ],
        [
            ("s", "fork"),
            ("fork", "t1"),
            ("t1", "t2"),
            ("t2", "join"),
            ("fork", "t3"),
            ("t3", "join"),
            ("join", "t4"),
            ("t4", "e"),
        ],
    )
    assert compute_bound(bpmn) == 8


def test_exclusive_choice_inside_parallel_branch():
    # One branch is t1 or (t2, t3), whichever is longer: 2 steps and the
    # gateway makes 3. The other is t4. s + fork + (x + 2 + 1) + join + e = 8.
    bpmn = _build(
        [
            ("s", "s"),
            ("p", "fork"),
            ("x", "x"),
            ("t", "t1"),
            ("t", "t2"),
            ("t", "t3"),
            ("t", "t4"),
            ("p", "join"),
            ("e", "e"),
        ],
        [
            ("s", "fork"),
            ("fork", "x"),
            ("x", "t1"),
            ("t1", "join"),
            ("x", "t2"),
            ("t2", "t3"),
            ("t3", "join"),
            ("fork", "t4"),
            ("t4", "join"),
            ("join", "e"),
        ],
    )
    assert compute_bound(bpmn) == 8


def test_nested_parallel():
    # s, f1, [ f2 [a | b] j2 | c ], j1, e.
    # Inner: f2 + a + b + j2 = 4. Outer branches: 4 + c(1). s + f1 + 5 + j1 + e = 9.
    bpmn = _build(
        [
            ("s", "s"),
            ("p", "f1"),
            ("p", "f2"),
            ("t", "a"),
            ("t", "b"),
            ("p", "j2"),
            ("t", "c"),
            ("p", "j1"),
            ("e", "e"),
        ],
        [
            ("s", "f1"),
            ("f1", "f2"),
            ("f2", "a"),
            ("a", "j2"),
            ("f2", "b"),
            ("b", "j2"),
            ("j2", "j1"),
            ("f1", "c"),
            ("c", "j1"),
            ("j1", "e"),
        ],
    )
    assert compute_bound(bpmn) == 9


def test_nested_loops_each_add_their_own_cycle():
    # s, x1, x2, e: 4 on the path. Inner loop x2 -> t2 -> x2 has 2 nodes. Outer
    # loop x1 -> x2 -> t1 -> x1 has 3 nodes. 4 + 2 * (2 + 3) = 14.
    bpmn = _build(
        [("s", "s"), ("x", "x1"), ("x", "x2"), ("t", "t1"), ("t", "t2"), ("e", "e")],
        [
            ("s", "x1"),
            ("x1", "x2"),
            ("x2", "e"),
            ("x2", "t2"),
            ("t2", "x2"),
            ("x2", "t1"),
            ("t1", "x1"),
        ],
    )
    assert compute_bound(bpmn) == 14


def test_largest_over_start_events_and_processes():
    long_process = (
        "other",
        [("s", "s2"), ("t", "a"), ("t", "b"), ("t", "c"), ("e", "e2")],
        [("s2", "a"), ("a", "b"), ("b", "c"), ("c", "e2")],
    )
    bpmn = _build(
        [("s", "s"), ("e", "e")],
        [("s", "e")],
        extra_processes=[long_process],
    )
    # 2 in the short process, 5 in the long one.
    assert compute_bound(bpmn) == 5


@pytest.mark.parametrize("file", ["workflow.bpmn", "face2face_open.bpmn"])
def test_face2face(file):
    # Path: start, t1, fork, t2, t3, join, x, t6, fork, t7a, t7b, join, end = 13.
    # Loops: back to the first fork through x: cycle fork, t2, join, x = 4;
    # back to x through t4 or t5: cycle 2. 13 + 2 * (4 + 2) = 25.
    state = State.from_str(open(FACE2FACE + "state.txt").read()).unwrap()
    bpmn = bpmnmethods.from_xml(ET.parse(FACE2FACE + file).getroot(), state).unwrap()
    assert compute_bound(bpmn) == 25
