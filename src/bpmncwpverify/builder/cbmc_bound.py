from collections.abc import Callable

from bpmncwpverify.core.bpmn import (
    Bpmn,
    Node,
    ParallelGatewayNode,
    Process,
    Task,
)

DEFAULT_RETRIES = 2

_Successors = Callable[[Node], list[Node]]


def _successors(node: Node) -> list[Node]:
    nodes: list[Node] = [flow.target_node for flow in node.out_flows]
    if isinstance(node, Task):
        nodes.extend(node.msg_boundary_events)
    return nodes


def _find_back_edges(start: Node) -> set[tuple[str, str]]:
    """Edges that go back to a node that is on the path (depth first) so far."""
    back_edges: set[tuple[str, str]] = set()
    visited: set[str] = set()
    on_path: set[str] = set()

    def dfs(node: Node) -> None:
        visited.add(node.id)
        on_path.add(node.id)
        for succ in _successors(node):
            if succ.id in on_path:
                back_edges.add((node.id, succ.id))
            elif succ.id not in visited:
                dfs(succ)
        on_path.discard(node.id)

    dfs(start)
    return back_edges


def _is_fork(node: Node) -> bool:
    return isinstance(node, ParallelGatewayNode) and len(node.out_flows) > 1


class _AcyclicGraph:
    """The part of a process reachable from one node, with its loops cut."""

    def __init__(self, start: Node, successors: _Successors) -> None:
        self.start = start
        back_edges = _find_back_edges(start)
        self._back_edges = back_edges
        self._succ: dict[str, list[Node]] = {}
        self._order: list[Node] = []  # topological order
        self._nodes: dict[str, Node] = {}
        self._reach: dict[str, set[str]] = {}
        self._memo: dict[tuple[str, str | None], int] = {}
        self._build(start, successors)

    def _build(self, start: Node, successors: _Successors) -> None:
        seen: set[str] = set()

        def dfs(node: Node) -> None:
            seen.add(node.id)
            kept = [
                s for s in successors(node) if (node.id, s.id) not in self._back_edges
            ]
            self._succ[node.id] = kept
            self._nodes[node.id] = node
            for s in kept:
                if s.id not in seen:
                    dfs(s)
            self._order.append(node)

        dfs(start)
        self._order.reverse()
        for node in reversed(self._order):
            reach = {node.id}
            for s in self._succ[node.id]:
                reach |= self._reach[s.id]
            self._reach[node.id] = reach

    def _join_of(self, fork: Node) -> Node | None:
        """The first node that every branch of the fork leads to, if any."""
        branches = self._succ[fork.id]
        common = set(self._reach[branches[0].id])
        for branch in branches[1:]:
            common &= self._reach[branch.id]
        for node in self._order:
            if node.id in common:
                return node
        return None

    def steps(self, node: Node, stop: Node | None = None) -> int:
        """Passes needed from node up to, not including, stop."""
        if stop is not None and node.id == stop.id:
            return 0
        key = (node.id, stop.id if stop else None)
        if key in self._memo:
            return self._memo[key]

        succ = self._succ[node.id]
        if not succ:
            result = 1
        elif _is_fork(node):
            join = self._join_of(node)
            branches = sum(self.steps(s, join) for s in succ)
            after = self.steps(join, stop) if join else 0
            result = 1 + branches + after
        else:
            result = 1 + max(self.steps(s, stop) for s in succ)
        self._memo[key] = result
        return result

    def longest_path(self, src: Node, dst: Node) -> int:
        """Most nodes on a single path from src to dst, 0 if there is none."""
        best: dict[str, int] = {}
        for node in reversed(self._order):
            if node.id == dst.id:
                best[node.id] = 1
                continue
            lengths = [best[s.id] for s in self._succ[node.id] if best[s.id] > 0]
            best[node.id] = 1 + max(lengths) if lengths else 0
        return best[src.id]

    def back_edge_sources(self) -> dict[Node, list[Node]]:
        """Maps each node a loop comes back into to the nodes the loop leaves from."""
        sources: dict[Node, list[Node]] = {}
        for src, dst in self._back_edges:
            sources.setdefault(self._nodes[dst], []).append(self._nodes[src])
        return sources


def _cycle_length(graph: _AcyclicGraph, head: Node, tail: Node) -> int:
    """
    Longest cycle head -> ... -> tail -> head, counting each node once.

    Branches of a parallel gateway inside the cycle are not added together: the
    cycle is a single path.
    """
    return graph.longest_path(head, tail)


def _process_bound(process: Process, retries: int) -> int:
    bounds = [0]
    for start in process.get_start_states().values():
        graph = _AcyclicGraph(start, _successors)
        bound = graph.steps(start)
        loops = sum(
            max(_cycle_length(graph, head, tail) for tail in tails)
            for head, tails in graph.back_edge_sources().items()
        )
        bounds.append(bound + retries * loops)
    return max(bounds)


def compute_bound(bpmn: Bpmn, retries: int = DEFAULT_RETRIES) -> int:
    """
    Number of passes of the CBMC main loop needed to cover every path.

    Args:
        bpmn (Bpmn): Workflow to bound
        retries (int, optional): How many times each loop is repeated. Defaults to 2.
    """
    return max(
        (_process_bound(process, retries) for process in bpmn.processes.values()),
        default=0,
    )
