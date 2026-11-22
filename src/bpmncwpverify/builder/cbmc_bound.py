from bpmncwpverify.core.bpmn import (
    Bpmn,
    Node,
    ParallelGatewayNode,
    Task,
)

DEFAULT_RETRIES = 2

# Steps of a path that never reaches an end event, because every way on loops back
_DEAD = -(10**9)

# (steps, nodes visited while computing them). The visited set tells us whether a
# cached result is still valid under a different path to the same node.
_Result = tuple[int, frozenset[str]]


def _successors(node: Node) -> list[Node]:
    """
    Nodes that can fire right after this one. A boundary event is an
    alternative to the task's own outgoing flows.
    """
    succ = [flow.target_node for flow in node.out_flows]
    if isinstance(node, Task):
        succ.extend(node.msg_boundary_events)
    return succ


def _reachable(starts: list[Node], blocked: frozenset[str]) -> set[str]:
    seen: set[str] = set()
    stack = [n for n in starts if n.id not in blocked]
    while stack:
        node = stack.pop()
        if node.id in seen:
            continue
        seen.add(node.id)
        stack.extend(n for n in _successors(node) if n.id not in blocked)
    return seen


class _BoundCalculator:
    __slots__ = ["_cache", "_retries"]

    def __init__(self, retries: int) -> None:
        self._retries = retries
        self._cache: dict[tuple[str, str | None], _Result] = {}

    def _matching_join(
        self, fork: Node, branches: list[Node], on_path: frozenset[str]
    ) -> Node | None:
        """
        The nearest parallel join that every branch of the fork reaches
        """
        reach = [_reachable([b], on_path) for b in branches]
        common = reach[0].intersection(*reach[1:])
        joins = [
            n
            for n in _reachable_nodes(fork)
            if n.id in common
            and isinstance(n, ParallelGatewayNode)
            and len(n.in_flows) > 1
        ]
        # The nearest join is the one no other candidate leads to
        for join in joins:
            others = [j for j in joins if j is not join]
            if not any(join.id in _reachable([j], frozenset()) for j in others):
                return join
        return None

    def longest(
        self, node: Node, on_path: frozenset[str], until: Node | None
    ) -> _Result:
        """
        Steps from node to an end event, stopping short of the join `until`.
        Edges back into the current path are dead ends, and a path that has
        nowhere else to go doesn't count.
        """
        if until is not None and node is until:
            return 0, frozenset({node.id})

        key = (node.id, until.id if until else None)
        cached = self._cache.get(key)
        if cached is not None and cached[1].isdisjoint(on_path):
            return cached

        path = on_path | {node.id}
        all_succ = _successors(node)
        succ = [n for n in all_succ if n.id not in path]
        visited = {node.id}
        best = 0 if not all_succ else _DEAD

        is_fork = isinstance(node, ParallelGatewayNode) and len(node.out_flows) > 1
        if is_fork and succ:
            join = self._matching_join(node, succ, path)
            parts = [(b, join) for b in succ]
            if join is not None:
                # The part after the join is shared, so it is counted once
                parts.append((join, until))
            total = 0
            for branch, stop in parts:
                steps, seen = self.longest(branch, path, stop)
                total = _DEAD if _DEAD in (total, steps) else total + steps
                visited |= seen
            best = total
        else:
            for nxt in succ:
                steps, seen = self.longest(nxt, path, until)
                best = max(best, steps)
                visited |= seen

        result = (_DEAD if best == _DEAD else 1 + best, frozenset(visited))
        # Results that touched the current path depend on it, so they aren't cached
        if result[1].isdisjoint(on_path):
            self._cache[key] = result
        return result

    def back_edges(self, start: Node) -> dict[str, tuple[Node, list[Node]]]:
        """
        Nodes that an edge comes back into, found by a depth-first walk from start,
        each with the nodes the edges come back from
        """
        heads: dict[str, tuple[Node, list[Node]]] = {}
        done: set[str] = set()
        stack: list[str] = []

        def walk(node: Node) -> None:
            stack.append(node.id)
            for nxt in _successors(node):
                if nxt.id in stack:
                    heads.setdefault(nxt.id, (nxt, []))[1].append(node)
                elif nxt.id not in done:
                    walk(nxt)
            stack.pop()
            done.add(node.id)

        walk(start)
        return heads

    def longest_cycle(self, head: Node, tails: list[Node]) -> int:
        """
        Number of nodes in the longest simple path from head to one of the nodes
        whose edge closes the loop back into head
        """
        best = 0

        def walk(node: Node, on_path: frozenset[str]) -> None:
            nonlocal best
            if node in tails:
                best = max(best, len(on_path))
            for nxt in _successors(node):
                if nxt.id not in on_path:
                    walk(nxt, on_path | {nxt.id})

        walk(head, frozenset({head.id}))
        return best

    def bound(self, start: Node) -> int:
        steps = max(self.longest(start, frozenset(), None)[0], 0)
        loops = sum(
            self.longest_cycle(head, tails)
            for head, tails in self.back_edges(start).values()
        )
        return steps + loops * self._retries


def _reachable_nodes(start: Node) -> list[Node]:
    seen: dict[str, Node] = {}
    stack = [start]
    while stack:
        node = stack.pop()
        if node.id in seen:
            continue
        seen[node.id] = node
        stack.extend(_successors(node))
    return list(seen.values())


def compute_bound(bpmn: Bpmn, retries: int = DEFAULT_RETRIES) -> int:
    """
    Number of passes of the CBMC main loop needed to cover every path of the BPMN

    Args:
        bpmn (Bpmn): The workflow
        retries (int): How many times each loop is taken again. Defaults to 2.

    Returns:
        int: The largest bound over all processes and start events
    """
    calculator = _BoundCalculator(retries)
    bounds = [
        calculator.bound(start)
        for process in bpmn.processes.values()
        for start in process.get_start_states().values()
    ]
    return max(bounds, default=0)
