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
from bpmncwpverify.visitors.cwp_cbmc_visitor import UPDATE_FUNC

##############
# Constants
##############
HELPER_FUNCS_STR = "unsigned int nondet_uint(void);\n"
NL_NONE = 0
NL_SINGLE = 1
NL_DOUBLE = 2
OCCUPIED_VAR = "occupied"
CHOICE_VAR = "choice"
CWP_CHANGED_VAR = "cwp_changed"
##############


def _c_expr(expr: str) -> str:
    """Turns a Promela expression into a C expression."""
    expr = re.sub(r"\btrue\b", "1", expr)
    return re.sub(r"\bfalse\b", "0", expr).strip()


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
        "_declared",
        "_end_flags",
        "_num_transitions",
        "_process_ended",
        "_visited",
        "defs",
        "enables",
        "ends",
        "errors",
        "places",
        "transitions",
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
        sm.write_str(f"int {CWP_CHANGED_VAR} = 0;", NL_SINGLE)
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
        # The CWP moves once per pass, after the transition has run
        sm.write_str(f"if ({CWP_CHANGED_VAR}) {UPDATE_FUNC}();", NL_SINGLE)
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

    def _enable_condition(
        self, node: Node, flow_expr: str = "", all_in: bool = False
    ) -> str:
        seq, msg = self._in_places(node)
        parts = ["(" + (" && " if all_in else " || ").join(seq) + ")"]
        if msg:
            parts.append("(" + " && ".join(msg) + ")")
        if flow_expr:
            parts.append(f"({_c_expr(flow_expr.replace(chr(10), ' '))})")
        return " && ".join(parts)

    def _gen_task_behavior(self, task: Task) -> StringManager:
        """
        Translates the task's behavior into C. A behavior that does anything
        also flags the CWP for an update, which the pass makes after the
        transition runs.
        """
        sm = StringManager()
        lines = [line.strip() for line in task.behavior.split("\n") if line.strip()]
        body, _ = self._parse_block(lines, 0, task.id, [0])
        if not body:
            return sm
        for line in body:
            sm.write_str(line, NL_SINGLE)
        sm.write_str(f"{CWP_CHANGED_VAR} = 1;", NL_SINGLE)
        return sm

    def _parse_block(
        self, lines: list[str], pos: int, task_id: str, counter: list[int]
    ) -> tuple[list[str], int]:
        """
        Translates statements until a `::` option, a `fi`, or the end. Returns
        the C lines and the position where it stopped.
        """
        out: list[str] = []
        while pos < len(lines):
            line = lines[pos]
            if line.startswith("::") or line == "fi":
                break
            pos += 1
            if line == "if":
                code, pos = self._parse_if(lines, pos, task_id, counter)
                out.extend(code)
                continue
            for stmt in line.split(";"):
                stmt = stmt.strip()
                if not stmt or stmt == "skip":
                    continue
                if stmt.startswith("assert"):
                    cond = _c_expr(stmt[len("assert") :])
                    out.append(f'__CPROVER_assert({cond}, "assertion in {task_id}");')
                else:
                    out.append(f"{_c_expr(stmt)};")
        return out, pos

    def _parse_if(
        self, lines: list[str], pos: int, task_id: str, counter: list[int]
    ) -> tuple[list[str], int]:
        """
        Translates the options of an if, from after `if` through `fi`, into a
        nondeterministic choice among the options whose guards hold. No option
        enabled blocks the path, as it does in Promela.
        """
        options: list[tuple[str, list[str]]] = []
        while pos < len(lines) and lines[pos] != "fi":
            head = lines[pos][2:]
            guard, _, rest = head.partition("->")
            lines[pos] = rest.strip()
            if not lines[pos]:
                pos += 1
            body, pos = self._parse_block(lines, pos, task_id, counter)
            options.append((_c_expr(guard), body))
        pos += 1  # past fi

        name = f"{CHOICE_VAR}_{counter[0]}"
        counter[0] += 1
        out = ["{", f"\tunsigned int {name} = nondet_uint();"]
        taken = " || ".join(f"({g})" for g, _ in options if g != "else")
        for i, (guard, body) in enumerate(options):
            cond = f"!({taken or 0})" if guard == "else" else guard
            out.append(f"\t{'} else ' if i else ''}if ({name} == {i}) {{")
            out.append(f"\t\t__CPROVER_assume({cond});")
            out.extend(f"\t\t{b}" for b in body)
        out.append("\t} else {")
        out.append("\t\t__CPROVER_assume(0);")
        out.extend(["\t}", "}"])
        return out, pos

    def _gen_transition(
        self,
        node: Node,
        out_places: list[str],
        flow_expr: str = "",
        behavior: StringManager | None = None,
        end: bool = False,
        label: str = "",
        all_in: bool = False,
    ) -> None:
        index = self._num_transitions
        self._num_transitions += 1

        self.enables.write_str(f"/* {label or node.id} */", NL_SINGLE)
        self.enables.write_str(
            f"#define ENABLED_{index} ({self._enable_condition(node, flow_expr, all_in)})",
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
            return False
        if not (event.in_flows or event.in_msgs):
            # The start event's own place holds the initial token
            self._declare(self._place(event.id), 1)
        self._first_visit(event)
        self._gen_transition(event, self._out_places(event))
        return True

    def visit_end_event(self, event: EndEvent) -> bool:
        if not self._first_visit(event):
            return False
        self._gen_transition(event, [], end=True)
        return True

    def visit_intermediate_event(self, event: IntermediateEvent) -> bool:
        if not self._first_visit(event):
            return False
        self._gen_transition(event, self._out_places(event))
        return True

    def visit_task(self, task: Task) -> bool:
        if not self._first_visit(task):
            return False
        self._gen_transition(
            task, self._out_places(task), behavior=self._gen_task_behavior(task)
        )
        return True

    def visit_boundary_event(self, boundary_event: Task.BoundaryEvent) -> bool:
        self._unsupported(boundary_event.id, "boundary event")
        return False

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        if not self._first_visit(gateway):
            return False
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
        if not self._first_visit(gateway):
            return False
        out = self._out_places(gateway)
        if not out:
            self._unsupported(gateway.id, "parallel gateway with no outgoing flow")
            return True
        # A fork starts on any incoming token (it may be where a loop comes
        # back in); a join waits for all of them
        self._gen_transition(gateway, out, all_in=not gateway.is_fork)
        return True

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
