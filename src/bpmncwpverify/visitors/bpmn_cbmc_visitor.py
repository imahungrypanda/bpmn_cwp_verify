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

##############
# Constants
##############
HELPER_DEFS_STR = "#include <stdbool.h>\n\nunsigned int nondet_uint(void);\n"
CHOICE_VAR = "bpmn_choice"
OCCUPIED_VAR = "bpmn_occupied"
ALT_VAR = "bpmn_alt"
_ASSIGN_RE = re.compile(r"^[A-Za-z_]\w*\s*=(?!=)")
_INCDEC_RE = re.compile(r"^[A-Za-z_]\w*\s*(\+\+|--)$")
_ASSERT_RE = re.compile(r"^assert\s*\((.*)\)$")
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

    __slots__ = ["label", "enable", "body"]

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
        "places",
        "ended_flags",
        "transitions",
        "errors",
        "_visited",
        "_process_id",
        "_alt_count",
    ]

    def __init__(self) -> None:
        self.places: dict[str, bool] = {}  # place name -> initially holds a token
        self.ended_flags: list[str] = []
        self.transitions: list[Transition] = []
        self.errors: list[Error] = []
        self._visited: set[str] = set()
        self._process_id = ""
        self._alt_count = 0

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

    def _statement(self, task: Task, text: str) -> list[str]:
        """Translates one behavior statement (no `;`) into C."""
        text = " ".join(text.split())
        if not text or text == "skip":
            return []
        if _ASSIGN_RE.match(text) or _INCDEC_RE.match(text):
            return [f"{text};"]
        assertion = _ASSERT_RE.match(text)
        if assertion:
            expr = assertion.group(1)
            return [f'__CPROVER_assert({expr}, "behavior of {task.id}");']
        self._unsupported(task, f"behavior statement '{text}'")
        return []

    def _choice(self, task: Task, lines: list[str], pos: int) -> tuple[int, list[str]]:
        """
        Translates an `if :: guard -> body ... fi` starting after the `if` at
        lines[pos - 1]. Like Promela, it picks any option whose guard holds,
        and blocks when none does.
        """
        options: list[tuple[str, list[str]]] = []
        while pos < len(lines) and lines[pos].startswith("::"):
            guard, arrow, rest = lines[pos][2:].partition("->")
            if not arrow:
                self._unsupported(task, f"behavior option '{lines[pos]}'")
                return len(lines), []
            lines[pos] = rest.strip()
            if not lines[pos]:
                pos += 1
            pos, body = self._block(task, lines, pos)
            options.append((" ".join(guard.split()), body))
        if pos >= len(lines) or lines[pos] != "fi" or not options:
            self._unsupported(task, "behavior with a malformed if")
            return len(lines), []
        explicit = [g for g, _ in options if g != "else"]
        sm = StringManager()
        sm.write_str("{", NL_SINGLE, IndentAction.INC)
        alt = f"{ALT_VAR}_{self._alt_count}"
        self._alt_count += 1
        sm.write_str(f"unsigned int {alt} = nondet_uint();", NL_SINGLE)
        sm.write_str(f"__CPROVER_assume({alt} < {len(options)}u);", NL_SINGLE)
        sm.write_str(f"switch ({alt}) {{", NL_SINGLE)
        for index, (guard, body) in enumerate(options):
            if guard == "else":
                guard = " && ".join(f"!({g})" for g in explicit) or "true"
            sm.write_str(f"case {index}:", NL_SINGLE, IndentAction.INC)
            sm.write_str(f"__CPROVER_assume({guard});", NL_SINGLE)
            for line in body:
                sm.write_str(line, NL_SINGLE)
            sm.write_str("break;", NL_SINGLE, IndentAction.DEC)
        sm.write_str("}", NL_SINGLE)
        sm.write_str("}", NL_SINGLE, IndentAction.DEC)
        return pos + 1, repr(sm).splitlines()

    def _block(self, task: Task, lines: list[str], pos: int) -> tuple[int, list[str]]:
        """Translates statements until a `::` or `fi` line, or the end."""
        out: list[str] = []
        while pos < len(lines):
            line = lines[pos]
            if line == "fi" or line.startswith("::"):
                break
            pos += 1
            if line == "if":
                pos, code = self._choice(task, lines, pos)
                out += code
            else:
                for text in line.split(";"):
                    out += self._statement(task, text)
        return pos, out

    def _behavior(self, task: Task) -> list[str]:
        """
        Translates the task's behavior into C, ending with the CWP update when
        the behavior is not empty (the Promela visitor does the same).
        """
        lines = [line.strip() for line in task.behavior.split("\n") if line.strip()]
        if not lines:
            return []
        pos, code = self._block(task, lines, 0)
        if pos < len(lines):
            self._unsupported(task, f"behavior line '{lines[pos]}'")
        return code + [f"{UPDATE_FUNC}();"]

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

    @staticmethod
    def _flow_condition(flow: SequenceFlow) -> str:
        expression = " ".join(flow.expression.split())
        return expression if expression else "true"

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
