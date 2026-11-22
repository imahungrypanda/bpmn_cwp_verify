from bpmncwpverify.core.bpmn import (
    Bpmn,
    EndEvent,
    Node,
    ParallelGatewayNode,
    Process,
    SequenceFlow,
    StartEvent,
)

DEFAULT_RETRIES = 2


class _ProcessGraph:
    """
    The graph reachable from one start event, with its loops cut
    """

    def __init__(self, start: StartEvent) -> None:
        self._back_edges: list[SequenceFlow] = []
        self._nodes: dict[str, Node] = {}  # every reachable node
        self._order: dict[str, int] = {}  # topological index of every reachable node
        self._lengths: dict[tuple[str, str | None, bool], int | None] = {}
        self._reach: dict[str, set[str]] = {}
        self._cut(start)
        self._start = start

    def _cut(self, start: Node) -> None:
        on_path: set[str] = set()
        done: set[str] = set()
        postorder: list[Node] = []

        def visit(node: Node) -> None:
            on_path.add(node.id)
            for flow in node.out_flows:
                target = flow.target_node
                if target.id in on_path:
                    self._back_edges.append(flow)
                elif target.id not in done:
                    visit(target)
            on_path.discard(node.id)
            done.add(node.id)
            postorder.append(node)
            self._nodes[node.id] = node

        visit(start)
        for index, node in enumerate(reversed(postorder)):
            self._order[node.id] = index

    def _successors(self, node: Node) -> list[Node]:
        return [
            flow.target_node for flow in node.out_flows if flow not in self._back_edges
        ]

    def _descendants(self, node: Node) -> set[str]:
        if node.id not in self._reach:
            reach = {node.id}
            for successor in self._successors(node):
                reach |= self._descendants(successor)
            self._reach[node.id] = reach
        return self._reach[node.id]

    def _find_join(self, fork: Node) -> Node | None:
        branches = self._successors(fork)
        common = self._descendants(branches[0])
        for branch in branches[1:]:
            common = common & self._descendants(branch)
        if not common:
            return None
        join = self._nodes[min(common, key=lambda node_id: self._order[node_id])]
        if isinstance(join, ParallelGatewayNode) and len(join.in_flows) > 1:
            return join
        return None

    def longest(
        self, node: Node, stop: Node | None = None, strict: bool = True
    ) -> int | None:
        """
        Steps from node up to, not including, stop, on the longest path

        A path has to finish at an end event (or at stop) when strict. None means
        there is no such path. When not strict, a path that runs into a cut loop
        edge, or any other dead end, counts as finished, so there is always one.
        """
        if stop is not None and node.id == stop.id:
            return 0
        key = (node.id, stop.id if stop else None, strict)
        if key not in self._lengths:
            self._lengths[key] = self._longest(node, stop, strict)
        return self._lengths[key]

    def _branch(self, node: Node, stop: Node | None) -> int:
        # a branch of a fork always takes its steps, even if it only loops
        steps = self.longest(node, stop)
        return steps if steps is not None else self.longest(node, stop, False) or 0

    def _longest(self, node: Node, stop: Node | None, strict: bool) -> int | None:
        successors = self._successors(node)
        if not successors:
            return 1 if isinstance(node, EndEvent) or not strict else None
        if isinstance(node, ParallelGatewayNode) and len(successors) > 1:
            join = self._find_join(node)
            if join is None:
                return 1 + sum(self._branch(b, stop) for b in successors)
            after = self.longest(join, stop, strict)
            if after is None:
                return None
            return 1 + sum(self._branch(b, join) for b in successors) + after
        onward = [self.longest(s, stop, strict) for s in successors]
        best = max((steps for steps in onward if steps is not None), default=None)
        return None if best is None else 1 + best

    def _cycle_length(self, head: Node, sources: list[Node]) -> int:
        """
        Longest path of nodes from head to one of the nodes with an edge back to it
        """
        source_ids = {s.id for s in sources}
        memo: dict[str, int] = {}

        def steps(node: Node) -> int:  # 0 when no source can be reached
            if node.id not in memo:
                onward = [steps(s) for s in self._successors(node)]
                best = max(onward, default=0)
                if best:
                    memo[node.id] = 1 + best
                else:
                    memo[node.id] = 1 if node.id in source_ids else 0
            return memo[node.id]

        return steps(head)

    def loop_cost(self, retries: int) -> int:
        heads: dict[str, tuple[Node, list[Node]]] = {}
        for flow in self._back_edges:
            _, sources = heads.setdefault(flow.target_node.id, (flow.target_node, []))
            sources.append(flow.source_node)
        return sum(
            self._cycle_length(head, sources) * retries
            for head, sources in heads.values()
        )

    def bound(self, retries: int) -> int:
        path = self.longest(self._start)
        if path is None:  # no path reaches an end event
            path = self.longest(self._start, strict=False) or 0
        return path + self.loop_cost(retries)


def _process_bound(process: Process, retries: int) -> int:
    return max(
        (
            _ProcessGraph(start).bound(retries)
            for start in process.get_start_states().values()
        ),
        default=0,
    )


def compute_bound(bpmn: Bpmn, retries: int = DEFAULT_RETRIES) -> int:
    """
    Number of passes of the generated main() loop needed to cover every path

    Args:
        bpmn (Bpmn): The workflow
        retries (int, optional): How many times each loop may be repeated.
    """
    return max(
        (_process_bound(p, retries) for p in bpmn.processes.values()),
        default=0,
    )
