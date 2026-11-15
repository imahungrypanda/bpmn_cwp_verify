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


def _node(kind: str, id: str) -> Node:
    if kind == "start":
        return StartEvent(id, id, "", "")
    if kind == "end":
        return EndEvent(id, id, "", "")
    if kind == "task":
        return Task(id, id, "")
    if kind == "xor":
        return ExclusiveGatewayNode(id, id)
    return ParallelGatewayNode(id, id)


def _process(pid: str, nodes: dict[str, str], edges: list[tuple[str, str]]) -> Process:
    """nodes maps id to kind (start, end, task, xor, par); edges are (source, target)"""
    process = Process(pid, pid)
    built = {id: _node(kind, id) for id, kind in nodes.items()}
    for node in built.values():
        process[node.id] = node
    for source, target in edges:
        flow = SequenceFlow(f"{source}_{target}", "")
        flow.source_node, flow.target_node = built[source], built[target]
        built[source].add_out_flow(flow)
        built[target].add_in_flow(flow)
        process[flow.id] = flow
    return process


def _bpmn(*processes: Process) -> Bpmn:
    bpmn = Bpmn()
    for process in processes:
        bpmn.processes[process.id] = process
    return bpmn


def _bound(nodes: dict[str, str], edges: list[tuple[str, str]], **kwargs: int) -> int:
    return get_unwinding_bound(_bpmn(_process("p", nodes, edges)), **kwargs)


def test_no_processes() -> None:
    assert get_unwinding_bound(Bpmn()) == 0


def test_straight_line() -> None:
    # start, a, b, end: one pass each
    nodes = {"s": "start", "a": "task", "b": "task", "e": "end"}
    assert _bound(nodes, [("s", "a"), ("a", "b"), ("b", "e")]) == 4


def test_exclusive_takes_longest_branch() -> None:
    # The long branch a1 a2 a3 is taken over the short branch b
    nodes = {
        "s": "start",
        "x": "xor",
        "a1": "task",
        "a2": "task",
        "a3": "task",
        "b": "task",
        "m": "xor",
        "e": "end",
    }
    edges = [
        ("s", "x"),
        ("x", "a1"),
        ("a1", "a2"),
        ("a2", "a3"),
        ("a3", "m"),
        ("x", "b"),
        ("b", "m"),
        ("m", "e"),
    ]
    # s x a1 a2 a3 m e: 7. With b it would be 5
    assert _bound(nodes, edges) == 7


def test_parallel_adds_branches_and_counts_join_tail_once() -> None:
    # s, fork, (a1 a2) + (b), join, t, e. The branches add up to 3, and t and e
    # come after the join so they count once: 1+1+3+1+1+1
    nodes = {
        "s": "start",
        "f": "par",
        "a1": "task",
        "a2": "task",
        "b": "task",
        "j": "par",
        "t": "task",
        "e": "end",
    }
    edges = [
        ("s", "f"),
        ("f", "a1"),
        ("a1", "a2"),
        ("a2", "j"),
        ("f", "b"),
        ("b", "j"),
        ("j", "t"),
        ("t", "e"),
    ]
    assert _bound(nodes, edges) == 8


def test_parallel_branches_ending_without_join() -> None:
    # s, fork, a, b, and each branch has its own end event: 1+1+2+2
    nodes = {
        "s": "start",
        "f": "par",
        "a": "task",
        "b": "task",
        "e1": "end",
        "e2": "end",
    }
    edges = [("s", "f"), ("f", "a"), ("a", "e1"), ("f", "b"), ("b", "e2")]
    assert _bound(nodes, edges) == 6


NESTED_PAR = (
    {
        "s": "start",
        "f1": "par",
        "f2": "par",
        "a": "task",
        "b": "task",
        "j2": "par",
        "c": "task",
        "j1": "par",
        "e": "end",
    },
    [
        ("s", "f1"),
        ("f1", "f2"),
        ("f2", "a"),
        ("f2", "b"),
        ("a", "j2"),
        ("b", "j2"),
        ("f1", "c"),
        ("j2", "j1"),
        ("c", "j1"),
        ("j1", "e"),
    ],
)


def test_nested_parallel() -> None:
    # s, f1, then the inner part f2 a b j2 (4) plus the other branch c (1), then
    # j1 and e once each
    assert _bound(*NESTED_PAR) == 1 + 1 + 4 + 1 + 1 + 1


def test_exclusive_inside_parallel_branch() -> None:
    # The branch with the exclusive gateway counts its longest side:
    # s, f, x, a1 a2, j, e and the other branch b: 1+1+(1+2)+1+1+1
    nodes = {
        "s": "start",
        "f": "par",
        "x": "xor",
        "a1": "task",
        "a2": "task",
        "a3": "task",
        "m": "xor",
        "b": "task",
        "j": "par",
        "e": "end",
    }
    edges = [
        ("s", "f"),
        ("f", "x"),
        ("x", "a1"),
        ("a1", "a2"),
        ("a2", "m"),
        ("x", "a3"),
        ("a3", "m"),
        ("m", "j"),
        ("f", "b"),
        ("b", "j"),
        ("j", "e"),
    ]
    # x a1 a2 m = 4 in one branch, b in the other
    assert _bound(nodes, edges) == 1 + 1 + 4 + 1 + 1 + 1


def test_loop() -> None:
    # s, x, a, e is 4. The loop comes back to x from a, and its longest cycle is
    # x, a: 2 steps, added for 2 retries
    nodes = {"s": "start", "x": "xor", "a": "task", "e": "end"}
    edges = [("s", "x"), ("x", "a"), ("a", "x"), ("x", "e")]
    assert _bound(nodes, edges) == 3 + 2 * 2


def test_loop_retries_parameter() -> None:
    nodes = {"s": "start", "x": "xor", "a": "task", "e": "end"}
    edges = [("s", "x"), ("x", "a"), ("a", "x"), ("x", "e")]
    # s x e is 3, the cycle x a is 2
    assert _bound(nodes, edges, retries=0) == 3
    assert _bound(nodes, edges, retries=1) == 5
    assert _bound(nodes, edges, retries=5) == 13


def test_loop_takes_longest_cycle() -> None:
    # Two loops back to x: x a (2), and x b1 b2 (3). Only the longest is added
    nodes = {
        "s": "start",
        "x": "xor",
        "a": "task",
        "b1": "task",
        "b2": "task",
        "e": "end",
    }
    edges = [
        ("s", "x"),
        ("x", "a"),
        ("a", "x"),
        ("x", "b1"),
        ("b1", "b2"),
        ("b2", "x"),
        ("x", "e"),
    ]
    # The loops are cut, so the path to the end is s x e: 3. Of the cycles through
    # x, the longest is 3 and the other, 2, is not added
    assert _bound(nodes, edges) == 3 + 3 * 2


def test_separate_loops_add_up() -> None:
    # Loop one (x1, a) and loop two (x2, b) are different nodes, so each adds
    # its own cycle: s x1 x2 e is 4, plus (2 + 2) * 2
    nodes = {
        "s": "start",
        "x1": "xor",
        "a": "task",
        "x2": "xor",
        "b": "task",
        "e": "end",
    }
    edges = [
        ("s", "x1"),
        ("x1", "a"),
        ("a", "x1"),
        ("x1", "x2"),
        ("x2", "b"),
        ("b", "x2"),
        ("x2", "e"),
    ]
    assert _bound(nodes, edges) == 4 + 4 * 2


def test_nested_loops() -> None:
    # Outer loop head o, inner loop head i. Path s o i e is 4. The outer cycle is
    # o i a (3, going out through the inner gateway), the inner cycle is i b (2)
    nodes = {
        "s": "start",
        "o": "xor",
        "i": "xor",
        "b": "task",
        "a": "task",
        "e": "end",
    }
    edges = [
        ("s", "o"),
        ("o", "i"),
        ("i", "b"),
        ("b", "i"),
        ("i", "a"),
        ("a", "o"),
        ("i", "e"),
    ]
    assert _bound(nodes, edges) == 4 + (3 + 2) * 2


def test_loop_through_parallel_gateways() -> None:
    # s, f, (a) + (b), j, x, e: 1+1+2+1+1+1 = 7. x loops back to f, and the cycle
    # follows one branch: f a j x, 4 steps
    nodes = {
        "s": "start",
        "f": "par",
        "a": "task",
        "b": "task",
        "j": "par",
        "x": "xor",
        "e": "end",
    }
    edges = [
        ("s", "f"),
        ("f", "a"),
        ("f", "b"),
        ("a", "j"),
        ("b", "j"),
        ("j", "x"),
        ("x", "f"),
        ("x", "e"),
    ]
    assert _bound(nodes, edges) == 7 + 4 * 2


def test_largest_start_event_and_process_win() -> None:
    short = _process("short", {"s": "start", "e": "end"}, [("s", "e")])
    long = _process(
        "long",
        {"s": "start", "a": "task", "b": "task", "e": "end", "s2": "start"},
        [("s", "a"), ("a", "b"), ("b", "e"), ("s2", "e")],
    )
    # Two start events in "long": 4 steps from s, 2 from s2. "short" has 2
    assert get_unwinding_bound(_bpmn(short)) == 2
    assert get_unwinding_bound(_bpmn(long)) == 4
    assert get_unwinding_bound(_bpmn(short, long)) == 4


@pytest.mark.parametrize("file", ["workflow.bpmn", "face2face_open.bpmn"])
def test_face2face(file: str) -> None:
    # Without the loops: start, task 1, fork, tasks 2 and 3, join, gateway, task 6,
    # fork, tasks 7a and 7b, join, end = 13. The gateway loops back to itself
    # through the repeat tasks (cycle of 2) and to the first fork (cycle of 4: the
    # fork, one branch, the join, the gateway). (2 + 4) * 2 retries = 12
    with open(FACE2FACE + "state.txt") as f:
        state = State.from_str(f.read()).unwrap()
    bpmn = bpmnmethods.from_xml(parse(FACE2FACE + file).getroot(), state).unwrap()
    assert get_unwinding_bound(bpmn) == 25
    assert get_unwinding_bound(bpmn, retries=0) == 13
