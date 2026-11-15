import pytest
from returns.unsafe import unsafe_perform_io

from bpmncwpverify.builder.cbmc_bound import compute_unwinding_bound
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
from bpmncwpverify.util.file import element_tree_from_string

FACE2FACE = "./test/resources/face2face/"


class _Graph:
    """Builds a one-process Bpmn from node kinds and (source, target) pairs"""

    def __init__(self, kinds: dict[str, str], edges: list[tuple[str, str]]) -> None:
        make = {
            "start": lambda i: StartEvent(i, i, "", ""),
            "end": lambda i: EndEvent(i, i, "", ""),
            "task": lambda i: Task(i, i, ""),
            "xor": lambda i: ExclusiveGatewayNode(i, i),
            "par": lambda i: ParallelGatewayNode(i, i),
        }
        self.process = Process("p", "p")
        self.nodes: dict[str, Node] = {}
        for id, kind in kinds.items():
            self.nodes[id] = make[kind](id)
            self.process[id] = self.nodes[id]
        for source, target in edges:
            flow = SequenceFlow(f"{source}_{target}", "")
            flow.source_node = self.nodes[source]
            flow.target_node = self.nodes[target]
            self.nodes[source].add_out_flow(flow)
            self.nodes[target].add_in_flow(flow)
            self.process[flow.id] = flow
        self.bpmn = Bpmn()
        self.bpmn.processes["p"] = self.process


def _bound(kinds: dict[str, str], edges: list[tuple[str, str]], **kw: int) -> int:
    return compute_unwinding_bound(_Graph(kinds, edges).bpmn, **kw)


def test_empty_bpmn_needs_no_passes():
    # nothing can fire
    assert compute_unwinding_bound(Bpmn()) == 0


def test_straight_line():
    # start, a, b, end each fire once
    kinds = {"s": "start", "a": "task", "b": "task", "e": "end"}
    assert _bound(kinds, [("s", "a"), ("a", "b"), ("b", "e")]) == 4


def test_exclusive_gateway_takes_longest_branch():
    # s, x, then the longer branch a1, a2, then e: 5. The short branch b is 4
    kinds = {
        "s": "start",
        "x": "xor",
        "a1": "task",
        "a2": "task",
        "b": "task",
        "m": "xor",
        "e": "end",
    }
    edges = [
        ("s", "x"),
        ("x", "a1"),
        ("a1", "a2"),
        ("a2", "m"),
        ("x", "b"),
        ("b", "m"),
        ("m", "e"),
    ]
    # s, x, a1, a2, m, e
    assert _bound(kinds, edges) == 6


def test_exclusive_gateway_branches_ending_apart():
    # one branch ends at e1 after 3 steps (s, x, e1); the other at e2 after 4
    kinds = {"s": "start", "x": "xor", "e1": "end", "a": "task", "e2": "end"}
    edges = [("s", "x"), ("x", "e1"), ("x", "a"), ("a", "e2")]
    assert _bound(kinds, edges) == 4


def test_parallel_branches_are_added_and_join_counted_once():
    # s, fork, a, b, c (3 branch steps added, not max), join, t, e = 8
    kinds = {
        "s": "start",
        "f": "par",
        "a": "task",
        "b": "task",
        "c": "task",
        "j": "par",
        "t": "task",
        "e": "end",
    }
    edges = [
        ("s", "f"),
        ("f", "a"),
        ("f", "b"),
        ("f", "c"),
        ("a", "j"),
        ("b", "j"),
        ("c", "j"),
        ("j", "t"),
        ("t", "e"),
    ]
    assert _bound(kinds, edges) == 8


def test_parallel_branches_of_different_lengths():
    # s, fork, a1, a2, b, join, e: the branches 2 + 1 are added = 7
    kinds = {
        "s": "start",
        "f": "par",
        "a1": "task",
        "a2": "task",
        "b": "task",
        "j": "par",
        "e": "end",
    }
    edges = [
        ("s", "f"),
        ("f", "a1"),
        ("a1", "a2"),
        ("a2", "j"),
        ("f", "b"),
        ("b", "j"),
        ("j", "e"),
    ]
    assert _bound(kinds, edges) == 7


def test_parallel_branches_ending_without_a_join():
    # no join, so both branches run to their own end: s, fork, a, e1, b, e2
    kinds = {
        "s": "start",
        "f": "par",
        "a": "task",
        "b": "task",
        "e1": "end",
        "e2": "end",
    }
    edges = [("s", "f"), ("f", "a"), ("f", "b"), ("a", "e1"), ("b", "e2")]
    assert _bound(kinds, edges) == 6


def test_exclusive_gateway_inside_parallel_branch():
    # s, fork, branch 1 (x, long1, long2, m: the longer exclusive branch is
    # used) + branch 2 (b) = 5 added, join, e: 1+1+5+1+1 = 9
    kinds = {
        "s": "start",
        "f": "par",
        "x": "xor",
        "l1": "task",
        "l2": "task",
        "sh": "task",
        "m": "xor",
        "b": "task",
        "j": "par",
        "e": "end",
    }
    edges = [
        ("s", "f"),
        ("f", "x"),
        ("x", "l1"),
        ("l1", "l2"),
        ("l2", "m"),
        ("x", "sh"),
        ("sh", "m"),
        ("m", "j"),
        ("f", "b"),
        ("b", "j"),
        ("j", "e"),
    ]
    assert _bound(kinds, edges) == 9


def test_nested_parallel_gateways():
    # outer fork branches: [inner fork, c, d, inner join] and [b]
    # s, F1, (F2, c, d, J2) + b, J1, e = 1+1+4+1+1+1 = 9
    kinds = {
        "s": "start",
        "f1": "par",
        "f2": "par",
        "c": "task",
        "d": "task",
        "j2": "par",
        "b": "task",
        "j1": "par",
        "e": "end",
    }
    edges = [
        ("s", "f1"),
        ("f1", "f2"),
        ("f2", "c"),
        ("f2", "d"),
        ("c", "j2"),
        ("d", "j2"),
        ("j2", "j1"),
        ("f1", "b"),
        ("b", "j1"),
        ("j1", "e"),
    ]
    assert _bound(kinds, edges) == 9


def _loop():
    # s -> a -> x -> b -> e, with x -> a looping back
    kinds = {"s": "start", "a": "task", "x": "xor", "b": "task", "e": "end"}
    edges = [("s", "a"), ("a", "x"), ("x", "b"), ("b", "e"), ("x", "a")]
    return kinds, edges


def test_loop_adds_its_cycle_times_default_retries():
    # path s, a, x, b, e = 5. The cycle a, x is 2 steps, retried twice: +4
    assert _bound(*_loop()) == 9


@pytest.mark.parametrize("retries,expected", [(0, 5), (1, 7), (3, 11)])
def test_retries_scale_the_loop(retries: int, expected: int):
    # 5 steps for the path plus 2 per retry
    assert _bound(*_loop(), retries=retries) == expected


def test_self_loop_cycle_is_one_step():
    # path s, x, e = 3, the cycle is x alone: +2 with 2 retries
    kinds = {"s": "start", "x": "xor", "e": "end"}
    assert _bound(kinds, [("s", "x"), ("x", "x"), ("x", "e")]) == 5


def test_loop_takes_longest_cycle_through_the_node():
    # two cycles through x: via a (2 steps: a, x) and via b1, b2 (3 steps:
    # b1, b2, x). Path s, x, e = 3; the 3-step cycle is retried twice: +6.
    # the shorter cycle's flow comes back into x too, but only the longest
    # cycle through x is added
    kinds = {
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
    assert _bound(kinds, edges) == 9


def test_two_loops_are_added_separately():
    # path s, x, y, e = 4. x's cycle is x, a (2). y's cycle is y, b (2).
    # +4 for each loop: 12
    kinds = {
        "s": "start",
        "x": "xor",
        "a": "task",
        "y": "xor",
        "b": "task",
        "e": "end",
    }
    edges = [
        ("s", "x"),
        ("x", "a"),
        ("a", "x"),
        ("x", "y"),
        ("y", "b"),
        ("b", "y"),
        ("y", "e"),
    ]
    assert _bound(kinds, edges) == 12


def test_loop_flow_does_not_count_as_a_path_to_the_end():
    # the only way out of the loop body is back, so the path is s, x, e = 3
    # and the cycle x, a is 2: 3 + 4
    kinds = {"s": "start", "x": "xor", "a": "task", "e": "end"}
    edges = [("s", "x"), ("x", "a"), ("a", "x"), ("x", "e")]
    assert _bound(kinds, edges) == 7


def test_loop_around_a_parallel_section():
    kinds = {
        "s": "start",
        "x": "xor",
        "f": "par",
        "a": "task",
        "b": "task",
        "j": "par",
        "y": "xor",
        "e": "end",
    }
    edges = [
        ("s", "x"),
        ("x", "f"),
        ("f", "a"),
        ("f", "b"),
        ("a", "j"),
        ("b", "j"),
        ("j", "y"),
        ("y", "x"),
        ("y", "e"),
    ]
    # the loop goes from y back to x. path s, x, f, a, b, j, y, e = 8 (branches
    # added); the cycle x, f, a, j, y = 5 (a cycle counts one branch), twice: +10
    assert _bound(kinds, edges) == 18


def test_largest_start_event_wins():
    # starts s1 (3 steps) and s2 (2 steps) share the same end
    kinds = {"s1": "start", "s2": "start", "a": "task", "e": "end"}
    edges = [("s1", "a"), ("a", "e"), ("s2", "e")]
    assert _bound(kinds, edges) == 3


def test_largest_process_wins():
    short = _Graph({"s": "start", "e": "end"}, [("s", "e")])
    long = _Graph(
        {"s": "start", "a": "task", "b": "task", "e": "end"},
        [("s", "a"), ("a", "b"), ("b", "e")],
    )
    bpmn = Bpmn()
    bpmn.processes["short"] = short.process
    bpmn.processes["long"] = long.process
    assert compute_unwinding_bound(bpmn) == 4


@pytest.mark.parametrize("bpmn_file", ["workflow.bpmn", "face2face_open.bpmn"])
def test_face2face(bpmn_file: str):
    # path: start, task, fork, 2 branch tasks, join, exclusive gateway, task,
    # fork, 2 branch tasks, join, end = 13.
    # Loops: the exclusive gateway's back edge to the first fork closes a
    # cycle fork, one branch task, join, gateway = 4 steps; the repeat tasks
    # close a cycle of the gateway and that task = 2 steps. (4 + 2) * 2 = 12
    with open(FACE2FACE + "state.txt") as f:
        state = State.from_str(f.read()).unwrap()
    with open(FACE2FACE + bpmn_file) as f:
        root = unsafe_perform_io(element_tree_from_string(f.read()).unwrap())
    bpmn = bpmnmethods.from_xml(root, state).unwrap()
    assert compute_unwinding_bound(bpmn) == 25
