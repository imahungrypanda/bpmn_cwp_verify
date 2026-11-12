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
    SequenceFlow,
    StartEvent,
    Task,
)
from bpmncwpverify.core.error import BpmnCbmcUnsupportedElementError, Error
from bpmncwpverify.util.stringmanager import IndentAction, StringManager
from bpmncwpverify.visitors.cwp_cbmc_visitor import UPDATE_FUNC
from bpmncwpverify.visitors.feel_to_cbmc_visitor import behavior_to_c, condition_to_c

##############
# Constants
##############
HELPER_DEFS_STR = "#include <stdbool.h>\n\nunsigned int nondet_uint(void);\n"
CHOICE_VAR = "bpmn_choice"
OCCUPIED_VAR = "bpmn_occupied"
NL_NONE = 0
NL_SINGLE = 1
NL_DOUBLE = 2


##############
def _sanitize(identifier: str) -> str:
    return re.sub(r"\W", "_", identifier)


def place_name(element_id: str) -> str:
    """Name of the boolean token place for a start event or a flow."""
    return f"tok_{_sanitize(element_id)}"


def ended_name(process_id: str) -> str:
    """Name of the boolean that says a process has ended."""
    return f"ended_{_sanitize(process_id)}"


class Transition:
    """
    One thing the workflow can do in a single pass: its enable condition and
    the statements that run once it is chosen.
    """

    __slots__ = ["body", "enable", "label"]

    def __init__(self, label: str, enable: str, body: list[str]) -> None:
        self.label = label
        self.enable = enable
        self.body = body


class CbmcBpmnGenVisitor(BpmnVisitor):
    """
    Turns BPMN into the C pieces of the CBMC model: the token places, the
    transitions (enable condition and body) and one pass of the main loop.
    """

    __slots__ = [
        "_process_id",
        "_visited",
        "ended_flags",
        "errors",
        "places",
        "transitions",
    ]

    def __init__(self) -> None:
        self.places: dict[str, bool] = {}  # place name -> initially holds a token
        self.ended_flags: list[str] = []
        self.transitions: list[Transition] = []
        self.errors: list[Error] = []
        self._visited: set[str] = set()
        self._process_id = ""

    ####################
    # Helpers
    ####################

    def _unsupported(self, element: Node, kind: str) -> None:
        self.errors.append(BpmnCbmcUnsupportedElementError(element.id, kind))

    def _first_visit(self, element: Node) -> bool:
        if element.id in self._visited:
            return False
        self._visited.add(element.id)
        return True

    def _declare(self, name: str, initial: bool = False) -> None:
        self.places[name] = self.places.get(name, False) or initial

    def _declare_outgoing(self, element: Node) -> None:
        for flow in element.out_flows + element.out_msgs:
            self._declare(place_name(flow.id))

    def _incoming(self, element: Node) -> tuple[list[str], list[str]]:
        """Returns (sequence places, message places) feeding the element."""
        seq = [place_name(flow.id) for flow in element.in_flows]
        msgs = [place_name(flow.id) for flow in element.in_msgs]
        for name in seq + msgs:
            self._declare(name)
        return seq, msgs

    @staticmethod
    def _enable(seq: list[str], msgs: list[str], join: bool = False) -> str:
        parts: list[str] = []
        if seq:
            parts.append("(" + (" && " if join else " || ").join(seq) + ")")
        if msgs:
            parts.append("(" + " && ".join(msgs) + ")")
        return " && ".join(parts) if parts else "true"

    @staticmethod
    def _put(places: list[str]) -> list[str]:
        """
        Puts tokens on places, remembering whether any was already occupied.
        The check itself happens once, after the pass's transition has run.
        """
        if not places:
            return []
        return [
            f"{OCCUPIED_VAR} = {' || '.join(places)};",
            *[f"{place} = true;" for place in places],
        ]

    def _behavior(self, task: Task) -> list[str]:
        """
        Translates the task's FEEL behavior into C, ending with the CWP update
        when the task has a behavior (the Promela visitor does the same).
        """
        if task.behavior_tree is None:
            return []
        code = behavior_to_c(task.behavior_tree)
        if isinstance(code, Failure):
            self.errors.append(code.failure())
            return []
        return code.unwrap() + [f"{UPDATE_FUNC}();"]

    def _add_node_transition(
        self,
        element: Node,
        behavior: list[str] | None = None,
        ends_process: bool = False,
        join: bool = False,
    ) -> None:
        seq, msgs = self._incoming(element)
        self._declare_outgoing(element)
        body = [f"{place} = false;" for place in seq + msgs]
        body += behavior or []
        body += self._put(
            [place_name(flow.id) for flow in element.out_flows + element.out_msgs]
        )
        if ends_process:
            body.append(f"{ended_name(self._process_id)} = true;")
        self.transitions.append(
            Transition(element.id, self._enable(seq, msgs, join), body)
        )

    ####################
    # Output
    ####################

    def all_ended_expr(self) -> str:
        """C condition that is true once every process has ended."""
        return " && ".join(self.ended_flags) if self.ended_flags else "true"

    def gen_defs(self) -> str:
        sm = StringManager()
        for name, initial in self.places.items():
            sm.write_str(f"bool {name} = {'true' if initial else 'false'};", NL_SINGLE)
        for flag in self.ended_flags:
            sm.write_str(f"bool {flag} = false;", NL_SINGLE)
        return repr(sm)

    def gen_pass(self) -> str:
        """
        One pass of the loop: choose one transition, assume it is enabled and
        run it. Nothing in here loops over the transitions.
        """
        sm = StringManager()
        sm.write_str("{", NL_SINGLE, IndentAction.INC)
        sm.write_str(f"unsigned int {CHOICE_VAR} = nondet_uint();", NL_SINGLE)
        sm.write_str(f"bool {OCCUPIED_VAR} = false;", NL_SINGLE)
        sm.write_str(
            f"__CPROVER_assume({CHOICE_VAR} < {len(self.transitions)}u);", NL_SINGLE
        )
        sm.write_str(f"switch ({CHOICE_VAR}) {{", NL_SINGLE)
        for index, transition in enumerate(self.transitions):
            sm.write_str(
                f"case {index}: /* {transition.label} */", NL_SINGLE, IndentAction.INC
            )
            sm.write_str(f"__CPROVER_assume({transition.enable});", NL_SINGLE)
            for line in transition.body:
                sm.write_str(line, NL_SINGLE)
            sm.write_str("break;", NL_SINGLE, IndentAction.DEC)
        sm.write_str("default:", NL_SINGLE, IndentAction.INC)
        sm.write_str("__CPROVER_assume(false);", NL_SINGLE)
        sm.write_str("break;", NL_SINGLE, IndentAction.DEC)
        sm.write_str("}", NL_SINGLE)
        sm.write_str(
            f'__CPROVER_assert(!{OCCUPIED_VAR}, "token placed on an occupied place");',
            NL_SINGLE,
        )
        sm.write_str("}", NL_SINGLE, IndentAction.DEC)
        return repr(sm)

    def get_result(self) -> Result[str, Error]:
        """The generated C (helpers, places, one pass), or the first error."""
        if self.errors:
            return Failure(self.errors[0])
        return Success(f"{HELPER_DEFS_STR}\n{self.gen_defs()}\n{self.gen_pass()}")

    def __repr__(self) -> str:
        return f"{HELPER_DEFS_STR}\n{self.gen_defs()}\n{self.gen_pass()}"

    ####################
    # Visitor Methods
    ####################

    def visit_start_event(self, event: StartEvent) -> bool:
        if not self._first_visit(event):
            return False
        name = place_name(event.id)
        self._declare(name, initial=True)
        # a start event has no incoming flows, its own place is its input
        self._declare_outgoing(event)
        body = [f"{name} = false;"]
        body += self._put(
            [place_name(flow.id) for flow in event.out_flows + event.out_msgs]
        )
        self.transitions.append(Transition(event.id, name, body))
        return True

    def visit_end_event(self, event: EndEvent) -> bool:
        if not self._first_visit(event):
            return False
        self._add_node_transition(event, ends_process=True)
        return True

    def visit_intermediate_event(self, event: IntermediateEvent) -> bool:
        if not self._first_visit(event):
            return False
        self._add_node_transition(event)
        return True

    def visit_task(self, task: Task) -> bool:
        if not self._first_visit(task):
            return False
        self._add_node_transition(task, self._behavior(task))
        return True

    def visit_boundary_event(self, boundary_event: Task.BoundaryEvent) -> bool:
        self._unsupported(boundary_event, "boundary event")
        return False

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        if not self._first_visit(gateway):
            return False
        if gateway.in_msgs or gateway.out_msgs:
            self._unsupported(gateway, "exclusive gateway with message flows")
            return True
        seq, _ = self._incoming(gateway)
        self._declare_outgoing(gateway)
        enable_in = self._enable(seq, [])
        clear = [f"{place} = false;" for place in seq]
        conditions: list[str] = []
        for flow in gateway.out_flows:
            condition = self._flow_condition(flow)
            conditions.append(condition)
            self.transitions.append(
                Transition(
                    f"{gateway.id} -> {flow.id}",
                    f"{enable_in} && ({condition})",
                    clear + self._put([place_name(flow.id)]),
                )
            )
        # Like SPIN, a gateway where no condition holds is a violation
        none_hold = " && ".join(f"!({c})" for c in conditions) or "true"
        self.transitions.append(
            Transition(
                f"{gateway.id} has no viable path",
                f"{enable_in} && {none_hold}",
                [
                    f'__CPROVER_assert(false, "no viable path from {gateway.id}");',
                ],
            )
        )
        return True

    def _flow_condition(self, flow: SequenceFlow) -> str:
        if flow.expression_tree is None:
            return "true"
        condition = condition_to_c(flow.expression_tree)
        if isinstance(condition, Failure):
            self.errors.append(condition.failure())
            return "true"
        return condition.unwrap()

    def visit_parallel_gateway(self, gateway: ParallelGatewayNode) -> bool:
        if not self._first_visit(gateway):
            return False
        if gateway.in_msgs or gateway.out_msgs:
            self._unsupported(gateway, "parallel gateway with message flows")
            return True
        # A fork is enabled by any incoming flow, since a loop can come back in
        # through it. A join waits for all of them.
        if gateway.is_fork:
            self._add_node_transition(gateway)
        else:
            self._add_node_transition(gateway, join=True)
        return True

    def visit_message_flow(self, flow: MessageFlow) -> bool:
        return True

    def visit_process(self, process: Process) -> bool:
        self._process_id = process.id
        self.ended_flags.append(ended_name(process.id))
        return True

    def visit_bpmn(self, bpmn: Bpmn) -> bool:
        return True
