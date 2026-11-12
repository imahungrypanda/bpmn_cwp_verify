from bpmncwpverify.core.bpmn import (
    Bpmn,
    EndEvent,
    Node,
    ParallelGatewayNode,
    Process,
    StartEvent,
)

DEFAULT_RETRIES = 2

# Result of walking a path: (steps taken, join the path stopped at, if any)
_Walk = tuple[int, Node | None]


def _is_join(node: Node) -> bool:
    # A gateway that also forks is walked as a fork: its extra incoming flows
    # are loops back into it.
    return (
        isinstance(node, ParallelGatewayNode)
        and len(node.in_flows) > 1
        and len(node.out_flows) <= 1
    )


class _ProcessBound:
    """
    Computes the number of passes of main()'s loop needed for one start event
    """

    def __init__(self) -> None:
        self.loop_heads: dict[str, Node] = {}
        self.visit_order: dict[str, int] = {}

    def walk(self, node: Node, path: frozenset[str], past_join: bool = False) -> _Walk:
        """
        Longest acyclic walk from node, counting each node as one step.

        A walk stops, uncounted, at a parallel join, unless past_join is set.
        Returns the steps taken and the join it stopped at.
        """
        if _is_join(node) and not past_join:
            return 0, node
        self.visit_order.setdefault(node.id, len(self.visit_order))
        path = path | {node.id}
        if isinstance(node, EndEvent) or not node.out_flows:
            return 1, None
        if isinstance(node, ParallelGatewayNode) and len(node.out_flows) > 1:
            return self._fork(node, path)
        return self._choice(node, path)

    def _choice(self, node: Node, path: frozenset[str]) -> _Walk:
        """
        Take the longest outgoing branch. A branch back onto the path is a dead end.
        """
        best: _Walk = (0, None)
        for flow in node.out_flows:
            target = flow.target_node
            if target.id in path:
                self.loop_heads[target.id] = target
                continue
            steps, join = self.walk(target, path)
            if steps > best[0] or (steps == best[0] and best[1] is None):
                best = (steps, join if join is not None else best[1])
            elif join is not None and best[1] is None:
                best = (best[0], join)
        return best[0] + 1, best[1]

    def _fork(self, node: Node, path: frozenset[str]) -> _Walk:
        """
        Add the branches together, then count what follows the join once.
        """
        total = 1
        join: Node | None = None
        for flow in node.out_flows:
            target = flow.target_node
            if target.id in path:
                self.loop_heads[target.id] = target
                continue
            steps, branch_join = self.walk(target, path)
            total += steps
            join = join or branch_join
        if join is None:
            return total, None
        if join.id in path:
            return total, None
        steps, outer_join = self.walk_past_join(join, path)
        return total + steps, outer_join

    def walk_past_join(self, join: Node, path: frozenset[str]) -> _Walk:
        return self.walk(join, path, past_join=True)


def _longest_cycle(head: Node, outer: set[str]) -> int:
    """
    Number of nodes on the longest simple cycle through head that stays
    clear of the outer loops' heads
    """
    best = 0
    stack: list[tuple[Node, frozenset[str]]] = [(head, frozenset({head.id}))]
    while stack:
        node, path = stack.pop()
        for flow in node.out_flows:
            target = flow.target_node
            if target is head:
                best = max(best, len(path))
            elif target.id not in path and target.id not in outer:
                stack.append((target, path | {target.id}))
    return best


def _start_event_bound(start: StartEvent, retries: int) -> int:
    walker = _ProcessBound()
    steps, _ = walker.walk(start, frozenset())
    # An inner loop is counted without the outer loop around it, so nested
    # loops add up instead of multiplying. Outer heads are reached first.
    heads = sorted(walker.loop_heads.values(), key=lambda h: walker.visit_order[h.id])
    loops = sum(
        _longest_cycle(head, {outer.id for outer in heads[:i]})
        for i, head in enumerate(heads)
    )
    return steps + loops * retries


def _process_bound(process: Process, retries: int) -> int:
    return max(
        (_start_event_bound(s, retries) for s in process.get_start_states().values()),
        default=0,
    )


def compute_unwinding_bound(bpmn: Bpmn, retries: int = DEFAULT_RETRIES) -> int:
    """
    Number of passes of the generated main() loop needed to cover every path

    Args:
        bpmn (Bpmn): The workflow
        retries (int): How many extra times each loop is allowed to run
    """
    return max(
        (_process_bound(process, retries) for process in bpmn.processes.values()),
        default=0,
    )
