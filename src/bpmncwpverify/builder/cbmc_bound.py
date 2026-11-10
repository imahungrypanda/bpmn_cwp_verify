"""
Unwinding bound for CBMC.

The bound returned by `compute_unwind_bound` counts node executions: one step
is one BPMN node being executed by one token. It is the largest number of steps
any single run of all the processes together can take, with these rules:

- A start event runs once, and every process runs concurrently, so the steps of
  all processes and all start events add up.
- An exclusive gateway sends the token down one branch, so it costs the most
  expensive branch.
- A parallel gateway with several outgoing flows sends a token down every
  branch, so it costs the sum of the branches. The join where they meet runs
  once, not once per branch.
- A task with boundary events is treated like a fork with no join: the boundary
  event may fire as well as the task finishing, so every path counts.
- Loops can't be covered for every iteration count, so every loop body is
  counted `loop_iterations` times (nested loops multiply). Two iterations is
  enough to see what the first pass leaves behind for the second.
"""

from bpmncwpverify.core.bpmn import (
    Bpmn,
    ExclusiveGatewayNode,
    Node,
    ParallelGatewayNode,
    Process,
    Task,
)

DEFAULT_LOOP_ITERATIONS = 2


def _successors(node: Node) -> list[Node]:
    successors = [flow.target_node for flow in node.out_flows]
    if isinstance(node, Task):
        successors.extend(node.msg_boundary_events)
    return successors


def _is_join(node: Node) -> bool:
    return isinstance(node, ParallelGatewayNode) and len(node.in_flows) > 1


def _is_fork(node: Node) -> bool:
    return isinstance(node, ParallelGatewayNode) and len(node.out_flows) > 1


class _ProcessBound:
    """Longest run of one process, with every loop back edge cut and weighted."""

    def __init__(self, process: Process, loop_iterations: int) -> None:
        self._loop_iterations = loop_iterations
        self._back_edges: set[tuple[str, str]] = set()
        self._weights: dict[str, int] = {}
        self._memo: dict[str, tuple[int, frozenset[str]]] = {}
        self._nodes: dict[str, Node] = {}
        self._starts = list(process.get_start_states().values())
        self._find_back_edges()
        self._compute_weights()

    def _find_back_edges(self) -> None:
        on_stack: set[str] = set()

        def dfs(node: Node) -> None:
            self._nodes[node.id] = node
            on_stack.add(node.id)
            for succ in _successors(node):
                if succ.id in on_stack:
                    self._back_edges.add((node.id, succ.id))
                elif succ.id not in self._nodes:
                    dfs(succ)
            on_stack.discard(node.id)

        for start in self._starts:
            if start.id not in self._nodes:
                dfs(start)

    def _compute_weights(self) -> None:
        predecessors: dict[str, list[str]] = {id: [] for id in self._nodes}
        for node in self._nodes.values():
            for succ in _successors(node):
                predecessors[succ.id].append(node.id)

        depth = {id: 0 for id in self._nodes}
        # Back edges that share a header form a single loop
        bodies: dict[str, set[str]] = {}
        for tail, header in self._back_edges:
            body = bodies.setdefault(header, {header})
            pending = [tail]
            while pending:
                current = pending.pop()
                if current not in body:
                    body.add(current)
                    pending.extend(predecessors[current])
        for body in bodies.values():
            for id in body:
                depth[id] += 1

        self._weights = {id: self._loop_iterations**d for id, d in depth.items()}

    def _forward(self, node: Node) -> list[Node]:
        return [
            succ
            for succ in _successors(node)
            if (node.id, succ.id) not in self._back_edges
        ]

    def _enter(self, node: Node) -> tuple[int, frozenset[str]]:
        # A join is not part of any one branch; whoever forked resolves it
        if _is_join(node):
            return 0, frozenset({node.id})
        return self._run(node)

    def _run(self, node: Node) -> tuple[int, frozenset[str]]:
        if node.id in self._memo:
            return self._memo[node.id]

        weight = self._weights[node.id]
        branches = [self._enter(succ) for succ in self._forward(node)]
        joins: frozenset[str] = frozenset()
        for _, joined in branches:
            joins |= joined

        result: tuple[int, frozenset[str]]
        if not branches:
            result = (weight, frozenset())
        elif isinstance(node, ExclusiveGatewayNode):
            result = (weight + max(cost for cost, _ in branches), joins)
        else:
            cost = weight + sum(cost for cost, _ in branches)
            if _is_fork(node):
                cost, joins = self._resolve(cost, joins)
            result = (cost, joins)

        self._memo[node.id] = result
        return result

    def _resolve(self, cost: int, joins: frozenset[str]) -> tuple[int, frozenset[str]]:
        """Run each join where this fork's branches meet once, and carry on."""
        carried: frozenset[str] = frozenset()
        for join_id in sorted(joins):
            join_cost, join_joins = self._run(self._nodes[join_id])
            cost += join_cost
            carried |= join_joins
        return cost, carried

    def steps(self) -> int:
        total, unresolved = 0, frozenset[str]()
        for start in self._starts:
            cost, joins = self._run(start)
            total += cost
            unresolved |= joins
        # Joins nobody forked for are still executed once
        total, _ = self._resolve(total, unresolved)
        return total


def compute_unwind_bound(
    bpmn: Bpmn, loop_iterations: int = DEFAULT_LOOP_ITERATIONS
) -> int:
    """
    Compute a CBMC unwinding bound for a BPMN model.

    Args:
        bpmn (Bpmn): The model to bound
        loop_iterations (int, optional): How many times each loop body is
            counted. Defaults to 2.

    Returns:
        int: The most node executions a run can take, plus one, because
        `--unwind N` lets a loop body run N - 1 times before the unwinding
        assertion fails.
    """
    steps = sum(
        _ProcessBound(process, loop_iterations).steps()
        for process in bpmn.processes.values()
    )
    return steps + 1
