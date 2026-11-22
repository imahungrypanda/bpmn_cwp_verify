import re
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
from bpmncwpverify.visitors.cwp_cbmc_visitor import UPDATE_STATE_FUNC

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
UPDATE_VAR = "bpmn_update_cwp"
OPTION_PREFIX = "bpmn_option_"
NONDET_DECL = "unsigned int nondet_uint(void);"
COLLISION_MSG = "Attempting to place token in already-occupied place"


def _place(flow_or_node_id: str) -> str:
    return f"{TOKEN_PREFIX}{flow_or_node_id}"


def _c_expr(expr: str) -> str:
    """Promela's true/false are not C; everything else we accept is the same."""
    expr = " ".join(expr.split())
    expr = re.sub(r"\btrue\b", "1", expr)
    return re.sub(r"\bfalse\b", "0", expr)


##############
# Behaviors
##############
_ASSIGN_RE = re.compile(r"^[A-Za-z_]\w*(\[[^\]]*\])?\s*(=(?!=)|\+=|-=)\s*\S")
_INCDEC_RE = re.compile(r"^[A-Za-z_]\w*(\[[^\]]*\])?\s*(\+\+|--)$")
_ASSERT_RE = re.compile(r"^assert\s*\((.*)\)$")
_OPTION_RE = re.compile(r"^::\s*(.*)$")
_IF_RE = re.compile(r"^if\b\s*(.*)$")
_FI_RE = re.compile(r"^fi\b\s*(.*)$")

# A parsed behavior is a list of statements: either a string (a simple
# statement, already C) or an `_If`.
_Stmts = list["str | _If"]


class _If:
    """A Promela `if`: options of (guard, statements), guard None for `else`."""

    __slots__ = ["options"]

    def __init__(self) -> None:
        self.options: list[tuple[str | None, _Stmts]] = []


class BehaviorError(Exception):
    """A behavior statement that has no C translation."""


def _tokens(behavior: str) -> list[str]:
    """Split a behavior into `if`, `fi`, `:: <guard> ->` and simple statements."""
    out: list[str] = []

    def feed(text: str) -> None:
        text = text.strip().strip(";").strip()
        if not text:
            return
        if text.endswith(" fi"):
            feed(text[:-3])
            out.append("fi")
        elif m := _IF_RE.match(text):
            out.append("if")
            feed(m.group(1))
        elif m := _FI_RE.match(text):
            out.append("fi")
            feed(m.group(1))
        elif m := _OPTION_RE.match(text):
            rest = m.group(1)
            if "->" in rest:
                guard, _, rest = rest.partition("->")
                out.append(f":: {guard.strip()}")
                feed(rest)
            else:
                out.append(f":: {rest.strip()}")
        else:
            for part in text.split(";"):
                if part.strip():
                    out.append(part.strip())

    for line in behavior.splitlines():
        feed(line)
    return out


def _translate_simple(stmt: str) -> str | None:
    """C for a simple statement, None if it does nothing."""
    if stmt == "skip":
        return None
    if m := _ASSERT_RE.match(stmt):
        msg = stmt.replace('"', "'").replace("\\", "/")
        return f'__CPROVER_assert({_c_expr(m.group(1))}, "behavior {msg}");'
    if _ASSIGN_RE.match(stmt) or _INCDEC_RE.match(stmt):
        return f"{_c_expr(stmt)};"
    raise BehaviorError(stmt)


def _parse_block(tokens: list[str], pos: int, in_option: bool) -> tuple[_Stmts, int]:
    """Parse statements until a `::` or `fi` of the enclosing `if` (or the end)."""
    stmts: _Stmts = []
    while pos < len(tokens):
        tok = tokens[pos]
        if tok == "fi" or tok.startswith("::"):
            if not in_option:
                raise BehaviorError(tok)
            return stmts, pos
        if tok == "if":
            node = _If()
            pos += 1
            while pos < len(tokens) and tokens[pos].startswith("::"):
                guard = tokens[pos][2:].strip()
                body, pos = _parse_block(tokens, pos + 1, True)
                node.options.append((None if guard == "else" else _c_expr(guard), body))
            if pos >= len(tokens) or tokens[pos] != "fi" or not node.options:
                raise BehaviorError("if")
            stmts.append(node)
            pos += 1
        else:
            c = _translate_simple(tok)
            if c:
                stmts.append(c)
            pos += 1
    if in_option:
        raise BehaviorError("if")
    return stmts, pos


def parse_behavior(behavior: str) -> _Stmts:
    """Translate a task behavior (a Promela subset) into a statement tree."""
    return _parse_block(_tokens(behavior), 0, False)[0]


class Transition:
    """One thing that can fire in a pass: an enable condition and a body."""

    __slots__ = ["body", "enable", "name"]

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
      boundary events and behavior statements with no C translation are not
      supported).

    Parallel gateways follow the Promela visitor: a fork (more than one
    outgoing flow) is enabled when any incoming flow has a token and starts
    every outgoing flow; a join waits for a token on every incoming flow.

    A task's behavior is translated into C inside its transition, after the
    incoming places are cleared. A non-empty behavior also sets
    `bpmn_update_cwp`, and `bpmn_step()` calls `cwp_update_state()` once, after
    the transition, if it is set. An `if` becomes a nondeterministic choice
    among the options whose guard holds, so the step still has no loop.
    """

    __slots__ = [
        "_option_count",
        "_process_id",
        "_seen",
        "_updates_cwp",
        "defs",
        "errors",
        "places",
        "process_ids",
        "step_func",
        "transitions",
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
        self._option_count = 0
        self._updates_cwp = False

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

    def _enable(self, node: Node, extra: str = "", join: bool = False) -> str:
        """
        One of the incoming sequence places has a token (all of them for a
        join) and all of the incoming message places do. A node with no incoming
        flows (start event) uses its own place.
        """
        seq, msgs = self._in_places(node)
        if not (seq or msgs):
            seq = [_place(node.id)]
        parts: list[str] = []
        if seq:
            parts.append("(" + (" && " if join else " || ").join(seq) + ")")
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

    def _simple_node(
        self, node: Node, extra_lines: list[str] | None = None, join: bool = False
    ) -> bool:
        if self._first_visit(node):
            self._add_transition(
                node.id,
                self._enable(node, join=join),
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

    def _behavior_lines(self, task: Task) -> list[str]:
        try:
            stmts = parse_behavior(task.behavior)
        except BehaviorError as e:
            self._unsupported(task.id, f"behavior statement '{e}'")
            return []
        if not stmts:
            return []
        self._updates_cwp = True
        sm = StringManager()
        self._write_stmts(sm, stmts)
        return [*str(sm).splitlines(), f"{UPDATE_VAR} = 1;"]

    def _write_stmts(self, sm: StringManager, stmts: _Stmts) -> None:
        for stmt in stmts:
            if isinstance(stmt, str):
                sm.write_str(stmt, NL_SINGLE)
            else:
                self._write_if(sm, stmt)

    def _write_if(self, sm: StringManager, node: _If) -> None:
        """
        Promela picks any option whose guard holds (`else` when none does) and
        blocks when there is none; here that is a nondeterministic choice and
        an assume per option.
        """
        self._option_count += 1
        choice = f"{OPTION_PREFIX}{self._option_count}"
        guards = [g for g, _ in node.options if g is not None]
        sm.write_str(f"unsigned int {choice} = nondet_uint();", NL_SINGLE)
        sm.write_str(f"__CPROVER_assume({choice} < {len(node.options)});", NL_SINGLE)
        sm.write_str(f"switch ({choice}) {{", NL_SINGLE)
        for idx, (guard, body) in enumerate(node.options):
            sm.write_str(f"case {idx}: {{", NL_SINGLE, IndentAction.INC)
            if guard is None:
                guard = " && ".join(f"!({g})" for g in guards) or "1"
            sm.write_str(f"__CPROVER_assume({guard});", NL_SINGLE)
            self._write_stmts(sm, body)
            sm.write_str("break;", NL_SINGLE)
            sm.write_str("}", NL_SINGLE, IndentAction.DEC)
        sm.write_str("default: break;", NL_SINGLE)
        sm.write_str("}", NL_SINGLE)

    def visit_task(self, task: Task) -> bool:
        if task.id in self._seen:
            return True
        return self._simple_node(task, self._behavior_lines(task))

    def visit_boundary_event(self, boundary_event: Task.BoundaryEvent) -> bool:
        return self._unsupported(boundary_event.id, "boundary event")

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        if not self._first_visit(gateway):
            return True
        for flow in gateway.out_flows:
            expr = _c_expr(flow.expression) or "1"
            self._add_transition(
                f"{gateway.id}_{flow.id}",
                self._enable(gateway, expr),
                self._body(
                    gateway, [_place(flow.id)] + self._flow_places(gateway.out_msgs)
                ),
            )
        return True

    def visit_parallel_gateway(self, gateway: ParallelGatewayNode) -> bool:
        return self._simple_node(gateway, join=not gateway.is_fork)

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
        if self._updates_cwp:
            sm.write_str(f"_Bool {UPDATE_VAR} = 0;", NL_SINGLE)
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
        if self._updates_cwp:
            sm.write_str(f"if ({UPDATE_VAR}) {UPDATE_STATE_FUNC}();", NL_SINGLE)
        sm.write_str("}", NL_DOUBLE, IndentAction.DEC)

    def __repr__(self) -> str:
        return f"{self.defs}{self.step_func}"
