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
from bpmncwpverify.visitors.cwp_cbmc_visitor import UPDATE_FUNC as CWP_UPDATE_FUNC

##############
# Constants
##############
NL_NONE = 0
NL_SINGLE = 1
NL_DOUBLE = 2

COLLISION_VAR = "token_collision"
STEP_FUNC = "bpmn_step"
ALL_DONE_FUNC = "bpmn_all_processes_done"

HELPER_STR = (
    "#include <stdbool.h>\n"
    "unsigned int nondet_uint(void);\n"
    f"static bool {COLLISION_VAR} = false;\n"
    f"#define PUT_TOKEN(place) do {{ {COLLISION_VAR} |= (place); (place) = true; }} while (0)\n"
    "#define CONSUME_TOKEN(place) ((place) = false)\n"
)


_TOKEN_RE = re.compile(r"::|->|;|\n|[^\s;:\-]+|-|:|\s+")
_ASSIGN_RE = re.compile(r"(?<![=!<>])=(?!=)")


def _tokenize_behavior(text: str) -> list[str]:
    """Split Promela behavior code into tokens; newlines are kept as tokens."""
    tokens: list[str] = []
    for tok in _TOKEN_RE.findall(text):
        if tok.isspace() and tok != "\n":
            continue
        tokens.append(tok)
    return tokens


class _BehaviorParser:
    """
    Translates the Promela-style code of a task behavior into C statements.

    Supported: assignments, `skip`, `assert(...)`, and `if :: guard -> body ...
    fi` (nested, with `else` and guard-only options). An `if` becomes a switch
    on a nondeterministic value: each case assumes its guard and runs its body,
    so every enabled option is explored and none enabled blocks the path.
    """

    def __init__(self, text: str) -> None:
        self.tokens = _tokenize_behavior(text)
        self.pos = 0

    def parse(self) -> list[str]:
        return self._block()

    def _peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _skip_separators(self) -> None:
        while self._peek() in ("\n", ";"):
            self.pos += 1

    def _next_significant(self) -> str | None:
        i = self.pos
        while i < len(self.tokens) and self.tokens[i] in ("\n", ";"):
            i += 1
        return self.tokens[i] if i < len(self.tokens) else None

    def _block(self) -> list[str]:
        lines: list[str] = []
        while True:
            self._skip_separators()
            tok = self._peek()
            if tok is None or tok in ("::", "fi"):
                return lines
            if tok == "if":
                self.pos += 1
                lines.extend(self._if())
            else:
                stmt = self._simple()
                lines.extend(self._translate_stmt(stmt))

    def _simple(self) -> str:
        parts: list[str] = []
        while (tok := self._peek()) is not None and tok not in (
            "\n",
            ";",
            "::",
            "fi",
            "if",
        ):
            parts.append(tok)
            self.pos += 1
        return " ".join(parts)

    @staticmethod
    def _translate_stmt(stmt: str) -> list[str]:
        stmt = stmt.strip()
        if not stmt or stmt == "skip":
            return []
        if stmt.startswith("assert(") and stmt.endswith(")"):
            cond = stmt[len("assert(") : -1]
            return [f'__CPROVER_assert({cond}, "behavior assertion");']
        return [f"{stmt};"]

    def _guard(self) -> str:
        """Reads an option's guard; leaves the body for the caller."""
        start = self.pos
        parts: list[str] = []
        while True:
            tok = self._peek()
            if tok is None or tok in ("::", "fi"):
                break
            if tok == "->":
                self.pos += 1
                break
            if tok in ("\n", ";"):
                if self._next_significant() == "->" or (
                    tok == "\n" and parts and parts[-1] in ("&&", "||")
                ):
                    self._skip_separators()
                    continue
                break
            parts.append(tok)
            self.pos += 1
        guard = " ".join(parts)
        if _ASSIGN_RE.search(guard) or guard.startswith("assert("):
            # Not a condition: the option starts with a statement. Un-read it.
            self.pos = start
            return "true"
        return guard

    def _if(self) -> list[str]:
        options: list[tuple[str, list[str]]] = []
        while True:
            self._skip_separators()
            if self._peek() != "::":
                break
            self.pos += 1
            guard = self._guard()
            body = self._block()
            options.append((guard, body))
        if self._peek() == "fi":
            self.pos += 1
        if not options:
            return []

        lines = ["switch (nondet_uint()) {"]
        for i, (guard, body) in enumerate(options):
            lines.append(f"case {i}:")
            if guard == "else":
                others = " || ".join(f"({g})" for g, _ in options if g != "else")
                lines.append(f"\t__CPROVER_assume(!({others or 'false'}));")
            elif guard != "true":
                lines.append(f"\t__CPROVER_assume({guard});")
            lines.extend(f"\t{line}" for line in body)
            lines.append("\tbreak;")
        lines.append("default:")
        lines.append("\t__CPROVER_assume(0);")
        lines.append("\tbreak;")
        lines.append("}")
        return lines


def translate_behavior(behavior: str) -> list[str]:
    """C statements (with relative tab indentation) for a task's behavior."""
    return _BehaviorParser(behavior).parse()


def _ident(raw: str) -> str:
    """Make a BPMN id into a C identifier fragment, without merging distinct ids."""
    return re.sub(r"[^A-Za-z0-9_]", lambda m: f"_x{ord(m.group()):x}_", raw)


def place_name(element_id: str) -> str:
    """Name of the boolean that holds the token of a start event or flow."""
    return f"tok_{_ident(element_id)}"


def done_name(process_id: str) -> str:
    """Name of the boolean that is set once a process's end event has run."""
    return f"done_{_ident(process_id)}"


class BpmnCbmcVisitor(BpmnVisitor):
    """
    Generates C for the BPMN side of the CBMC model.

    Every token place is a bool, and every transition (start event, task,
    end event, intermediate event, or one outgoing flow of an exclusive
    gateway) gets an enable function and a run function. One pass of the
    main loop is `bpmn_step()`: it picks a transition with a nondeterministic
    choice, assumes it is enabled and runs it. The step has no loop over the
    transitions.
    """

    __slots__ = [
        "defs",
        "places",
        "transitions",
        "step",
        "error",
        "transition_count",
        "_place_inits",
        "_process_ids",
        "_process_id",
        "_dispatch",
    ]

    def __init__(self) -> None:
        self.defs = StringManager()
        self.places = StringManager()
        self.transitions = StringManager()
        self.step = StringManager()
        self.error: Error | None = None
        self.transition_count = 0
        self._place_inits: dict[str, bool] = {}
        self._process_ids: list[str] = []
        self._process_id = ""
        self._dispatch = StringManager()

    ####################
    # Helpers
    ####################

    def _add_place(self, name: str, initial: bool = False) -> None:
        self._place_inits[name] = self._place_inits.get(name, False) or initial

    def _fail(self, element_id: str, element_type: str) -> bool:
        if self.error is None:
            self.error = BpmnCbmcUnsupportedElementError(element_id, element_type)
        return False

    def _in_places(self, node: Node) -> tuple[list[str], list[str]]:
        """Returns the (in-process places, message places) a node consumes."""
        if isinstance(node, StartEvent):
            seq = [place_name(node.id)]
        else:
            seq = [place_name(flow.id) for flow in node.in_flows]
        return seq, [place_name(msg.id) for msg in node.in_msgs]

    def _declare_places(self, node: Node) -> None:
        if isinstance(node, StartEvent):
            self._add_place(place_name(node.id), initial=True)
        for flow in node.in_flows + node.out_flows:
            self._add_place(place_name(flow.id))
        for msg in node.in_msgs + node.out_msgs:
            self._add_place(place_name(msg.id))

    def _enable_expr(self, node: Node, extra: str = "") -> str:
        seq, msgs = self._in_places(node)
        parts: list[str] = []
        if seq:
            parts.append("(" + " || ".join(seq) + ")")
        parts.extend(msgs)
        if not parts:
            return "false"
        if extra:
            parts.append(f"({extra})")
        return " && ".join(parts)

    def _behavior_stmts(self, task: Task) -> list[str]:
        """Statements that run a task's behavior, then update the CWP state."""
        stmts = translate_behavior(task.behavior)
        if task.behavior.strip():
            stmts.append(f"{CWP_UPDATE_FUNC}();")
        return stmts

    def _add_transition(
        self,
        node: Node,
        enable: str,
        puts: list[str],
        extra_stmts: list[str] | None = None,
    ) -> None:
        index = self.transition_count
        self.transition_count += 1

        self.transitions.write_str(f"// {node.id}", NL_SINGLE, IndentAction.NIL)
        self.transitions.write_str(
            f"static bool enabled_{index}(void) {{", NL_SINGLE, IndentAction.INC
        )
        self.transitions.write_str(f"return {enable};", NL_SINGLE)
        self.transitions.write_str("}", NL_DOUBLE, IndentAction.DEC)

        self.transitions.write_str(
            f"static void run_{index}(void) {{", NL_SINGLE, IndentAction.INC
        )
        seq, msgs = self._in_places(node)
        for place in seq + msgs:
            self.transitions.write_str(f"CONSUME_TOKEN({place});", NL_SINGLE)
        for stmt in extra_stmts or []:
            self.transitions.write_str(stmt, NL_SINGLE)
        for place in puts:
            self.transitions.write_str(f"PUT_TOKEN({place});", NL_SINGLE)
        self.transitions.write_str("}", NL_DOUBLE, IndentAction.DEC)

        self._dispatch.write_str(f"case {index}:", NL_SINGLE, IndentAction.INC)
        self._dispatch.write_str(f"__CPROVER_assume(enabled_{index}());", NL_SINGLE)
        self._dispatch.write_str(f"run_{index}();", NL_SINGLE)
        self._dispatch.write_str("break;", NL_SINGLE, IndentAction.DEC)

    def _out_places(self, node: Node) -> list[str]:
        return [place_name(f.id) for f in node.out_flows + node.out_msgs]

    def _simple_transition(
        self, node: Node, extra_stmts: list[str] | None = None
    ) -> None:
        self._declare_places(node)
        self._add_transition(
            node, self._enable_expr(node), self._out_places(node), extra_stmts
        )

    def get_result(self) -> Result[str, Error]:
        if self.error is not None:
            return Failure(self.error)
        return Success(repr(self))

    def __repr__(self) -> str:
        return f"{self.defs}{self.places}{self.transitions}{self.step}"

    ####################
    # Visitor Methods
    ####################

    def visit_start_event(self, event: StartEvent) -> bool:
        self._simple_transition(event)
        return True

    def visit_end_event(self, event: EndEvent) -> bool:
        self._simple_transition(event, [f"{done_name(self._process_id)} = true;"])
        return True

    def visit_intermediate_event(self, event: IntermediateEvent) -> bool:
        self._simple_transition(event)
        return True

    def visit_task(self, task: Task) -> bool:
        self._simple_transition(task, self._behavior_stmts(task))
        return True

    def visit_boundary_event(self, boundary_event: Task.BoundaryEvent) -> bool:
        return self._fail(boundary_event.id, "boundary event")

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        self._declare_places(gateway)
        for flow in gateway.out_flows:
            condition = flow.expression.replace("\n", " ").strip()
            self._add_transition(
                gateway,
                self._enable_expr(gateway, condition),
                [place_name(flow.id)] + [place_name(m.id) for m in gateway.out_msgs],
            )
        return True

    def visit_parallel_gateway(self, gateway: ParallelGatewayNode) -> bool:
        self._declare_places(gateway)
        if gateway.is_fork:
            # A fork starts every branch and is enabled by any one incoming flow.
            enable = self._enable_expr(gateway)
        else:
            # A join waits for a token on every incoming flow.
            seq, msgs = self._in_places(gateway)
            enable = " && ".join(seq + msgs) or "false"
        self._add_transition(gateway, enable, self._out_places(gateway))
        return True

    def visit_message_flow(self, flow: MessageFlow) -> bool:
        self._add_place(place_name(flow.id))
        return True

    def visit_process(self, process: Process) -> bool:
        self._process_id = process.id
        self._process_ids.append(process.id)
        return True

    def end_visit_bpmn(self, bpmn: Bpmn) -> None:
        self.defs.write_str(HELPER_STR, NL_DOUBLE)

        for name, initial in self._place_inits.items():
            self.places.write_str(
                f"static bool {name} = {'true' if initial else 'false'};", NL_SINGLE
            )
        for process_id in self._process_ids:
            self.places.write_str(
                f"static bool {done_name(process_id)} = false;", NL_SINGLE
            )
        self.places.write_str("", NL_SINGLE)

        done = " && ".join(done_name(pid) for pid in self._process_ids) or "true"
        self.transitions.write_str(
            f"static bool {ALL_DONE_FUNC}(void) {{", NL_SINGLE, IndentAction.INC
        )
        self.transitions.write_str(f"return {done};", NL_SINGLE)
        self.transitions.write_str("}", NL_DOUBLE, IndentAction.DEC)

        self.step.write_str(
            f"static void {STEP_FUNC}(void) {{", NL_SINGLE, IndentAction.INC
        )
        self.step.write_str("unsigned int choice = nondet_uint();", NL_SINGLE)
        self.step.write_str(f"{COLLISION_VAR} = false;", NL_SINGLE)
        self.step.write_str("switch (choice) {", NL_SINGLE, IndentAction.INC)
        self.step.write_str(self._dispatch)
        self.step.write_str("default:", NL_SINGLE, IndentAction.INC)
        self.step.write_str("__CPROVER_assume(0);", NL_SINGLE)
        self.step.write_str("break;", NL_SINGLE, IndentAction.DEC)
        self.step.write_str("}", NL_SINGLE, IndentAction.DEC)
        self.step.write_str(
            f'__CPROVER_assert(!{COLLISION_VAR}, "token placed on an occupied place");',
            NL_SINGLE,
        )
        self.step.write_str("}", NL_SINGLE, IndentAction.DEC)
