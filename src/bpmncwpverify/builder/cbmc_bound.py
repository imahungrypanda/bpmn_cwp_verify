from bpmncwpverify.core.bpmn import (
    Bpmn,
    EndEvent,
    Node,
    ParallelGatewayNode,
    Process,
)

DEFAULT_RETRIES = 2

# (reaches the goal, steps). Paths that reach the goal always beat ones that don't.
_Length = tuple[bool, int]
_DEAD: _Length = (False, 0)


def _successors(node: Node, back_edges: set[tuple[str, str]]) -> list[Node]:
    return [
        flow.target_node
        for flow in node.out_flows
        if (node.id, flow.target_node.id) not in back_edges
    ]


def _find_back_edges(start: Node) -> set[tuple[str, str]]:
    """
    Edges that come back to a node already on the path from `start`
    """
    back_edges: set[tuple[str, str]] = set()
    on_path: set[str] = set()
    done: set[str] = set()

    def dfs(node: Node) -> None:
        on_path.add(node.id)
        for flow in node.out_flows:
            target = flow.target_node
            if target.id in on_path:
                back_edges.add((node.id, target.id))
            elif target.id not in done:
                dfs(target)
        on_path.discard(node.id)
        done.add(node.id)

    dfs(start)
    return back_edges


def _post_order(start: Node, back_edges: set[tuple[str, str]]) -> list[Node]:
    order: list[Node] = []
    seen: set[str] = {start.id}

    def dfs(node: Node) -> None:
        for succ in _successors(node, back_edges):
            if succ.id not in seen:
                seen.add(succ.id)
                dfs(succ)
        order.append(node)

    dfs(start)
    return order


def _immediate_post_dominators(
    order: list[Node], back_edges: set[tuple[str, str]]
) -> dict[str, str | None]:
    """
    For each node, the closest node every path from it must go through, or None
    if its paths only meet at the end of the process. Back edges are cut.
    """
    # None stands for the end of the process, which is after every node
    pdom: dict[str, frozenset[str | None]] = {}
    for node in order:  # successors come before their predecessors
        succs = _successors(node, back_edges)
        common: set[str | None] = {None}
        if succs:
            common = set(pdom[succs[0].id])
            for succ in succs[1:]:
                common &= pdom[succ.id]
        pdom[node.id] = frozenset(common | {node.id})

    ipdom: dict[str, str | None] = {}
    for node in order:
        strict = pdom[node.id] - {node.id}
        ipdom[node.id] = max(strict, key=lambda p: len(pdom[p]) if p is not None else 0)
    return ipdom


class _LongestPath:
    """
    Longest path through the graph with the back edges cut, counting nodes.
    A path is only worth counting if it reaches a node where `closes` is true.
    With `add_branches`, the branches of a parallel fork are added together,
    otherwise a path takes one branch like any other path.
    """

    def __init__(
        self,
        back_edges: set[tuple[str, str]],
        ipdom: dict[str, str | None],
        nodes: dict[str, Node],
        closes: dict[str, bool],
        add_branches: bool,
    ) -> None:
        self._back_edges = back_edges
        self._ipdom = ipdom
        self._nodes = nodes
        self._closes = closes
        self._add_branches = add_branches
        self._memo: dict[tuple[str, str | None], _Length] = {}

    def from_node(self, node: Node, stop: str | None = None) -> _Length:
        """
        Steps from `node` up to `stop`, which isn't counted. With no `stop`, up to
        the end of the process.
        """
        if node.id == stop:
            return (True, 0)
        key = (node.id, stop)
        if key not in self._memo:
            self._memo[key] = self._compute(node, stop)
        return self._memo[key]

    def _compute(self, node: Node, stop: str | None) -> _Length:
        succs = _successors(node, self._back_edges)

        if (
            self._add_branches
            and isinstance(node, ParallelGatewayNode)
            and len(succs) > 1
        ):
            return self._fork(node, succs, stop)

        options: list[_Length] = []
        closes = self._closes[node.id]
        if closes or not succs:
            options.append((closes and stop is None, 1))
        for succ in succs:
            reaches, steps = self.from_node(succ, stop)
            options.append((reaches, steps + 1))
        return max(options)

    def _fork(self, node: Node, succs: list[Node], stop: str | None) -> _Length:
        # Each branch takes passes of its own up to the join, and the join and
        # everything after it is shared, so it's counted once.
        join = self._ipdom[node.id]
        reaches = True
        total = 1
        for succ in succs:
            branch_reaches, steps = self.from_node(succ, join)
            reaches = reaches and branch_reaches
            total += steps
        if join is not None:
            tail_reaches, steps = self.from_node(self._nodes[join], stop)
            reaches = reaches and tail_reaches
            total += steps
        return (reaches, total)


def _bound_for_start(start: Node, retries: int) -> int:
    back_edges = _find_back_edges(start)
    order = _post_order(start, back_edges)
    nodes = {node.id: node for node in order}
    ipdom = _immediate_post_dominators(order, back_edges)

    ends = {node.id: isinstance(node, EndEvent) for node in order}
    _, acyclic = _LongestPath(back_edges, ipdom, nodes, ends, True).from_node(start)

    # For each node a loop comes back into, the longest cycle through it. A cycle
    # is a single path around the loop, so it takes one branch of a fork.
    loop_heads = {head for _, head in back_edges}
    cycles = 0
    for head in loop_heads:
        closes = {node.id: (node.id, head) in back_edges for node in order}
        _, length = _LongestPath(back_edges, ipdom, nodes, closes, False).from_node(
            nodes[head]
        )
        cycles += length

    return acyclic + cycles * retries


def _bound_for_process(process: Process, retries: int) -> int:
    return max(
        (
            _bound_for_start(start, retries)
            for start in process.get_start_states().values()
        ),
        default=0,
    )


def compute_cbmc_bound(bpmn: Bpmn, retries: int = DEFAULT_RETRIES) -> int:
    """
    Work out how many passes of the generated main() loop cover every path
    through the BPMN.

    Args:
        bpmn (Bpmn): The workflow
        retries (int, optional): How many times each loop is allowed to go
            around again. Defaults to 2.

    Returns:
        int: The number of passes, one per event, task, or gateway firing
    """
    return max(
        (_bound_for_process(process, retries) for process in bpmn.processes.values()),
        default=0,
    )
