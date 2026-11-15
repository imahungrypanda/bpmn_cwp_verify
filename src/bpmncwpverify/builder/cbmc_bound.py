from bpmncwpverify.core.bpmn import (
    Bpmn,
    EndEvent,
    Node,
    ParallelGatewayNode,
    Process,
    StartEvent,
)

DEFAULT_RETRIES = 2

# (reached an end event, number of steps): an unfinished path ranks below a finished one
_Result = tuple[bool, int]


def _is_fork(node: Node) -> bool:
    return isinstance(node, ParallelGatewayNode) and len(node.out_flows) > 1


class _CutGraph:
    """
    The graph reachable from a start event, with its loops cut.

    A loop is cut by dropping its back edge: an edge to a node that is already on
    the path being followed. What is left has no cycles.
    """

    def __init__(self, start: StartEvent) -> None:
        self.succs: dict[Node, list[Node]] = {}
        self.back_edges: list[tuple[Node, Node]] = []
        self._cut(start, set())

    def _cut(self, node: Node, path: set[Node]) -> None:
        self.succs[node] = []
        path.add(node)
        for flow in node.out_flows:
            target = flow.target_node
            if target in path:
                self.back_edges.append((node, target))
                continue
            self.succs[node].append(target)
            if target not in self.succs:
                self._cut(target, path)
        path.remove(node)

    def _distances(self, node: Node, avoid: Node) -> dict[Node, int]:
        dist = {node: 0}
        queue = [node]
        for current in queue:
            for succ in self.succs[current]:
                if succ is not avoid and succ not in dist:
                    dist[succ] = dist[current] + 1
                    queue.append(succ)
        return dist

    def join_of(self, fork: Node) -> Node | None:
        """The parallel join where all the branches of a fork meet, if there is one"""
        branches = [self._distances(succ, fork) for succ in self.succs[fork]]
        candidates = [
            node
            for node in branches[0]
            if isinstance(node, ParallelGatewayNode)
            and len(node.in_flows) > 1
            and all(node in branch for branch in branches)
        ]
        if not candidates:
            return None
        return min(
            candidates, key=lambda node: sum(branch[node] for branch in branches)
        )


class _Walker:
    def __init__(self, graph: _CutGraph) -> None:
        self._graph = graph
        self._memo: dict[tuple[Node, Node | None], _Result] = {}

    def longest_path(self, node: Node, stop: Node | None = None) -> _Result:
        """
        Longest path from node to an end event, counting each node as one step.

        It stops short of the stop node, which is the join of the fork being walked.
        """
        if node is stop:
            return True, 0
        key = (node, stop)
        if key not in self._memo:
            self._memo[key] = (
                self._fork(node, stop) if _is_fork(node) else self._step(node, stop)
            )
        return self._memo[key]

    def _step(self, node: Node, stop: Node | None) -> _Result:
        # An exclusive gateway has one branch taken at a time, so take the longest
        best: _Result = (isinstance(node, EndEvent), 0)
        for succ in self._graph.succs[node]:
            best = max(best, self.longest_path(succ, stop))
        return best[0], best[1] + 1

    def _fork(self, fork: Node, stop: Node | None) -> _Result:
        join = self._graph.join_of(fork)
        branches = [self.longest_path(s, join) for s in self._graph.succs[fork]]
        done = all(ok for ok, _ in branches)
        steps = 1 + sum(length for _, length in branches)
        if join is None:
            return done, steps
        # The part after the join is in every branch, so it is counted once
        after_done, after = self.longest_path(join, stop)
        return done and after_done, steps + after

    def longest_cycle(self, head: Node, source: Node) -> int:
        """Nodes on the longest path from head to source, the node that loops back"""
        memo: dict[Node, int] = {}

        def longest(node: Node) -> int:
            if node is source:
                return 1
            if node not in memo:
                # 0 means source can't be reached from here
                reach = max((longest(s) for s in self._graph.succs[node]), default=0)
                memo[node] = 1 + reach if reach else 0
            return memo[node]

        return longest(head)


def _process_bound(process: Process, retries: int) -> int:
    bound = 0
    for start in process.get_start_states().values():
        graph = _CutGraph(start)
        walker = _Walker(graph)
        _, steps = walker.longest_path(start)
        # Per node a loop comes back into, the longest cycle through it
        cycles: dict[Node, int] = {}
        for source, head in graph.back_edges:
            cycles[head] = max(cycles.get(head, 0), walker.longest_cycle(head, source))
        bound = max(bound, steps + sum(cycles.values()) * retries)
    return bound


def get_unwinding_bound(bpmn: Bpmn, retries: int = DEFAULT_RETRIES) -> int:
    """
    Number of passes of the loop in main() needed to cover every path of the BPMN.

    Args:
        bpmn (Bpmn): The workflow
        retries (int, optional): How many more times each loop can be gone around.
    """
    return max(
        (_process_bound(process, retries) for process in bpmn.processes.values()),
        default=0,
    )
