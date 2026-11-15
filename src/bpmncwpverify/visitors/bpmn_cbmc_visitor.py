from returns.result import Failure, Result, Success

from bpmncwpverify.core.bpmn import (
    Bpmn,
    BpmnVisitor,
    EndEvent,
    ExclusiveGatewayNode,
    Flow,
    IntermediateEvent,
    MessageFlow,
    Node,
    ParallelGatewayNode,
    Process,
    StartEvent,
    Task,
)
from bpmncwpverify.core.error import BpmnCbmcUnsupportedElementError, Error
from bpmncwpverify.util.stringmanager import IndentAction, StringManager

##############
# Constants
##############
NL_NONE = 0
NL_SINGLE = 1
NL_DOUBLE = 2

DEFS_STR = "unsigned int nondet_uint(void);\n"
STEP_FUNC_NAME = "bpmn_step"
TRANSITION_VAR = "transition"
CLASH_VAR = "token_clash"
CLASH_MSG = "Attempting to place token in already-occupied place"
STUCK_MSG = "No viable path to take"


class Transition:
    """
    One thing the workflow can do in a single pass: an enable condition and the
    statements that run when it is taken.
    """

    __slots__ = ["label", "enable", "body"]

    def __init__(self, label: str, enable: str, body: list[str]) -> None:
        self.label = label
        self.enable = enable
        self.body = body


class CbmcGenVisitor(BpmnVisitor):
    """
    Turns BPMN into the pieces of a C program that models how the workflow runs.

    - `places`: one boolean per start event and per sequence/message flow
    - `step`: one pass of the main loop. It picks one transition
      nondeterministically, assumes it is enabled, and runs it. There is no
      loop over the transitions.

    The caller puts `step` in the main loop and stops when `all_ended` holds.
    Elements that cannot be expressed are collected in `errors`.
    """

    __slots__ = [
        "defs",
        "places",
        "process_ids",
        "transitions",
        "errors",
        "_seen",
        "_place_names",
        "_current_process",
    ]

    def __init__(self) -> None:
        self.defs = StringManager()
        self.places = StringManager()
        self.process_ids: list[str] = []
        self.transitions: list[Transition] = []
        self.errors: list[Error] = []
        self._seen: set[str] = set()
        self._place_names: set[str] = set()
        self._current_process = ""

    ####################
    # Helpers
    ####################

    @staticmethod
    def _flow_place(flow: Flow) -> str:
        return f"{flow.target_node.id}_FROM_{flow.source_node.id}"

    @staticmethod
    def _ended_var(process_id: str) -> str:
        return f"{process_id}_ended"

    def _in_places(self, node: Node) -> tuple[list[str], list[str]]:
        """
        Returns (sequence places, message places) a node consumes from. A node
        with no incoming flows at all gets a standalone place named after itself.
        """
        if not (node.in_flows or node.in_msgs):
            return [node.id], []
        return (
            [self._flow_place(f) for f in node.in_flows],
            [self._flow_place(f) for f in node.in_msgs],
        )

    def _out_places(self, node: Node) -> list[str]:
        return [self._flow_place(f) for f in node.out_flows + node.out_msgs]

    def _declare_place(self, name: str, initial: bool = False) -> None:
        if name in self._place_names:
            return
        self._place_names.add(name)
        self.places.write_str(f"bool {name} = {int(initial)};", NL_SINGLE)

    def _declare_in_places(self, node: Node) -> None:
        seq, msgs = self._in_places(node)
        for place in seq + msgs:
            self._declare_place(
                place, initial=isinstance(node, StartEvent) and place == node.id
            )

    def _enable_condition(self, node: Node) -> str:
        """
        Any incoming sequence place has a token, and every incoming message
        place has one.
        """
        seq, msgs = self._in_places(node)
        parts: list[str] = []
        if seq:
            parts.append("(" + " || ".join(seq) + ")")
        if msgs:
            parts.append("(" + " && ".join(msgs) + ")")
        return " && ".join(parts)

    def _put_tokens(self, places: list[str]) -> list[str]:
        """
        Sets the places. Whether any of them was already occupied is recorded
        in one flag, which is asserted once per pass, after the transition.
        """
        if not places:
            return [f"{CLASH_VAR} = 0;"]
        return [f"{CLASH_VAR} = {' || '.join(places)};"] + [
            f"{place} = 1;" for place in places
        ]

    def _consume_tokens(self, node: Node) -> list[str]:
        seq, msgs = self._in_places(node)
        return [f"{place} = 0;" for place in seq + msgs]

    def _unsupported(self, element: Node, element_type: str) -> None:
        self.errors.append(BpmnCbmcUnsupportedElementError(element.id, element_type))

    def _first_visit(self, node: Node) -> bool:
        if node.id in self._seen:
            return False
        self._seen.add(node.id)
        return True

    def _add_node_transition(
        self, node: Node, behavior: list[str] | None = None, ends: bool = False
    ) -> None:
        self._declare_in_places(node)
        body = self._consume_tokens(node)
        body.extend(behavior or [])
        if ends:
            body.append(f"{self._ended_var(self._current_process)} = 1;")
        body.extend(self._put_tokens(self._out_places(node)))
        self.transitions.append(Transition(node.id, self._enable_condition(node), body))

    ####################
    # Output
    ####################

    @property
    def all_ended(self) -> str:
        """C expression that is true when every process has ended."""
        if not self.process_ids:
            return "1"
        return " && ".join(self._ended_var(p) for p in self.process_ids)

    @property
    def step(self) -> StringManager:
        """One pass of the loop: pick one transition, assume it enabled, run it."""
        sm = StringManager()
        sm.write_str(
            f"static void {STEP_FUNC_NAME}(void) {{", NL_SINGLE, IndentAction.INC
        )
        sm.write_str(f"unsigned int {TRANSITION_VAR} = nondet_uint();", NL_SINGLE)
        sm.write_str(f"bool {CLASH_VAR} = 0;", NL_SINGLE)
        sm.write_str(
            f"__CPROVER_assume({TRANSITION_VAR} < {len(self.transitions)}u);", NL_SINGLE
        )
        sm.write_str(f"switch ({TRANSITION_VAR}) {{", NL_SINGLE)
        for index, transition in enumerate(self.transitions):
            sm.write_str(
                f"case {index}: /* {transition.label} */", NL_SINGLE, IndentAction.INC
            )
            sm.write_str(f"__CPROVER_assume({transition.enable});", NL_SINGLE)
            for line in transition.body:
                sm.write_str(line, NL_SINGLE)
            sm.write_str("break;", NL_SINGLE, IndentAction.DEC)
        sm.write_str("default:", NL_SINGLE, IndentAction.INC)
        sm.write_str("break;", NL_SINGLE, IndentAction.DEC)
        sm.write_str("}", NL_SINGLE)
        sm.write_str(f'__CPROVER_assert(!{CLASH_VAR}, "{CLASH_MSG}");', NL_SINGLE)
        sm.write_str("}", NL_SINGLE, IndentAction.DEC)
        return sm

    def result(self) -> Result[str, Error]:
        if self.errors:
            return Failure(self.errors[0])
        return Success(repr(self))

    def __repr__(self) -> str:
        ended = StringManager()
        for process_id in self.process_ids:
            ended.write_str(f"bool {self._ended_var(process_id)} = 0;", NL_SINGLE)
        return f"{self.defs}{self.places}{ended}\n{self.step}"

    ####################
    # Visitor Methods
    ####################

    def visit_start_event(self, event: StartEvent) -> bool:
        if not self._first_visit(event):
            return False
        self._add_node_transition(event)
        return True

    def visit_end_event(self, event: EndEvent) -> bool:
        if not self._first_visit(event):
            return False
        self._add_node_transition(event, ends=True)
        return True

    def visit_intermediate_event(self, event: IntermediateEvent) -> bool:
        if not self._first_visit(event):
            return False
        self._add_node_transition(event)
        return True

    def visit_task(self, task: Task) -> bool:
        if not self._first_visit(task):
            return False
        if task.msg_boundary_events:
            self._unsupported(task, "Task with boundary events")
            return False
        # S4 fills in the task's behavior
        self._add_node_transition(task, [f"/* behavior of {task.id} */"])
        return True

    def visit_boundary_event(self, boundary_event: Task.BoundaryEvent) -> bool:
        self._unsupported(boundary_event, "BoundaryEvent")
        return False

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        if not self._first_visit(gateway):
            return False
        self._declare_in_places(gateway)
        enable = self._enable_condition(gateway)
        consume = self._consume_tokens(gateway)

        # One transition per outgoing flow, guarded by the flow's condition.
        # A flow with no condition is always open.
        conditions: list[str] = []
        for flow in gateway.out_flows:
            condition = flow.expression.replace("\n", " ").strip() or "1"
            conditions.append(f"({condition})")
            self.transitions.append(
                Transition(
                    f"{gateway.id} -> {flow.id}",
                    f"{enable} && {conditions[-1]}",
                    consume + self._put_tokens([self._flow_place(flow)]),
                )
            )

        # Like SPIN, a token that no flow can take is a failure, not a silent stop.
        self.transitions.append(
            Transition(
                f"{gateway.id} stuck",
                f"{enable} && !({' || '.join(conditions) or '0'})",
                [f'__CPROVER_assert(0, "{STUCK_MSG}");'],
            )
        )
        return True

    def visit_parallel_gateway(self, gateway: ParallelGatewayNode) -> bool:
        # S4 handles parallel gateways
        self._unsupported(gateway, "ParallelGatewayNode")
        return False

    def visit_message_flow(self, flow: MessageFlow) -> bool:
        # A message flow is a place, declared with the node that consumes it
        return True

    def visit_process(self, process: Process) -> bool:
        self._current_process = process.id
        self.process_ids.append(process.id)
        return True

    def visit_bpmn(self, bpmn: Bpmn) -> bool:
        self.defs.write_str(DEFS_STR, NL_SINGLE)
        return True
