from collections.abc import Sequence

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
from bpmncwpverify.util.stringmanager import (
    NL_DOUBLE,
    NL_SINGLE,
    IndentAction,
    StringManager,
)

##############
# Constants
##############
START_STR = "//**********BPMN TOKEN PLACES************//"
END_STR = "//***************************************//"
TOKEN_PREFIX = "tok_"
DONE_PREFIX = "done_"
STEP_FUNC = "bpmn_step"
CHOICE_VAR = "bpmn_choice"
COLLISION_VAR = "bpmn_collision"
NONDET_DECL = "unsigned int nondet_uint(void);"
COLLISION_MSG = "Attempting to place token in already-occupied place"


def _place(flow_or_node_id: str) -> str:
    return f"{TOKEN_PREFIX}{flow_or_node_id}"


class Transition:
    """One thing that can fire in a pass: an enable condition and a body."""

    __slots__ = ["name", "enable", "body"]

    def __init__(self, name: str, enable: str, body: StringManager) -> None:
        self.name = name
        self.enable = enable
        self.body = body


class BpmnCbmcVisitor(BpmnVisitor):
    """
    Generates C for the BPMN processes. Token places are `_Bool` globals, one
    per start event and one per sequence/message flow. Each start event, task,
    end event, intermediate event and each outgoing flow of an exclusive
    gateway is a transition.

    `bpmn_step()` is one pass of the main loop: it picks exactly one
    transition nondeterministically, assumes it is enabled and runs it, with
    no loop over the transitions. A body clears the incoming places, then
    sets the outgoing ones. A token landing on an occupied place is asserted
    once per pass, after the transition.

    - `done_expr` is true when every process has reached an end event.
    - `get_result()` is a failure if an element can't be expressed (parallel
      gateways and boundary events are not supported yet).
    """

    __slots__ = [
        "places",
        "process_ids",
        "transitions",
        "errors",
        "_seen",
        "_process_id",
        "defs",
        "step_func",
    ]

    def __init__(self) -> None:
        self.places: dict[str, int] = {}  # place name -> initial value
        self.process_ids: list[str] = []
        self.transitions: list[Transition] = []
        self.errors: list[Error] = []
        self._seen: set[str] = set()
        self._process_id = ""
        self.defs = StringManager()
        self.step_func = StringManager()

    ####################
    # Helpers
    ####################

    @property
    def done_expr(self) -> str:
        return " && ".join(f"{DONE_PREFIX}{pid}" for pid in self.process_ids) or "1"

    def get_result(self) -> Result[str, Error]:
        if self.errors:
            return Failure(self.errors[0])
        return Success(repr(self))

    @staticmethod
    def _flow_places(flows: Sequence[Flow]) -> list[str]:
        return [_place(flow.id) for flow in flows]

    def _in_places(self, node: Node) -> tuple[list[str], list[str]]:
        """(sequence places, message places) feeding the node."""
        return self._flow_places(node.in_flows), self._flow_places(node.in_msgs)

    def _out_places(self, node: Node) -> list[str]:
        return self._flow_places(node.out_flows) + self._flow_places(node.out_msgs)

    def _declare_places(self, node: Node) -> None:
        for flow in node.in_flows + node.out_flows + node.in_msgs + node.out_msgs:
            self.places.setdefault(_place(flow.id), 0)

    def _enable(self, node: Node, extra: str = "") -> str:
        """
        One of the incoming sequence places has a token and all of the incoming
        message places do. A node with no incoming flows (start event) uses its
        own place.
        """
        seq, msgs = self._in_places(node)
        if not (seq or msgs):
            seq = [_place(node.id)]
        parts: list[str] = []
        if seq:
            parts.append("(" + " || ".join(seq) + ")")
        if msgs:
            parts.append("(" + " && ".join(msgs) + ")")
        if extra:
            parts.append(f"({extra})")
        return " && ".join(parts)

    def _body(
        self,
        node: Node,
        out_places: list[str],
        extra_lines: list[str] | None = None,
    ) -> StringManager:
        seq, msgs = self._in_places(node)
        if not (seq or msgs):
            seq = [_place(node.id)]
        body = StringManager()
        body.write_str(f"// {type(node).__name__} {node.id}", NL_SINGLE)
        for place in seq + msgs:
            body.write_str(f"{place} = 0;", NL_SINGLE)
        for line in extra_lines or []:
            body.write_str(line, NL_SINGLE)
        if out_places:
            body.write_str(
                f"{COLLISION_VAR} = {' || '.join(out_places)};",
                NL_SINGLE,
            )
        for place in out_places:
            body.write_str(f"{place} = 1;", NL_SINGLE)
        return body

    def _add_transition(self, name: str, enable: str, body: StringManager) -> None:
        self.transitions.append(Transition(name, enable, body))

    def _first_visit(self, node: Node) -> bool:
        if node.id in self._seen:
            return False
        self._seen.add(node.id)
        self._declare_places(node)
        return True

    def _unsupported(self, element_id: str, element_type: str) -> bool:
        self.errors.append(BpmnCbmcUnsupportedElementError(element_id, element_type))
        return False

    def _simple_node(self, node: Node, extra_lines: list[str] | None = None) -> bool:
        if self._first_visit(node):
            self._add_transition(
                node.id,
                self._enable(node),
                self._body(node, self._out_places(node), extra_lines),
            )
        return True

    ####################
    # Visitor Methods
    ####################

    def visit_start_event(self, event: StartEvent) -> bool:
        if not (event.in_flows or event.in_msgs):
            self.places[_place(event.id)] = 1
        return self._simple_node(event)

    def visit_end_event(self, event: EndEvent) -> bool:
        return self._simple_node(event, [f"{DONE_PREFIX}{self._process_id} = 1;"])

    def visit_intermediate_event(self, event: IntermediateEvent) -> bool:
        return self._simple_node(event)

    def visit_task(self, task: Task) -> bool:
        # Behaviors are not generated yet, only a marker where they go.
        return self._simple_node(task, [f"// behavior of {task.id}"])

    def visit_boundary_event(self, boundary_event: Task.BoundaryEvent) -> bool:
        return self._unsupported(boundary_event.id, "boundary event")

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        if not self._first_visit(gateway):
            return True
        for flow in gateway.out_flows:
            expr = flow.expression.replace("\n", " ").strip() or "1"
            self._add_transition(
                f"{gateway.id}_{flow.id}",
                self._enable(gateway, expr),
                self._body(
                    gateway, [_place(flow.id)] + self._flow_places(gateway.out_msgs)
                ),
            )
        return True

    def visit_parallel_gateway(self, gateway: ParallelGatewayNode) -> bool:
        return self._unsupported(gateway.id, "parallel gateway")

    def visit_message_flow(self, flow: MessageFlow) -> bool:
        return True

    def visit_process(self, process: Process) -> bool:
        self._process_id = process.id
        self.process_ids.append(process.id)
        return True

    def visit_bpmn(self, bpmn: Bpmn) -> bool:
        return True

    def end_visit_bpmn(self, bpmn: Bpmn) -> None:
        self._write_defs()
        self._write_step()

    ####################
    # Output
    ####################

    def _write_defs(self) -> None:
        self.defs.write_str(START_STR, NL_SINGLE)
        for place, init in self.places.items():
            self.defs.write_str(f"_Bool {place} = {init};", NL_SINGLE)
        for pid in self.process_ids:
            self.defs.write_str(f"_Bool {DONE_PREFIX}{pid} = 0;", NL_SINGLE)
        self.defs.write_str(f"_Bool {COLLISION_VAR} = 0;", NL_SINGLE)
        self.defs.write_str(NONDET_DECL, NL_SINGLE)
        self.defs.write_str(END_STR, NL_DOUBLE)

    def _write_step(self) -> None:
        sm = self.step_func
        sm.write_str(f"static void {STEP_FUNC}(void) {{", NL_SINGLE, IndentAction.INC)
        sm.write_str(f"unsigned int {CHOICE_VAR} = nondet_uint();", NL_SINGLE)
        sm.write_str(
            f"__CPROVER_assume({CHOICE_VAR} < {len(self.transitions)});", NL_SINGLE
        )
        sm.write_str(f"{COLLISION_VAR} = 0;", NL_SINGLE)
        sm.write_str(f"switch ({CHOICE_VAR}) {{", NL_SINGLE)
        for idx, tr in enumerate(self.transitions):
            sm.write_str(f"case {idx}: {{", NL_SINGLE, IndentAction.INC)
            sm.write_str(f"__CPROVER_assume({tr.enable});", NL_SINGLE)
            sm.write_str(tr.body)
            sm.write_str("break;", NL_SINGLE)
            sm.write_str("}", NL_SINGLE, IndentAction.DEC)
        sm.write_str("default: break;", NL_SINGLE)
        sm.write_str("}", NL_SINGLE)
        sm.write_str(
            f'__CPROVER_assert(!{COLLISION_VAR}, "{COLLISION_MSG}");', NL_SINGLE
        )
        sm.write_str("}", NL_DOUBLE, IndentAction.DEC)

    def __repr__(self) -> str:
        return f"{self.defs}{self.step_func}"
