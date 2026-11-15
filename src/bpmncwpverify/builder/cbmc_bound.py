from bpmncwpverify.core.bpmn import (
    Bpmn,
    EndEvent,
    Node,
    ParallelGatewayNode,
    StartEvent,
)

DEFAULT_RETRIES = 2

# Cost of walking from a node: the steps taken, and the join gateway the walk
# stopped in front of (None if it ran to an end event or a dead end).
_Walk = tuple[int, Node | None]


def _is_fork(node: Node) -> bool:
    return isinstance(node, ParallelGatewayNode) and len(node.out_flows) > 1


def _is_join(node: Node) -> bool:
    return (
        isinstance(node, ParallelGatewayNode)
        and len(node.in_flows) > 1
        and len(node.out_flows) <= 1
    )


class _ProcessGraph:
    """
    The part of a process reachable from one start event, with its loops cut
    """

    def __init__(self, start: StartEvent) -> None:
        self._start = start
        self._back_flows: set[str] = set()
        self._cut_loops()
        self._walks: dict[str, _Walk | None] = {}

    def _cut_loops(self) -> None:
        # A flow into a node that is already on the path closes a loop
        visited: set[str] = set()
        on_path: set[str] = set()

        def dfs(node: Node) -> None:
            visited.add(node.id)
            on_path.add(node.id)
            for flow in node.out_flows:
                target = flow.target_node
                if target.id in on_path:
                    self._back_flows.add(flow.id)
                elif target.id not in visited:
                    dfs(target)
            on_path.discard(node.id)

        dfs(self._start)

    def _forward(self, node: Node) -> list[Node]:
        return [f.target_node for f in node.out_flows if f.id not in self._back_flows]

    def _enter(self, node: Node) -> _Walk | None:
        if _is_join(node):
            return (0, node)
        return self._walk(node)

    def _pass_join(self, join: Node) -> _Walk | None:
        # The join fires once, then the rest of the process follows it
        rest = self._best(self._forward(join))
        if rest is None:
            return None
        return (1 + rest[0], rest[1])

    def _best(self, targets: list[Node]) -> _Walk | None:
        walks = [w for w in map(self._enter, targets) if w is not None]
        if not walks:
            return None
        return max(walks, key=lambda w: w[0])

    def _walk(self, node: Node) -> _Walk | None:
        """
        Longest walk from node to an end event, or to the join closing the
        parallel branch node sits in. None if every way out is a cut loop.
        """
        if node.id in self._walks:
            return self._walks[node.id]
        result = self._compute_walk(node)
        self._walks[node.id] = result
        return result

    def _compute_walk(self, node: Node) -> _Walk | None:
        if isinstance(node, EndEvent):
            return (1, None)
        targets = self._forward(node)
        if not _is_fork(node):
            rest = self._best(targets)
            return None if rest is None else (1 + rest[0], rest[1])

        branches = [self._enter(t) for t in targets]
        if any(b is None for b in branches):
            return None
        steps = 1 + sum(b[0] for b in branches if b is not None)
        join = next((b[1] for b in branches if b is not None and b[1]), None)
        if join is None:
            return (steps, None)
        rest = self._pass_join(join)
        return None if rest is None else (steps + rest[0], rest[1])

    def longest_path(self) -> int:
        walk = self._walk(self._start)
        steps = 0
        while walk is not None:
            steps += walk[0]
            walk = None if walk[1] is None else self._pass_join(walk[1])
        return steps

    def loop_heads(self) -> list[tuple[Node, list[Node]]]:
        """
        Each node a loop comes back into, with the nodes that close a loop onto it
        """
        closers: dict[str, list[Node]] = {}
        heads: dict[str, Node] = {}
        for node in self._nodes():
            for flow in node.out_flows:
                if flow.id in self._back_flows:
                    heads[flow.target_node.id] = flow.target_node
                    closers.setdefault(flow.target_node.id, []).append(node)
        return [(heads[i], closers[i]) for i in heads]

    def _nodes(self) -> list[Node]:
        seen: dict[str, Node] = {}
        stack: list[Node] = [self._start]
        while stack:
            node = stack.pop()
            if node.id in seen:
                continue
            seen[node.id] = node
            stack.extend(f.target_node for f in node.out_flows)
        return list(seen.values())

    def longest_cycle(self, head: Node, closers: list[Node]) -> int:
        """
        Steps in the longest cycle through head: the longest path from head to
        a node that loops back to it, over the graph with loops cut
        """
        closer_ids = {c.id for c in closers}
        memo: dict[str, int] = {}

        def longest_from(node: Node) -> int:
            if node.id in memo:
                return memo[node.id]
            best = 1 if node.id in closer_ids else 0
            for target in self._forward(node):
                tail = longest_from(target)
                if tail:
                    best = max(best, 1 + tail)
            memo[node.id] = best
            return best

        return longest_from(head)


def _bound_for_start(start: StartEvent, retries: int) -> int:
    graph = _ProcessGraph(start)
    bound = graph.longest_path()
    for head, closers in graph.loop_heads():
        bound += retries * graph.longest_cycle(head, closers)
    return bound


def compute_unwinding_bound(bpmn: Bpmn, retries: int = DEFAULT_RETRIES) -> int:
    """
    Number of passes of the C program's main loop needed to cover every path
    through the BPMN

    Args:
        bpmn (Bpmn): The workflow
        retries (int, optional): Times each loop may go around again. Defaults to 2.
    """
    return max(
        (
            _bound_for_start(start, retries)
            for process in bpmn.processes.values()
            for start in process.get_start_states().values()
        ),
        default=0,
    )
