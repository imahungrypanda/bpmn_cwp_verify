import re

from returns.result import Failure, Result, Success

from bpmncwpverify.core.bpmn import (
    Bpmn,
    BpmnVisitor,
    EndEvent,
    ExclusiveGatewayNode,
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
HELPER_FUNCS_STR = "unsigned int nondet_uint(void);\n"
NL_NONE = 0
NL_SINGLE = 1
NL_DOUBLE = 2
OCCUPIED_VAR = "occupied"
CHOICE_VAR = "choice"
##############


def _c_name(element_id: str) -> str:
    """Turns a BPMN id into something that is safe to use as a C identifier."""
    name = re.sub(r"\W", "_", element_id)
    return f"_{name}" if name[0].isdigit() else name


class CbmcBpmnGenVisitor(BpmnVisitor):
    """
    Generates the BPMN half of the C program. Each pass of the program's main
    loop picks one transition, assumes it is enabled, and runs it. The
    visitor produces the pieces:

    - places: the token places, one per start event and one per flow
    - ends: one "has this process ended" flag per process
    - enables: one ENABLED_<n> macro per transition
    - transitions: the body of each transition, as the cases of a switch
    - pass_code (after the visit): one pass, ready to go inside the loop

    Nothing in a pass loops over the transitions.
    """

    __slots__ = [
        "defs",
        "places",
        "ends",
        "enables",
        "transitions",
        "errors",
        "_declared",
        "_visited",
        "_process_ended",
        "_end_flags",
        "_num_transitions",
    ]

    def __init__(self) -> None:
        self.defs = StringManager()
        self.places = StringManager()
        self.ends = StringManager()
        self.enables = StringManager()
        self.transitions = StringManager()
        self.errors: list[Error] = []
        self._declared: set[str] = set()
        self._visited: set[str] = set()
        self._process_ended = ""
        self._end_flags: list[str] = []
        self._num_transitions = 0
        self.transitions.indent = 2

    ####################
    # Public interface
    ####################

    @property
    def num_transitions(self) -> int:
        return self._num_transitions

    @property
    def all_ended(self) -> str:
        """C expression that is true once every process has ended."""
        return " && ".join(self._end_flags) if self._end_flags else "1"

    @property
    def pass_code(self) -> str:
        """
        One pass of the main loop: pick a transition, assume it's enabled, run
        it, and check once that no token landed on an occupied place.
        """
        sm = StringManager()
        sm.write_str("{", NL_SINGLE, IndentAction.INC)
        sm.write_str(f"unsigned int {CHOICE_VAR} = nondet_uint();", NL_SINGLE)
        sm.write_str(f"int {OCCUPIED_VAR} = 0;", NL_SINGLE)
        sm.write_str(f"switch ({CHOICE_VAR}) {{", NL_SINGLE)
        sm.write_str(self.transitions)
        sm.write_str("\tdefault:", NL_SINGLE)
        sm.write_str("\t\t__CPROVER_assume(0);", NL_SINGLE)
        sm.write_str("\t\tbreak;", NL_SINGLE)
        sm.write_str("}", NL_SINGLE)
        sm.write_str(
            f'__CPROVER_assert(!{OCCUPIED_VAR}, "token placed on an occupied place");',
            NL_SINGLE,
        )
        sm.write_str("}", NL_SINGLE, IndentAction.DEC)
        return repr(sm)

    def result(self) -> Result["CbmcBpmnGenVisitor", Error]:
        if self.errors:
            return Failure(self.errors[0])
        return Success(self)

    def __repr__(self) -> str:
        return f"{self.defs}{self.places}{self.ends}{self.enables}"

    ####################
    # Helpers
    ####################

    def _place(self, element_id: str) -> str:
        return f"tok_{_c_name(element_id)}"

    def _in_places(self, node: Node) -> tuple[list[str], list[str]]:
        """(sequence places, message places) that feed the node."""
        seq = [self._place(f.id) for f in node.in_flows]
        msg = [self._place(m.id) for m in node.in_msgs]
        if not (seq or msg):
            seq = [self._place(node.id)]
        return seq, msg

    def _out_places(self, node: Node) -> list[str]:
        return [self._place(f.id) for f in node.out_flows + node.out_msgs]

    def _declare(self, place: str, initial: int = 0) -> None:
        if place not in self._declared:
            self._declared.add(place)
            self.places.write_str(f"int {place} = {initial};", NL_SINGLE)

    def _declare_places(self, node: Node) -> None:
        seq, msg = self._in_places(node)
        for place in seq + msg + self._out_places(node):
            self._declare(place)

    def _first_visit(self, node: Node) -> bool:
        if node.id in self._visited:
            return False
        self._visited.add(node.id)
        self._declare_places(node)
        return True

    def _unsupported(self, element_id: str, element_type: str) -> None:
        self.errors.append(BpmnCbmcUnsupportedElementError(element_id, element_type))

    def _enable_condition(self, node: Node, flow_expr: str = "") -> str:
        seq, msg = self._in_places(node)
        parts = ["(" + " || ".join(seq) + ")"]
        if msg:
            parts.append("(" + " && ".join(msg) + ")")
        if flow_expr:
            parts.append(f"({flow_expr.replace(chr(10), ' ').strip()})")
        return " && ".join(parts)

    def _gen_task_behavior(self, task: Task) -> StringManager:
        """Placeholder: task behaviors are not generated yet."""
        return StringManager()

    def _gen_transition(
        self,
        node: Node,
        out_places: list[str],
        flow_expr: str = "",
        behavior: StringManager | None = None,
        end: bool = False,
        label: str = "",
    ) -> None:
        index = self._num_transitions
        self._num_transitions += 1

        self.enables.write_str(f"/* {label or node.id} */", NL_SINGLE)
        self.enables.write_str(
            f"#define ENABLED_{index} ({self._enable_condition(node, flow_expr)})",
            NL_SINGLE,
        )

        seq, msg = self._in_places(node)
        sm = self.transitions
        sm.write_str(f"case {index}: /* {label or node.id} */", NL_SINGLE)
        sm.write_str(f"__CPROVER_assume(ENABLED_{index});", NL_SINGLE, IndentAction.INC)
        for place in seq + msg:
            sm.write_str(f"{place} = 0;", NL_SINGLE)
        if behavior is not None:
            sm.write_str(behavior)
        if out_places:
            sm.write_str(
                f"{OCCUPIED_VAR} = {' || '.join(out_places)};",
                NL_SINGLE,
            )
            for place in out_places:
                sm.write_str(f"{place} = 1;", NL_SINGLE)
        if end:
            sm.write_str(f"{self._process_ended} = 1;", NL_SINGLE)
        sm.write_str("break;", NL_SINGLE, IndentAction.DEC)

    ####################
    # Visitor Methods
    ####################

    def visit_start_event(self, event: StartEvent) -> bool:
        if event.id in self._visited:
            return True
        if not (event.in_flows or event.in_msgs):
            # The start event's own place holds the initial token
            self._declare(self._place(event.id), 1)
        self._first_visit(event)
        self._gen_transition(event, self._out_places(event))
        return True

    def visit_end_event(self, event: EndEvent) -> bool:
        if self._first_visit(event):
            self._gen_transition(event, [], end=True)
        return True

    def visit_intermediate_event(self, event: IntermediateEvent) -> bool:
        if self._first_visit(event):
            self._gen_transition(event, self._out_places(event))
        return True

    def visit_task(self, task: Task) -> bool:
        if self._first_visit(task):
            self._gen_transition(
                task, self._out_places(task), behavior=self._gen_task_behavior(task)
            )
        return True

    def visit_boundary_event(self, boundary_event: Task.BoundaryEvent) -> bool:
        self._unsupported(boundary_event.id, "boundary event")
        return False

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        if not self._first_visit(gateway):
            return True
        flows = gateway.out_flows
        if len(flows) > 1 and not all(f.expression for f in flows):
            self._unsupported(
                gateway.id, "exclusive gateway with a flow lacking a condition"
            )
            return True
        if not flows:
            self._unsupported(gateway.id, "exclusive gateway with no outgoing flow")
            return True
        for flow in flows:
            self._gen_transition(
                gateway,
                [self._place(flow.id)] + [self._place(m.id) for m in gateway.out_msgs],
                flow_expr=flow.expression,
                label=f"{gateway.id} -> {flow.id}",
            )
        return True

    def visit_parallel_gateway(self, gateway: ParallelGatewayNode) -> bool:
        self._unsupported(gateway.id, "parallel gateway")
        return False

    def visit_message_flow(self, flow: MessageFlow) -> bool:
        # Message flows are places, declared by the nodes at their ends
        return True

    def visit_process(self, process: Process) -> bool:
        self._process_ended = f"ended_{_c_name(process.id)}"
        self._end_flags.append(self._process_ended)
        self.ends.write_str(f"int {self._process_ended} = 0;", NL_SINGLE)
        return True

    def visit_bpmn(self, bpmn: Bpmn) -> bool:
        self.defs.write_str(HELPER_FUNCS_STR, NL_SINGLE)
        return True
