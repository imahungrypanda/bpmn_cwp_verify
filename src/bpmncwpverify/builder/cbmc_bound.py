from functools import cache

from bpmncwpverify.core.bpmn import (
    Bpmn,
    Node,
    ParallelGatewayNode,
    StartEvent,
    Task,
)

DEFAULT_RETRIES = 2

# (steps, join): steps taken before stopping, and the parallel join stopped at
_Walk = tuple[int, Node | None]


def _successors(node: Node) -> list[Node]:
    successors = [flow.target_node for flow in node.out_flows]
    if isinstance(node, Task):
        successors.extend(node.msg_boundary_events)
    return successors


def _find_back_edges(start: Node) -> set[tuple[Node, Node]]:
    """
    Find the edges that go back to a node that is already on the path
    """
    back_edges: set[tuple[Node, Node]] = set()
    on_path: set[Node] = set()
    visited: set[Node] = set()

    def dfs(node: Node) -> None:
        visited.add(node)
        on_path.add(node)
        for successor in _successors(node):
            if successor in on_path:
                back_edges.add((node, successor))
            elif successor not in visited:
                dfs(successor)
        on_path.remove(node)

    dfs(start)
    return back_edges


class _AcyclicGraph:
    """
    The part of a process that can be reached from a start event, without
    its loops
    """

    def __init__(self, start: StartEvent) -> None:
        self.back_edges = _find_back_edges(start)
        self._successors: dict[Node, list[Node]] = {}
        self._in_degree: dict[Node, int] = {}
        self._build(start)

    def _build(self, start: Node) -> None:
        pending = [start]
        while pending:
            node = pending.pop()
            if node in self._successors:
                continue
            successors = [
                s for s in _successors(node) if (node, s) not in self.back_edges
            ]
            self._successors[node] = successors
            for successor in successors:
                self._in_degree[successor] = self._in_degree.get(successor, 0) + 1
                pending.append(successor)

    def successors(self, node: Node) -> list[Node]:
        return self._successors[node]

    def is_join(self, node: Node) -> bool:
        return (
            isinstance(node, ParallelGatewayNode) and self._in_degree.get(node, 0) > 1
        )

    def is_fork(self, node: Node) -> bool:
        return isinstance(node, ParallelGatewayNode) and len(self.successors(node)) > 1


def _longest_path(graph: _AcyclicGraph, start: Node) -> int:
    """
    Steps on the longest path from the start event to an end event
    """

    @cache
    def walk(node: Node, in_fork: bool) -> _Walk:
        # Inside a fork, a join ends the branch. It is counted after the fork
        if in_fork and graph.is_join(node):
            return 0, node
        return through(node, in_fork)

    def through(node: Node, in_fork: bool) -> _Walk:
        """
        Steps from this node on, counting it
        """
        successors = graph.successors(node)
        if not successors:
            return 1, None

        if graph.is_fork(node):
            # Branches take passes of their own, so they add up
            branches = [walk(s, True) for s in successors]
            steps = 1 + sum(b[0] for b in branches)
            join = next((j for _, j in branches if j is not None), None)
            if join is None:
                return steps, None
            # Everything after the join is in every branch, so count it once
            rest, end_join = through(join, in_fork)
            return steps + rest, end_join

        # Only one branch of an exclusive gateway runs, so take the longest
        steps, join = max(
            (walk(s, in_fork) for s in successors),
            key=lambda w: (w[0], w[1] is not None),
        )
        return 1 + steps, join

    return through(start, False)[0]


def _loop_steps(graph: _AcyclicGraph, retries: int) -> int:
    """
    Steps the loops add, retrying each one the given number of times
    """

    def longest_cycle(head: Node, tail: Node) -> int:
        @cache
        def path(node: Node) -> int:
            # Nodes on the longest path from node to the tail, 0 if none
            if node is tail:
                return 1
            lengths = [p for p in map(path, graph.successors(node)) if p > 0]
            return 1 + max(lengths) if lengths else 0

        return path(head)

    cycles: dict[Node, int] = {}
    for tail, head in graph.back_edges:
        cycles[head] = max(cycles.get(head, 0), longest_cycle(head, tail))

    return sum(cycles.values()) * retries


def calculate_cbmc_bound(bpmn: Bpmn, retries: int = DEFAULT_RETRIES) -> int:
    """
    Work out how many passes of the CBMC main loop cover every path of the BPMN

    Args:
        bpmn (Bpmn): BPMN to bound
        retries (int, optional): Times each loop is retried. Defaults to 2.

    Returns:
        int: Bound for the largest start event of the largest process
    """
    bound = 0
    for process in bpmn.processes.values():
        for start in process.get_start_states().values():
            graph = _AcyclicGraph(start)
            steps = _longest_path(graph, start) + _loop_steps(graph, retries)
            bound = max(bound, steps)
    return bound
