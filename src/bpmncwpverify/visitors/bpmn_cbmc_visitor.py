import re
from collections.abc import Sequence

from returns.result import Failure, Result, Success

from bpmncwpverify.core.bpmn import (
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
PRELUDE_STR = "#include <stdbool.h>\n\nunsigned int nondet_uint(void);\n"
CHOICE_VAR = "transition"
CLASH_VAR = "token_clash"
NL_NONE = 0
NL_SINGLE = 1
NL_DOUBLE = 2


def _ident(name: str) -> str:
    return re.sub(r"\W", "_", name)


def token_place(element_id: str) -> str:
    """Name of the boolean token place for a start event or a flow."""
    return f"tok_{_ident(element_id)}"


def ended_flag(process_id: str) -> str:
    """Name of the boolean that is set once a process has reached an end event."""
    return f"ended_{_ident(process_id)}"


class Transition:
    """
    One step the workflow can take: an element firing, or one outgoing flow of an
    exclusive gateway.
    """

    __slots__ = ["element_id", "enable", "body"]

    def __init__(self, element_id: str, enable: str, body: list[str]) -> None:
        self.element_id = element_id
        self.enable = enable
        self.body = body


class CbmcGenVisitor(BpmnVisitor):
    """
    Generates the BPMN half of the CBMC program.

    After visiting, `declarations()` gives the token places and process-ended flags,
    and `pass_code()` gives one pass of the main loop: pick a transition, assume it
    is enabled, run it, and check for a token landing on an occupied place. The
    caller wraps `pass_code()` in a loop that stops when `all_ended_expr()` holds.
    """

    __slots__ = [
        "places",
        "initial_places",
        "process_ids",
        "transitions",
        "errors",
        "_process_id",
        "_seen",
    ]

    def __init__(self) -> None:
        self.places: dict[str, None] = {}  # insertion-ordered set
        self.initial_places: set[str] = set()
        self.process_ids: list[str] = []
        self.transitions: list[Transition] = []
        self.errors: list[Error] = []
        self._process_id = ""
        self._seen: set[str] = set()

    ####################
    # Helpers
    ####################

    def _unsupported(self, element_id: str, element_type: str) -> None:
        self.errors.append(BpmnCbmcUnsupportedElementError(element_id, element_type))

    def _first_visit(self, element_id: str) -> bool:
        if element_id in self._seen:
            return False
        self._seen.add(element_id)
        return True

    def _declare(self, flows: Sequence[Flow]) -> None:
        for flow in flows:
            self.places[token_place(flow.id)] = None

    def _in_places(self, element: Node) -> tuple[list[str], list[str]]:
        """(sequence-flow places, message-flow places) feeding the element."""
        return (
            [token_place(f.id) for f in element.in_flows],
            [token_place(m.id) for m in element.in_msgs],
        )

    def _enable(self, element: Node, extra: str = "") -> str:
        """
        The enable condition: any incoming sequence flow has a token, and every
        incoming message has arrived. A start event with no incoming flows has its
        own place.
        """
        seq, msgs = self._in_places(element)
        if not (seq or msgs):
            seq = [token_place(element.id)]
        parts = [f"!{ended_flag(self._process_id)}"]
        if seq:
            parts.append("(" + " || ".join(seq) + ")")
        if msgs:
            parts.append("(" + " && ".join(msgs) + ")")
        if extra:
            parts.append(f"({extra})")
        return " && ".join(parts)

    def _clear(self, element: Node) -> list[str]:
        seq, msgs = self._in_places(element)
        if not (seq or msgs):
            seq = [token_place(element.id)]
        return [f"{place} = 0;" for place in seq + msgs]

    def _put(self, flows: Sequence[Flow]) -> list[str]:
        """
        Set the places for the flows. The clash flag records, before any is set,
        whether one of them was already occupied.
        """
        if not flows:
            return []
        places = [token_place(f.id) for f in flows]
        return [f"{CLASH_VAR} = {' || '.join(places)};"] + [
            f"{place} = 1;" for place in places
        ]

    def _behavior(self, task: Task) -> list[str]:
        """Placeholder for the task's behavior."""
        return [f"/* behavior of {task.id} */"]

    def _add_transition(
        self,
        element: Node,
        enable: str,
        behavior: list[str],
        out_flows: Sequence[Flow],
        end_process: bool = False,
    ) -> None:
        body = self._clear(element) + behavior + self._put(out_flows)
        if end_process:
            body.append(f"{ended_flag(self._process_id)} = 1;")
        self.transitions.append(Transition(element.id, enable, body))

    def _register(self, element: Node) -> None:
        self._declare(element.in_flows)
        self._declare(element.out_flows)
        self._declare(element.in_msgs)
        self._declare(element.out_msgs)

    def _visit_node(
        self,
        element: Node,
        behavior: list[str] | None = None,
        end_process: bool = False,
    ) -> bool:
        if not self._first_visit(element.id):
            return False
        self._register(element)
        if isinstance(element, StartEvent) and not (
            element.in_flows or element.in_msgs
        ):
            place = token_place(element.id)
            self.places[place] = None
            self.initial_places.add(place)
        self._add_transition(
            element,
            self._enable(element),
            behavior or [],
            list(element.out_flows) + list(element.out_msgs),
            end_process,
        )
        return True

    ####################
    # Output
    ####################

    def all_ended_expr(self) -> str:
        """True when every process has reached an end event."""
        if not self.process_ids:
            return "true"
        return " && ".join(ended_flag(p) for p in self.process_ids)

    def any_enabled_expr(self) -> str:
        """True when at least one transition is enabled."""
        if not self.transitions:
            return "false"
        return " || ".join(f"({t.enable})" for t in self.transitions)

    def declarations(self) -> str:
        sm = StringManager()
        for place in self.places:
            init = 1 if place in self.initial_places else 0
            sm.write_str(f"static bool {place} = {init};", NL_SINGLE)
        for process_id in self.process_ids:
            sm.write_str(f"static bool {ended_flag(process_id)} = 0;", NL_SINGLE)
        return repr(sm)

    def pass_code(self) -> str:
        """
        One pass of the main loop. A single nondeterministic choice picks one
        transition; the switch only branches to it, nothing loops over the
        transitions.
        """
        count = len(self.transitions)
        sm = StringManager()
        sm.write_str(f"unsigned int {CHOICE_VAR} = nondet_uint();", NL_SINGLE)
        sm.write_str(f"__CPROVER_assume({CHOICE_VAR} < {count}u);", NL_SINGLE)
        sm.write_str(f"bool {CLASH_VAR} = 0;", NL_SINGLE)
        sm.write_str(f"switch ({CHOICE_VAR}) {{", NL_SINGLE, IndentAction.INC)
        for index, transition in enumerate(self.transitions):
            sm.write_str(f"case {index}u: /* {transition.element_id} */", NL_SINGLE)
            sm.write_str("", NL_NONE, IndentAction.INC)
            sm.write_str(f"__CPROVER_assume({transition.enable});", NL_SINGLE)
            for line in transition.body:
                sm.write_str(line, NL_SINGLE)
            sm.write_str("break;", NL_SINGLE, IndentAction.DEC)
        sm.write_str("default:", NL_SINGLE)
        sm.write_str("", NL_NONE, IndentAction.INC)
        sm.write_str("__CPROVER_assume(0);", NL_SINGLE)
        sm.write_str("break;", NL_SINGLE, IndentAction.DEC)
        sm.write_str("}", NL_SINGLE, IndentAction.DEC)
        sm.write_str(
            f'__CPROVER_assert(!{CLASH_VAR}, "token placed on an occupied place");',
            NL_SINGLE,
        )
        return repr(sm)

    def result(self) -> Result["CbmcGenVisitor", Error]:
        """Failure with the first unsupported element, else the visitor."""
        if self.errors:
            return Failure(self.errors[0])
        return Success(self)

    def __repr__(self) -> str:
        return f"{PRELUDE_STR}\n{self.declarations()}\n{self.pass_code()}"

    ####################
    # Visitor Methods
    ####################

    def visit_start_event(self, event: StartEvent) -> bool:
        return self._visit_node(event)

    def visit_end_event(self, event: EndEvent) -> bool:
        return self._visit_node(event, end_process=True)

    def visit_intermediate_event(self, event: IntermediateEvent) -> bool:
        return self._visit_node(event)

    def visit_task(self, task: Task) -> bool:
        if task.msg_boundary_events:
            for boundary in task.msg_boundary_events:
                self._unsupported(boundary.id, "boundary event")
            return False
        return self._visit_node(task, self._behavior(task))

    def visit_boundary_event(self, boundary_event: Task.BoundaryEvent) -> bool:
        self._unsupported(boundary_event.id, "boundary event")
        return False

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        if not self._first_visit(gateway.id):
            return False
        self._register(gateway)
        for flow in gateway.out_flows:
            expression = " ".join(flow.expression.split())
            self._add_transition(
                gateway,
                self._enable(gateway, expression),
                [],
                [flow],
            )
        return True

    def visit_parallel_gateway(self, gateway: ParallelGatewayNode) -> bool:
        self._unsupported(gateway.id, "parallel gateway")
        return False

    def visit_message_flow(self, flow: MessageFlow) -> bool:
        self._declare([flow])
        return True

    def visit_process(self, process: Process) -> bool:
        self._process_id = process.id
        self.process_ids.append(process.id)
        return True
