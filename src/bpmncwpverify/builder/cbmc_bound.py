from bpmncwpverify.core.bpmn import (
    Bpmn,
    Node,
    ParallelGatewayNode,
    Process,
    StartEvent,
)

DEFAULT_RETRIES = 2

# Longest way to a terminal: (steps, nodes on that way). The terminal is the id
# of the parallel join that ends a branch, or None when it ends at an end event.
_Ways = dict[str | None, tuple[int, frozenset[str]]]


def _targets(node: Node) -> list[Node]:
    return [flow.target_node for flow in node.out_flows]


def _is_fork(node: Node) -> bool:
    return isinstance(node, ParallelGatewayNode) and len(node.out_flows) > 1


def _is_join(node: Node) -> bool:
    return isinstance(node, ParallelGatewayNode) and len(node.in_flows) > 1


def _merge(
    ways: _Ways, terminal: str | None, steps: int, nodes: frozenset[str]
) -> None:
    if terminal not in ways or ways[terminal][0] < steps:
        ways[terminal] = (steps, nodes)


def _longest_ways(
    node: Node, path: frozenset[str], in_branch: bool, matched_join: bool = False
) -> _Ways:
    """
    Longest ways forward from node, with edges back onto the path cut.

    Inside a parallel branch (in_branch) the walk stops in front of a join,
    since the join belongs to the fork that opened the branch.
    """
    if in_branch and not matched_join and _is_join(node):
        return {node.id: (0, frozenset())}
    path = path | {node.id}
    successors = [t for t in _targets(node) if t.id not in path]
    if not node.out_flows:
        return {None: (1, frozenset({node.id}))}
    if _is_fork(node):
        return _fork_ways(node, successors, path, in_branch)

    ways: _Ways = {}
    for successor in successors:
        for terminal, (steps, nodes) in _longest_ways(
            successor, path, in_branch
        ).items():
            _merge(ways, terminal, steps + 1, nodes | {node.id})
    return ways


def _fork_ways(
    fork: Node, successors: list[Node], path: frozenset[str], in_branch: bool
) -> _Ways:
    branches = [_longest_ways(s, path, True) for s in successors]
    branches = [b for b in branches if b]
    if not branches:
        return {}

    joins: set[str | None] = set(branches[0])
    for branch in branches[1:]:
        joins &= set(branch)
    joins.discard(None)
    if not joins:
        # The branches never meet, so every one of them runs to its own end.
        steps = 1 + sum(max(s for s, _ in b.values()) for b in branches)
        nodes = frozenset({fork.id}).union(
            *(max(b.values(), key=lambda w: w[0])[1] for b in branches)
        )
        return {None: (steps, nodes)}

    ways: _Ways = {}
    for join_id in sorted(j for j in joins if j is not None):
        steps = 1 + sum(b[join_id][0] for b in branches)
        nodes = frozenset({fork.id}).union(*(b[join_id][1] for b in branches))
        join = next(
            t for t in _reachable(fork) if t.id == join_id
        )  # the join is reachable by construction
        for terminal, (rest, rest_nodes) in _longest_ways(
            join, path | nodes, in_branch, matched_join=True
        ).items():
            _merge(ways, terminal, steps + rest, nodes | rest_nodes)
    return ways


def _reachable(start: Node) -> list[Node]:
    seen: dict[str, Node] = {}
    stack = [start]
    while stack:
        node = stack.pop()
        if node.id in seen:
            continue
        seen[node.id] = node
        stack.extend(_targets(node))
    return list(seen.values())


def _back_edges(start: Node) -> list[tuple[Node, Node]]:
    """Edges (source, target) that close a loop in a depth-first walk from start."""
    edges: list[tuple[Node, Node]] = []
    done: set[str] = set()

    def visit(node: Node, on_path: set[str]) -> None:
        on_path.add(node.id)
        for target in _targets(node):
            if target.id in on_path:
                edges.append((node, target))
            elif target.id not in done:
                visit(target, on_path)
        on_path.discard(node.id)
        done.add(node.id)

    visit(start, set())
    return edges


def _longest_simple_path(source: Node, target: Node) -> int:
    """Number of nodes on the longest simple path from source to target."""

    def walk(node: Node, on_path: frozenset[str]) -> int:
        if node.id == target.id:
            return 1
        on_path = on_path | {node.id}
        best = 0
        for successor in _targets(node):
            if successor.id not in on_path:
                length = walk(successor, on_path)
                if length:
                    best = max(best, length + 1)
        return best

    return walk(source, frozenset())


def _bound_from_start(start: StartEvent, retries: int) -> int:
    ways = _longest_ways(start, frozenset(), False)
    base = ways[None][0] if None in ways else 0

    # The longest cycle through each node that a loop comes back into.
    cycles: dict[str, int] = {}
    for source, target in _back_edges(start):
        length = _longest_simple_path(target, source)
        cycles[target.id] = max(cycles.get(target.id, 0), length)
    return base + retries * sum(cycles.values())


def _bound_from_process(process: Process, retries: int) -> int:
    return max(
        (_bound_from_start(s, retries) for s in process.get_start_states().values()),
        default=0,
    )


def compute_bound(bpmn: Bpmn, retries: int = DEFAULT_RETRIES) -> int:
    """
    Number of passes of the C main loop needed to cover every path of the BPMN.

    Args:
        bpmn (Bpmn): The workflow to bound
        retries (int, optional): How many times each loop is retried. Defaults to 2.
    """
    return max(
        (_bound_from_process(p, retries) for p in bpmn.processes.values()),
        default=0,
    )
