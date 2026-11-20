from bpmncwpverify.core.bpmn import (
    Bpmn,
    Node,
    ParallelGatewayNode,
    Process,
    StartEvent,
    Task,
)

DEFAULT_RETRIES = 2

_Edge = tuple[str, str]


def _successors(node: Node) -> list[tuple[Node, _Edge]]:
    """
    Nodes that can fire right after this one, with the edge that leads there.
    A task's boundary events are alternatives to its own outgoing flows.
    """
    result = [(f.target_node, (node.id, f.target_node.id)) for f in node.out_flows]
    if isinstance(node, Task):
        result += [(e, (node.id, e.id)) for e in node.msg_boundary_events]
    return result


def _find_back_edges(start: StartEvent) -> set[_Edge]:
    """
    Edges that lead back to a node still on the depth-first path from start
    """
    back: set[_Edge] = set()
    done: set[str] = set()
    on_path: set[str] = set()

    def visit(node: Node) -> None:
        on_path.add(node.id)
        for target, edge in _successors(node):
            if target.id in on_path:
                back.add(edge)
            elif target.id not in done:
                visit(target)
        on_path.discard(node.id)
        done.add(node.id)

    visit(start)
    return back


class _Longest:
    """
    Longest paths through one start event's graph, once its loops are cut
    """

    def __init__(self, start: StartEvent) -> None:
        self._start = start
        self._back = _find_back_edges(start)
        self._cache: dict[tuple[str, str | None], int] = {}
        self._reach: dict[str, set[str]] = {}
        self._nodes: dict[str, Node] = {start.id: start}
        todo: list[Node] = [start]
        while todo:
            for target, _ in _successors(todo.pop()):
                if target.id not in self._nodes:
                    self._nodes[target.id] = target
                    todo.append(target)

    def _next(self, node: Node) -> list[Node]:
        return [t for t, edge in _successors(node) if edge not in self._back]

    def _descendants(self, node: Node) -> set[str]:
        """Ids of node and everything after it, loops cut"""
        if node.id not in self._reach:
            seen: set[str] = set()
            todo = [node]
            while todo:
                n = todo.pop()
                if n.id not in seen:
                    seen.add(n.id)
                    todo.extend(self._next(n))
            self._reach[node.id] = seen
        return self._reach[node.id]

    def _join_of(self, fork: Node) -> Node | None:
        """
        The parallel join the fork's branches meet at: the first parallel
        gateway with several incoming flows that every branch reaches
        """
        branches = self._next(fork)
        common = self._descendants(branches[0]).intersection(
            *(self._descendants(b) for b in branches[1:])
        )
        joins = [
            n
            for n in (self._nodes[i] for i in common)
            if isinstance(n, ParallelGatewayNode) and len(n.in_flows) > 1
        ]
        if not joins:
            return None
        return max(joins, key=lambda n: len(self._descendants(n)))

    def to_end(self, node: Node, stop: Node | None = None) -> int:
        """
        Steps from node (inclusive) to an end of the process, or up to but not
        including the join stop
        """
        if stop is not None and node is stop:
            return 0
        key = (node.id, stop.id if stop else None)
        if key not in self._cache:
            self._cache[key] = self._to_end(node, stop)
        return self._cache[key]

    def _to_end(self, node: Node, stop: Node | None) -> int:
        nxt = self._next(node)
        if not nxt:
            return 1
        if len(nxt) == 1 or not self._is_fork(node):
            # an exclusive choice: CBMC tries each branch, so take the longest
            return 1 + max(self.to_end(n, stop) for n in nxt)
        join = self._join_of(node)
        if join is None:
            return 1 + sum(self.to_end(n, stop) for n in nxt)
        # each branch fires on its own, the part from the join on only once
        return 1 + sum(self.to_end(n, join) for n in nxt) + self.to_end(join, stop)

    def to_goal(self, node: Node, goals: set[str]) -> int | None:
        """
        Nodes on the longest path from node (inclusive) to the first node in
        goals, or None if none of them can be reached. A fork's branches are
        not added up here: a cycle counts as the one path round it.
        """
        if node.id in goals:
            return 1
        reached = [r for r in (self.to_goal(n, goals) for n in self._next(node)) if r]
        return 1 + max(reached) if reached else None

    @staticmethod
    def _is_fork(node: Node) -> bool:
        return isinstance(node, ParallelGatewayNode) and node.is_fork

    def loop_steps(self) -> list[int]:
        """
        One length per node a loop comes back into: the nodes of the longest
        cycle through it, that is the longest way from the node to the source
        of a back edge into it
        """
        sources: dict[str, set[str]] = {}
        for source, target in self._back:
            sources.setdefault(target, set()).add(source)
        lengths: list[int] = []
        for target, srcs in sources.items():
            steps = self.to_goal(self._nodes[target], srcs)
            assert steps is not None, (
                "a back edge's source is reachable from its target"
            )
            lengths.append(steps)
        return lengths


def _process_bound(process: Process, retries: int) -> int:
    bounds: list[int] = []
    for start in process.get_start_states().values():
        longest = _Longest(start)
        bounds.append(longest.to_end(start) + retries * sum(longest.loop_steps()))
    return max(bounds, default=0)


def compute_unwind_bound(bpmn: Bpmn, retries: int = DEFAULT_RETRIES) -> int:
    """
    Number of passes of the generated main() loop that cover every path
    through the BPMN, with each loop taken up to `retries` extra times

    Args:
        bpmn (Bpmn): BPMN to bound
        retries (int, optional): Times a loop is repeated. Defaults to 2.
    """
    return max((_process_bound(p, retries) for p in bpmn.processes.values()), default=0)
