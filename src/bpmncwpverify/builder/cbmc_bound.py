from collections.abc import Iterator
from functools import cache

from bpmncwpverify.core.bpmn import (
    Bpmn,
    Node,
    ParallelGatewayNode,
    Process,
    StartEvent,
    Task,
)

DEFAULT_RETRIES = 2


def _successors(node: Node) -> list[Node]:
    """
    Nodes that can fire right after this one, boundary events of a task included
    """
    nodes = [flow.target_node for flow in node.out_flows]
    if isinstance(node, Task):
        nodes.extend(node.msg_boundary_events)
    return nodes


def _back_edges(start: Node) -> set[tuple[str, str]]:
    """
    Edges, as (source id, target id), that lead back to a node already on the path
    """
    back: set[tuple[str, str]] = set()
    on_path: set[str] = set()
    done: set[str] = set()

    def dfs(node: Node) -> None:
        on_path.add(node.id)
        for succ in _successors(node):
            if succ.id in on_path:
                back.add((node.id, succ.id))
            elif succ.id not in done:
                dfs(succ)
        on_path.discard(node.id)
        done.add(node.id)

    dfs(start)
    return back


class _ProcessBound:
    """
    Longest-path computations on one start event's graph, with its loops cut
    """

    def __init__(self, start: Node, retries: int) -> None:
        self._start = start
        self._retries = retries
        self._back = _back_edges(start)
        self._seg = cache(self._segment)
        self._reach = cache(self._reachable)
        self._cycle = cache(self._cycle_length)

    def _dag_successors(self, node: Node) -> list[Node]:
        return [s for s in _successors(node) if (node.id, s.id) not in self._back]

    def _reachable(self, node: Node) -> frozenset[str]:
        """
        Ids of the node and everything after it, once the loops are cut
        """
        seen: set[str] = set()
        stack = [node]
        while stack:
            current = stack.pop()
            if current.id not in seen:
                seen.add(current.id)
                stack.extend(self._dag_successors(current))
        return frozenset(seen)

    def _nodes_after(self, node: Node) -> Iterator[Node]:
        stack = [node]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current.id not in seen:
                seen.add(current.id)
                yield current
                stack.extend(self._dag_successors(current))

    def _matching_join(self, branches: list[Node]) -> Node | None:
        """
        The parallel join where the branches meet again, if they do.
        It is the first node every branch reaches, and only counts when it is
        a parallel gateway, since the part after any other merge runs once per token.
        """
        common: set[str] = set(self._reach(branches[0]))
        for branch in branches[1:]:
            common &= self._reach(branch)
        if not common:
            return None
        for node in self._nodes_after(branches[0]):
            if node.id in common and common <= self._reach(node):
                if isinstance(node, ParallelGatewayNode) and len(node.in_flows) > 1:
                    return node
                return None
        return None

    def _segment(
        self, node: Node, boundary: Node | None, target: Node | None
    ) -> int | None:
        """
        Most steps from node to the end of the process, or, when target is given,
        to target. Stops before boundary. None when there is no such path.
        """
        if node is boundary:
            return None if target else 0
        if node is target:
            return 1

        succs = self._dag_successors(node)
        if not succs:
            # A node whose only way on is a loop is not the end of a path
            return 1 if not target and not _successors(node) else None

        if isinstance(node, ParallelGatewayNode) and len(succs) > 1:
            return self._fork(node, succs, boundary, target)

        costs = [c for s in succs if (c := self._seg(s, boundary, target)) is not None]
        return 1 + max(costs) if costs else None

    def _fork(
        self,
        node: Node,
        branches: list[Node],
        boundary: Node | None,
        target: Node | None,
    ) -> int | None:
        join = self._matching_join(branches)
        tail_has_target = (
            target is not None and join is not None and target.id in self._reach(join)
        )
        total = 1
        reaches_target = False
        for branch in branches:
            if target and not tail_has_target and target.id in self._reach(branch):
                cost = self._seg(branch, join, target)
                reaches_target = True
            else:
                cost = self._seg(branch, join, None)
            if cost is None:
                return None
            total += cost
        if target and not tail_has_target:
            return total if reaches_target else None
        if join is None:
            return total
        tail = self._seg(join, boundary, target)
        return None if tail is None else total + tail

    def _cycle_length(self, node: Node, source: Node) -> int | None:
        """
        Nodes on the longest path from node to source, both counted, once the loops
        are cut. A cycle is one path, so parallel branches are not added together.
        """
        if node is source:
            return 1
        costs = [
            c
            for s in self._dag_successors(node)
            if (c := self._cycle(s, source)) is not None
        ]
        return 1 + max(costs) if costs else None

    def bound(self) -> int:
        total = self._seg(self._start, None, None) or 0
        nodes = {n.id: n for n in self._nodes_after(self._start)}
        cycles: dict[str, int] = {}
        for source_id, head_id in self._back:
            length = self._cycle(nodes[head_id], nodes[source_id]) or 0
            cycles[head_id] = max(cycles.get(head_id, 0), length)
        return total + sum(cycles.values()) * self._retries


def _process_bound(process: Process, retries: int) -> int:
    start_events: list[StartEvent] = list(process.get_start_states().values())
    return max(
        (_ProcessBound(start, retries).bound() for start in start_events), default=0
    )


def get_unwinding_bound(bpmn: Bpmn, retries: int = DEFAULT_RETRIES) -> int:
    """
    How many passes of main()'s loop it takes to cover every path through the BPMN

    Args:
        bpmn (Bpmn): BPMN to work the bound out for
        retries (int, optional): How many times each loop is taken. Defaults to 2.
    """
    return max(
        (_process_bound(process, retries) for process in bpmn.processes.values()),
        default=0,
    )
