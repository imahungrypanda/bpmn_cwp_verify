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
from bpmncwpverify.core.error import (
    BpmnCbmcUnsupportedElementError,
    BpmnSeqFlowNoExprError,
    Error,
)
from bpmncwpverify.core.feel_tree import Behavior, Triple
from bpmncwpverify.util.stringmanager import IndentAction, StringManager
from bpmncwpverify.visitors.feel_to_cbmc_visitor import (
    behavior_to_c,
    condition_to_c,
)

##############
# Constants
##############
HELPER_FUNCS_STR = """#include <assert.h>
#include <stdbool.h>

unsigned int nondet_uint(void);

#define hasToken(place) ((place) != 0)
#define putToken(place) do { assert((place) == 0 && "Attempting to place token in already-occupied place"); (place) = 1; } while (0)
#define consumeToken(place) ((place) = 0)
"""
NL_NONE = 0
NL_SINGLE = 1
NL_DOUBLE = 2
UNSUPPORTED_BEHAVIOR_KEYWORDS = {
    "atomic",
    "break",
    "d_step",
    "do",
    "goto",
    "od",
    "printf",
    "run",
}
UPDATE_STATE_DECL = "void updateState(void);"


class _BehaviorError(Exception):
    pass


class _BehaviorTranslator:
    """
    Translates a task behavior (Promela-style statements: assignments,
    `assert(...)`, `updateState()`, `skip` and `if :: guard -> ... fi`) into
    lines of C. Like Promela, an `if` with no true guard blocks, which is
    modeled with `__CPROVER_assume`; among several true guards one is picked
    nondeterministically.
    """

    def __init__(self) -> None:
        self._items: list[tuple[str, str, list[str]]] = []
        self._pos = 0
        self._counter = 0
        self.uses_update_state = False

    @staticmethod
    def _statements(text: str) -> list[str]:
        return [part.strip() for part in text.split(";") if part.strip()]

    def _tokenize(self, behavior: str) -> None:
        for raw in behavior.split("\n"):
            line = raw.split("//")[0].strip()
            if not line:
                continue
            if line.startswith("::"):
                guard, arrow, rest = line[2:].partition("->")
                if not arrow:
                    guard, rest = guard, ""
                self._items.append(
                    ("opt", " ".join(guard.split()), self._statements(rest))
                )
            elif line in ("if", "fi"):
                self._items.append((line, "", []))
            else:
                for stmt in self._statements(line):
                    self._items.append(("stmt", stmt, []))

    def translate(self, behavior: str) -> list[str]:
        self._tokenize(behavior)
        lines = self._block()
        if self._pos != len(self._items):
            raise _BehaviorError("unbalanced 'if'/'fi' in behavior")
        return lines

    def _statement(self, stmt: str) -> list[str]:
        word = stmt.split("(")[0].split()[0] if stmt.split() else ""
        if word in UNSUPPORTED_BEHAVIOR_KEYWORDS or stmt.endswith(":"):
            raise _BehaviorError(f"behavior statement '{stmt}' is not supported")
        if stmt == "skip":
            return []
        if stmt.replace(" ", "") == "updateState()":
            self.uses_update_state = True
            return ["updateState();"]
        return [f"{' '.join(stmt.split())};"]

    def _block(self) -> list[str]:
        lines: list[str] = []
        while self._pos < len(self._items):
            kind, text, _ = self._items[self._pos]
            if kind in ("fi", "opt"):
                break
            self._pos += 1
            if kind == "if":
                lines += self._if()
            else:
                lines += self._statement(text)
        return lines

    def _if(self) -> list[str]:
        options: list[tuple[str, list[str]]] = []
        while self._pos < len(self._items) and self._items[self._pos][0] == "opt":
            _, guard, stmts = self._items[self._pos]
            self._pos += 1
            body = [line for stmt in stmts for line in self._statement(stmt)]
            body += self._block()
            options.append((guard, body))
        if self._pos >= len(self._items) or self._items[self._pos][0] != "fi":
            raise _BehaviorError("'if' in behavior is not closed by 'fi'")
        self._pos += 1
        if not options:
            raise _BehaviorError("'if' in behavior has no options")

        n = self._counter
        self._counter += 1
        regular = [g for g, _ in options if g != "else"]
        guards: list[str] = []
        for guard, _ in options:
            if guard == "else":
                others = " || ".join(f"({g})" for g in regular) or "false"
                guards.append(f"!({others})")
            else:
                guards.append(guard)

        lines = ["{"]
        for i, guard in enumerate(guards):
            lines.append(f"bool if{n}_guard{i} = ({guard});")
        lines.append(f"unsigned int if{n}_pick = nondet_uint();")
        picked = " || ".join(
            f"(if{n}_pick == {i} && if{n}_guard{i})" for i in range(len(options))
        )
        lines.append(f"__CPROVER_assume({picked});")
        for i, (_, body) in enumerate(options):
            lines.append(f"if (if{n}_pick == {i}) {{")
            lines += body
            lines.append("}")
        lines.append("}")
        return lines


##############


class CbmcBpmnGenVisitor(BpmnVisitor):
    """
    Generates C that models the execution of a BPMN.

    Every sequence flow and message flow gets a token place, a global named
    `<target>_FROM_<source>` (a start event with no incoming flows uses its own
    id). Every element gets a `static bool <id>_step(void)` that, if the element
    is enabled, fires it and returns true. Every process gets
    `bool <process>_step(void)`, which fires one enabled element, chosen
    nondeterministically, and returns whether anything fired, and
    `void <process>_init(void)`, which places the initial tokens.
    `<process>_done` is set once the process's end event fires.

    Elements that cannot be expressed are recorded in `errors`. Use `result()`
    to get either the C or the first error.
    """

    __slots__ = [
        "_process_elements",
        "_process_id",
        "_process_init_places",
        "_update_state_declared",
        "_visited",
        "behaviors",
        "defs",
        "elements",
        "errors",
        "inits",
        "process_ids",
        "processes",
        "var_defs",
    ]

    def __init__(self) -> None:
        self.defs = StringManager()
        self.var_defs = StringManager()
        self.behaviors = StringManager()
        self.elements = StringManager()
        self.processes = StringManager()
        self.inits = StringManager()
        self.errors: list[Error] = []
        self.process_ids: list[str] = []
        self._visited: set[str] = set()
        self._process_id = ""
        self._process_elements: list[str] = []
        self._process_init_places: list[str] = []
        self._update_state_declared = False

    def result(self) -> Result[str, Error]:
        if self.errors:
            return Failure(self.errors[0])
        return Success(repr(self))

    def __repr__(self) -> str:
        return f"{self.defs}{self.var_defs}{self.behaviors}{self.elements}{self.processes}{self.inits}"

    ####################
    # Helpers
    ####################

    @staticmethod
    def _place(element: Node, flow: Flow | None = None) -> str:
        if flow:
            return f"{element.id}_FROM_{flow.source_node.id}"
        return element.id

    def _in_places(self, element: Node) -> tuple[list[str], list[str]]:
        """
        Returns (in-process places, message places) for the element.
        """
        if not (element.in_flows or element.in_msgs):
            return [self._place(element)], []
        return (
            [self._place(element, flow) for flow in element.in_flows],
            [self._place(element, msg) for msg in element.in_msgs],
        )

    def _out_places(self, element: Node) -> list[str]:
        return [
            self._place(flow.target_node, flow)
            for flow in element.out_flows + element.out_msgs
        ]

    def _guard(self, element: Node) -> str:
        seq, msgs = self._in_places(element)
        parts: list[str] = []
        if element.in_flows or not element.in_msgs:
            parts.append(" || ".join(f"hasToken({p})" for p in seq))
            parts[0] = f"({parts[0]})"
        if msgs:
            parts.append("(" + " && ".join(f"hasToken({p})" for p in msgs) + ")")
        return " && ".join(parts)

    def _unsupported(self, element: Node, reason: str) -> None:
        self.errors.append(BpmnCbmcUnsupportedElementError(element.id, reason))

    def _first_visit(self, element: Node) -> bool:
        if element.id in self._visited:
            return False
        self._visited.add(element.id)
        return True

    def _declare_places(self, element: Node) -> None:
        seq, msgs = self._in_places(element)
        for place in seq + msgs:
            self.var_defs.write_str(f"static unsigned char {place} = 0;", NL_SINGLE)

    def _write_step(
        self,
        element: Node,
        body: list[str],
        guard: str | None = None,
    ) -> None:
        """
        Writes `static bool <id>_step(void)`. `body` holds the statements that
        run once the element fires, after its tokens are consumed.
        """
        sm = self.elements
        sm.write_str(
            f"static bool {element.id}_step(void) {{", NL_SINGLE, IndentAction.INC
        )
        sm.write_str(
            f"if (!({guard if guard is not None else self._guard(element)})) return false;",
            NL_SINGLE,
        )
        for line in body:
            sm.write_str(line, NL_SINGLE)
        sm.write_str("return true;", NL_SINGLE)
        sm.write_str("}", NL_DOUBLE, IndentAction.DEC)
        self._process_elements.append(element.id)

    def _consume_and_put(self, element: Node) -> list[str]:
        lines: list[str] = []
        seq, msgs = self._in_places(element)
        for place in seq + msgs:
            lines.append(f"consumeToken({place});")
        for place in self._out_places(element):
            lines.append(f"putToken({place});")
        return lines

    def _simple_element(self, element: Node, extra: str = "") -> None:
        self._declare_places(element)
        body = [extra] if extra else []
        body += self._consume_and_put(element)
        self._write_step(element, body)

    ####################
    # Visitor Methods
    ####################

    def visit_start_event(self, event: StartEvent) -> bool:
        if not self._first_visit(event):
            return True
        self._simple_element(event)
        if not (event.in_flows or event.in_msgs):
            self._process_init_places.append(self._place(event))
        return True

    def visit_end_event(self, event: EndEvent) -> bool:
        if not self._first_visit(event):
            return True
        self._simple_element(event, extra=f"{self._process_id}_done = true;")
        return True

    def visit_intermediate_event(self, event: IntermediateEvent) -> bool:
        if not self._first_visit(event):
            return True
        self._simple_element(event)
        return True

    def visit_task(self, task: Task) -> bool:
        if not self._first_visit(task):
            return True
        if task.msg_boundary_events:
            self._unsupported(task, "tasks with boundary events are not supported")
            return True
        translator = _BehaviorTranslator()
        if isinstance(task.behavior, str):
            try:
                lines = translator.translate(task.behavior)
            except _BehaviorError as e:
                self._unsupported(task, str(e))
                return True
        elif not isinstance(task.behavior, Behavior | Triple):
            self._unsupported(task, "a FEEL behavior must be made of triples")
            return True
        else:
            feel_lines = behavior_to_c(task.behavior, f"{task.id}_feel")
            if isinstance(feel_lines, Failure):
                self.errors.append(feel_lines.failure())
                return True
            # A triple cannot call updateState(), so a FEEL behavior always
            # ends with it, as in the Promela back end.
            lines = [*feel_lines.unwrap(), "updateState();"]
            translator.uses_update_state = True
        if translator.uses_update_state and not self._update_state_declared:
            self._update_state_declared = True
            self.behaviors.write_str(UPDATE_STATE_DECL, NL_DOUBLE)
        self.behaviors.write_str(
            f"static void {task.id}_BehaviorModel(void) {{", NL_SINGLE, IndentAction.INC
        )
        for line in lines:
            if line.startswith("}"):
                self.behaviors.write_str(line, NL_SINGLE, IndentAction.DEC)
            elif line.endswith("{"):
                self.behaviors.write_str(line, NL_SINGLE, IndentAction.INC)
            else:
                self.behaviors.write_str(line, NL_SINGLE)
        self.behaviors.write_str("}", NL_DOUBLE, IndentAction.DEC)
        self._simple_element(task, extra=f"{task.id}_BehaviorModel();")
        return True

    def visit_boundary_event(self, boundary_event: Task.BoundaryEvent) -> bool:
        self._unsupported(boundary_event, "boundary events are not supported")
        return False

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        if not self._first_visit(gateway):
            return True
        if gateway.in_msgs or gateway.out_msgs:
            self._unsupported(gateway, "gateways cannot have message flows")
            return True
        if not gateway.out_flows:
            self._unsupported(gateway, "exclusive gateways need an outgoing flow")
            return True
        missing = [
            f
            for f in gateway.out_flows
            if isinstance(f.expression, str) and not f.expression
        ]
        if missing:
            for flow in missing:
                self.errors.append(BpmnSeqFlowNoExprError(gateway.id, flow.id))
            return True

        self._declare_places(gateway)
        body: list[str] = []
        flows = gateway.out_flows
        for i, flow in enumerate(flows):
            if isinstance(flow.expression, str):
                expr = " ".join(flow.expression.split())
            else:
                condition = condition_to_c(flow.expression, f"guard{i}")
                if isinstance(condition, Failure):
                    self.errors.append(condition.failure())
                    return True
                body += condition.unwrap().statements
                expr = condition.unwrap().expr
            body.append(f"bool guard{i} = ({expr});")
        any_guard = " || ".join(f"guard{i}" for i in range(len(flows)))
        body.append(f'assert(({any_guard}) && "No viable path to take");')
        body.append("unsigned int pick = nondet_uint();")
        picked = " || ".join(f"(pick == {i} && guard{i})" for i in range(len(flows)))
        body.append(f"__CPROVER_assume({picked});")
        seq, _ = self._in_places(gateway)
        for place in seq:
            body.append(f"consumeToken({place});")
        for i, place in enumerate(self._out_places(gateway)):
            body.append(f"if (pick == {i}) putToken({place});")
        self._write_step(gateway, body)
        return True

    def visit_parallel_gateway(self, gateway: ParallelGatewayNode) -> bool:
        if not self._first_visit(gateway):
            return True
        if gateway.in_msgs or gateway.out_msgs:
            self._unsupported(gateway, "gateways cannot have message flows")
            return True
        if not gateway.out_flows:
            self._unsupported(gateway, "parallel gateways need an outgoing flow")
            return True

        # A fork has one incoming flow and starts every outgoing branch; a join
        # waits for a token on every incoming flow. Both are the same rule:
        # consume from all incoming flows, put on all outgoing flows.
        self._declare_places(gateway)
        seq, _ = self._in_places(gateway)
        guard = " && ".join(f"hasToken({p})" for p in seq)
        self._write_step(gateway, self._consume_and_put(gateway), guard=f"({guard})")
        return True

    def visit_message_flow(self, flow: MessageFlow) -> bool:
        # Message flows are modeled by the token places of the sending and
        # receiving elements.
        return True

    def visit_process(self, process: Process) -> bool:
        self._process_id = process.id
        self._process_elements = []
        self._process_init_places = []
        self.process_ids.append(process.id)
        self.var_defs.write_str(f"static bool {process.id}_done = false;", NL_SINGLE)
        return True

    def end_visit_process(self, process: Process) -> None:
        pid = process.id
        sm = self.processes
        elements = self._process_elements

        sm.write_str(f"bool {pid}_step(void) {{", NL_SINGLE, IndentAction.INC)
        sm.write_str(f"if ({pid}_done) return false;", NL_SINGLE)
        if elements:
            n = len(elements)
            sm.write_str(f"unsigned int start = nondet_uint() % {n}u;", NL_SINGLE)
            sm.write_str(
                f"for (unsigned int i = 0; i < {n}u; i++) {{",
                NL_SINGLE,
                IndentAction.INC,
            )
            sm.write_str(f"switch ((start + i) % {n}u) {{", NL_SINGLE)
            for idx, element_id in enumerate(elements):
                sm.write_str(
                    f"case {idx}u: if ({element_id}_step()) return true; break;",
                    NL_SINGLE,
                )
            sm.write_str("default: break;", NL_SINGLE)
            sm.write_str("}", NL_SINGLE)
            sm.write_str("}", NL_SINGLE, IndentAction.DEC)
        sm.write_str("return false;", NL_SINGLE)
        sm.write_str("}", NL_DOUBLE, IndentAction.DEC)

        self.inits.write_str(f"void {pid}_init(void) {{", NL_SINGLE, IndentAction.INC)
        for place in self._process_init_places:
            self.inits.write_str(f"putToken({place});", NL_SINGLE)
        self.inits.write_str("}", NL_DOUBLE, IndentAction.DEC)

    def visit_bpmn(self, bpmn: Bpmn) -> bool:
        self.defs.write_str(HELPER_FUNCS_STR, NL_DOUBLE)
        return True
