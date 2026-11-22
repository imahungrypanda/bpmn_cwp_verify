from collections.abc import Iterator

from bpmncwpverify.core.bpmn import (
    Bpmn,
    Node,
    ParallelGatewayNode,
    Process,
    StartEvent,
)

DEFAULT_RETRIES = 2


def _successors(node: Node) -> list[Node]:
    return [flow.target_node for flow in node.out_flows]


def _is_fork(node: Node) -> bool:
    return isinstance(node, ParallelGatewayNode) and len(node.out_flows) > 1


def _reachable(start: Node, avoid: frozenset[Node] = frozenset()) -> set[Node]:
    """Nodes reachable from start by one or more flows that don't enter avoid."""
    seen: set[Node] = set()
    stack = _successors(start)
    while stack:
        node = stack.pop()
        if node not in seen and node not in avoid:
            seen.add(node)
            stack.extend(_successors(node))
    return seen


def _back_edges(start: StartEvent) -> set[tuple[Node, Node]]:
    """(source, target) of the flows that come back onto the path, walking depth first from start."""
    edges: set[tuple[Node, Node]] = set()
    done: set[Node] = set()
    on_path: set[Node] = {start}
    stack: list[tuple[Node, Iterator[Node]]] = [(start, iter(_successors(start)))]
    while stack:
        node, successors = stack[-1]
        for succ in successors:
            if succ in on_path:
                edges.add((node, succ))
            elif succ not in done:
                on_path.add(succ)
                stack.append((succ, iter(_successors(succ))))
                break
        else:
            stack.pop()
            on_path.discard(node)
            done.add(node)
    return edges


class _Bound:
    """Longest path computations for the graph reachable from one start event"""

    def __init__(self, start: StartEvent) -> None:
        self._start = start
        self._reach: dict[Node, set[Node]] = {}
        self._memo: dict[tuple[Node, Node | None, frozenset[Node]], int] = {}

    def reach(self, node: Node) -> set[Node]:
        if node not in self._reach:
            self._reach[node] = _reachable(node)
        return self._reach[node]

    def _join(self, fork: Node, path: frozenset[Node]) -> Node | None:
        """
        The node where the branches of a fork meet again: the first one that
        every branch reaches without going back along the path.
        """
        reach: dict[Node, set[Node]] = {}
        common: set[Node] | None = None
        for branch in _successors(fork):
            if branch in path:
                continue
            reach[branch] = _reachable(branch, path)
            reached = reach[branch] | {branch}
            common = reached if common is None else common & reached
        if not common:
            return None
        # the first common node is the one that no other common node leads to
        for node in common:
            if not any(node in _reachable(other, path) for other in common - {node}):
                return node
        # the common nodes lead into each other, so pick any of them
        return next(iter(common))

    def acyclic(self) -> int:
        return self._steps(self._start, None, frozenset())

    def _steps(self, node: Node, stop: Node | None, path: frozenset[Node]) -> int:
        """Longest path from node, not counting stop or going back onto path."""
        if node is stop or node in path:
            return 0
        # only the part of the path that node can come back to changes the answer
        reach = self.reach(node)
        key = (node, stop, frozenset(p for p in path if p in reach))
        if key in self._memo:
            return self._memo[key]

        path = path | {node}
        successors = _successors(node)
        if _is_fork(node):
            join = self._join(node, path)
            steps = 1 + sum(self._steps(s, join, path) for s in successors)
            if join is not None:
                steps += self._steps(join, stop, path)
        else:
            steps = 1 + max((self._steps(s, stop, path) for s in successors), default=0)
        self._memo[key] = steps
        return steps


def _cycle_length(head: Node, back_edges: set[tuple[Node, Node]]) -> int:
    """
    Number of nodes on the longest cycle through head: the longest path from
    head, without taking any other loop's way back, to a node that comes back to head.
    """
    sources = {src for src, dst in back_edges if dst is head}
    longest: dict[Node, int] = {}

    def from_node(node: Node) -> int:
        if node not in longest:
            best = 1 if node in sources else 0
            for succ in _successors(node):
                if (node, succ) not in back_edges:
                    rest = from_node(succ)
                    if rest:
                        best = max(best, 1 + rest)
            longest[node] = best
        return longest[node]

    return from_node(head)


def _start_bound(start: StartEvent, retries: int) -> int:
    bound = _Bound(start)
    total = bound.acyclic()
    back_edges = _back_edges(start)
    for head in {dst for _, dst in back_edges}:
        total += _cycle_length(head, back_edges) * retries
    return total


def _process_bound(process: Process, retries: int) -> int:
    return max(
        (_start_bound(s, retries) for s in process.get_start_states().values()),
        default=0,
    )


def compute_bound(bpmn: Bpmn, retries: int = DEFAULT_RETRIES) -> int:
    """
    Number of passes of the main loop that cover every path through the BPMN

    Args:
        bpmn (Bpmn): The workflow to bound
        retries (int, optional): How many extra times each loop is run. Defaults to 2.

    Returns:
        int: Largest bound over all processes and start events
    """
    return max(
        (_process_bound(p, retries) for p in bpmn.processes.values()),
        default=0,
    )
