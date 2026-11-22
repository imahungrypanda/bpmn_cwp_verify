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
NL_NONE = 0
NL_SINGLE = 1
NL_DOUBLE = 2

STEP_FUNC_NAME = "bpmn_step"
CHOICE_VAR = "choice"
DEFS_STR = "unsigned int nondet_uint(void);\n\n"
OCCUPIED_MSG = "Attempting to place token in already-occupied place"
##############


def _c_expr(raw: str) -> str:
    """Promela-style boolean literals to their C spelling."""
    return re.sub(r"\bfalse\b", "0", re.sub(r"\btrue\b", "1", " ".join(raw.split())))


def _tokenize_behavior(behavior: str) -> list[tuple[str, str, str]]:
    """
    Splits a Promela-style behavior into ("if"|"fi"|"opt"|"stmt", guard, text)
    tokens. An option is `:: guard -> statements`.
    """
    tokens: list[tuple[str, str, str]] = []
    for line in behavior.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line in ("if", "fi"):
            tokens.append((line, "", ""))
            continue
        rest = line
        if line.startswith("::"):
            guard, arrow, rest = line[2:].partition("->")
            if not arrow:
                raise ValueError(f"option without '->': {line}")
            tokens.append(("opt", guard.strip(), ""))
        for stmt in rest.split(";"):
            stmt = stmt.strip()
            if stmt in ("if", "fi"):
                tokens.append((stmt, "", ""))
            elif stmt:
                tokens.append(("stmt", "", stmt))
    return tokens


# A parsed behavior is a list of statements (str) and choices. A choice is a
# list of (guard, statements) options.
_Block = list["str | list[tuple[str, _Block]]"]


def _parse_block(tokens: list[tuple[str, str, str]], pos: int) -> tuple[_Block, int]:
    block: _Block = []
    while pos < len(tokens):
        kind, _, text = tokens[pos]
        if kind in ("opt", "fi"):
            break
        pos += 1
        if kind == "stmt":
            block.append(text)
            continue
        options: list[tuple[str, _Block]] = []
        while pos < len(tokens) and tokens[pos][0] == "opt":
            guard = tokens[pos][1]
            body, pos = _parse_block(tokens, pos + 1)
            options.append((guard, body))
        if not options or pos >= len(tokens) or tokens[pos][0] != "fi":
            raise ValueError("malformed if ... fi")
        pos += 1
        block.append(options)
    return block, pos


def _ident(raw: str) -> str:
    """Turns a BPMN id into something usable in a C identifier."""
    return re.sub(r"\W", "_", raw)


class Transition:
    """
    One thing the workflow can do in a single pass: the enable condition and
    the statements to run once the transition has been picked.
    """

    __slots__ = ["element_id", "enable", "body"]

    def __init__(self, element_id: str, enable: str, body: list[str]) -> None:
        self.element_id = element_id
        self.enable = enable
        self.body = body


class CbmcBpmnVisitor(BpmnVisitor):
    """
    Generates the BPMN half of the CBMC program.

    After visiting a Bpmn, `places` holds the token places and the per-process
    ended flags, `step` holds `bpmn_step()` (one pass of the main loop: pick one
    transition, assume it is enabled, run it), and `all_ended` is a C
    expression that is true once every process has ended.
    """

    __slots__ = [
        "defs",
        "places",
        "transitions",
        "errors",
        "_process_ids",
        "_ended_flags",
        "_seen",
        "_declared",
        "_choice_count",
    ]

    def __init__(self) -> None:
        self.defs = StringManager()
        self.places = StringManager()
        self.transitions: list[Transition] = []
        self.errors: list[Error] = []
        self._process_ids: list[str] = []
        self._ended_flags: list[str] = []
        self._seen: set[str] = set()
        self._declared: set[str] = set()
        self._choice_count = 0

    ####################
    # Naming
    ####################

    @staticmethod
    def seq_place(flow: SequenceFlow) -> str:
        return f"flow_{_ident(flow.id)}"

    @staticmethod
    def msg_place(flow: MessageFlow) -> str:
        return f"msg_{_ident(flow.id)}"

    @staticmethod
    def start_place(element: Node) -> str:
        return f"start_{_ident(element.id)}"

    @staticmethod
    def ended_flag(process_id: str) -> str:
        return f"ended_{_ident(process_id)}"

    @property
    def all_ended(self) -> str:
        if not self._ended_flags:
            return "1"
        return " && ".join(self._ended_flags)

    @property
    def step(self) -> StringManager:
        return self._build_step()

    ####################
    # Helpers
    ####################

    def _fail(self, element_id: str, reason: str) -> None:
        self.errors.append(BpmnCbmcUnsupportedElementError(element_id, reason))

    def _in_places(self, element: Node) -> tuple[list[str], list[str]]:
        """
        Returns (in-process places, message places) the element consumes from.
        A node without incoming sequence flows has a standalone start place.
        """
        if element.in_flows:
            seq = [self.seq_place(f) for f in element.in_flows]
        elif isinstance(element, StartEvent) or not element.in_msgs:
            seq = [self.start_place(element)]
        else:
            seq = []
        return seq, [self.msg_place(m) for m in element.in_msgs]

    def _declare_places(self, element: Node) -> None:
        seq, msgs = self._in_places(element)
        for place in seq + msgs:
            if place in self._declared:
                continue
            self._declared.add(place)
            init = 1 if place.startswith("start_") else 0
            self.places.write_str(f"_Bool {place} = {init};", NL_SINGLE)

    def _enable(self, element: Node, extra: str = "", join: bool = False) -> str:
        seq, msgs = self._in_places(element)
        parts = [f"!{self.ended_flag(self._process_ids[-1])}"]
        if seq:
            parts.append("(" + (" && " if join else " || ").join(seq) + ")")
        parts.extend(msgs)
        if extra:
            parts.append(f"({extra})")
        return " && ".join(parts)

    def _consume(self, element: Node) -> list[str]:
        seq, msgs = self._in_places(element)
        return [f"{place} = 0;" for place in seq + msgs]

    def _produce(self, outs: list[str], ended: bool = False) -> list[str]:
        """
        One occupancy check for the whole pass, then set the places.
        """
        lines: list[str] = []
        if outs:
            lines.append(f'__CPROVER_assert(!({" || ".join(outs)}), "{OCCUPIED_MSG}");')
        lines.extend(f"{place} = 1;" for place in outs)
        if ended:
            lines.append(f"{self.ended_flag(self._process_ids[-1])} = 1;")
        return lines

    def _out_places(self, element: Node, flows: list[SequenceFlow]) -> list[str]:
        return [self.seq_place(f) for f in flows] + [
            self.msg_place(m) for m in element.out_msgs
        ]

    def _emit_block(self, block: _Block) -> list[str]:
        lines: list[str] = []
        for item in block:
            if isinstance(item, str):
                if item != "skip":
                    lines.append(f"{_c_expr(item)};")
                continue
            # An if picks any option whose guard holds; else holds when no
            # other guard does.
            guards = [g for g, _ in item if g != "else"]
            var = f"bchoice_{self._choice_count}"
            self._choice_count += 1
            lines.append("{")
            lines.append(f"unsigned int {var} = nondet_uint();")
            lines.append(f"__CPROVER_assume({var} < {len(item)}u);")
            for idx, (guard, body) in enumerate(item):
                if guard == "else":
                    cond = " && ".join(f"!({_c_expr(g)})" for g in guards) or "1"
                else:
                    cond = _c_expr(guard)
                lines.append(f"{'else ' if idx else ''}if ({var} == {idx}u) {{")
                lines.append(f"__CPROVER_assume({cond});")
                lines.extend(self._emit_block(body))
                lines.append("}")
            lines.append("}")
        return lines

    def _behavior(self, task: Task) -> list[str]:
        """
        The task's behavior as C, followed by a CWP update, like the Promela
        visitor's updateState(). An empty behavior generates nothing.
        """
        if not task.behavior.strip():
            return []
        try:
            tokens = _tokenize_behavior(task.behavior)
            block, pos = _parse_block(tokens, 0)
            if pos != len(tokens):
                raise ValueError("unexpected option or fi")
        except ValueError as e:
            self._fail(task.id, f"unsupported behavior: {e}")
            return []
        return self._emit_block(block) + [f"{UPDATE_FUNC}();"]

    def _visit_plain(
        self,
        element: Node,
        behavior: list[str] | None = None,
        ended: bool = False,
    ) -> bool:
        if element.id in self._seen:
            return False
        self._seen.add(element.id)
        self._declare_places(element)
        body = self._consume(element)
        body.extend(behavior or [])
        body.extend(self._produce(self._out_places(element, element.out_flows), ended))
        self.transitions.append(Transition(element.id, self._enable(element), body))
        return True

    ####################
    # Assembly
    ####################

    def _build_step(self) -> StringManager:
        sm = StringManager()
        sm.write_str(f"void {STEP_FUNC_NAME}(void) {{", NL_SINGLE, IndentAction.INC)
        sm.write_str(f"unsigned int {CHOICE_VAR} = nondet_uint();", NL_SINGLE)
        count = len(self.transitions)
        sm.write_str(f"__CPROVER_assume({CHOICE_VAR} < {count}u);", NL_SINGLE)
        sm.write_str(f"switch ({CHOICE_VAR}) {{", NL_SINGLE)
        for idx, transition in enumerate(self.transitions):
            sm.write_str(f"case {idx}u: /* {transition.element_id} */", NL_SINGLE)
            sm.write_str("", NL_NONE, IndentAction.INC)
            sm.write_str(f"__CPROVER_assume({transition.enable});", NL_SINGLE)
            for line in transition.body:
                sm.write_str(line, NL_SINGLE)
            sm.write_str("break;", NL_SINGLE, IndentAction.NIL)
            sm.write_str("", NL_NONE, IndentAction.DEC)
        sm.write_str("default:", NL_SINGLE)
        sm.write_str("__CPROVER_assume(0);", NL_SINGLE)
        sm.write_str("}", NL_SINGLE)
        sm.write_str("}", NL_DOUBLE, IndentAction.DEC)
        return sm

    def get_result(self) -> Result[str, Error]:
        if self.errors:
            return Failure(self.errors[0])
        return Success(repr(self))

    def __repr__(self) -> str:
        flags = StringManager()
        for flag in self._ended_flags:
            flags.write_str(f"_Bool {flag} = 0;", NL_SINGLE)
        return f"{self.defs}{self.places}{flags}\n{self._build_step()}"

    ####################
    # Visitor Methods
    ####################

    def visit_start_event(self, event: StartEvent) -> bool:
        return self._visit_plain(event)

    def visit_end_event(self, event: EndEvent) -> bool:
        return self._visit_plain(event, ended=True)

    def visit_intermediate_event(self, event: IntermediateEvent) -> bool:
        return self._visit_plain(event)

    def visit_task(self, task: Task) -> bool:
        if task.msg_boundary_events:
            self._fail(task.id, "boundary events are not supported")
            return False
        return self._visit_plain(task, self._behavior(task))

    def visit_boundary_event(self, boundary_event: Task.BoundaryEvent) -> bool:
        self._fail(boundary_event.id, "boundary events are not supported")
        return False

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        if gateway.id in self._seen:
            return False
        self._seen.add(gateway.id)
        self._declare_places(gateway)

        flows = gateway.out_flows
        for flow in flows:
            expr = " ".join(flow.expression.split())
            if expr:
                cond = f"({expr})"
            elif len(flows) > 1:
                # A flow without a condition is the default: taken only when
                # no other flow's condition holds.
                others = [
                    " ".join(o.expression.split()) for o in flows if o is not flow
                ]
                cond = " && ".join(f"!({o})" for o in others if o) or ""
            else:
                cond = ""
            body = self._consume(gateway)
            body.extend(self._produce(self._out_places(gateway, [flow])))
            self.transitions.append(
                Transition(
                    f"{gateway.id}->{flow.id}", self._enable(gateway, cond), body
                )
            )
        return True

    def visit_parallel_gateway(self, gateway: ParallelGatewayNode) -> bool:
        if gateway.id in self._seen:
            return False
        self._seen.add(gateway.id)
        self._declare_places(gateway)
        outs = self._out_places(gateway, gateway.out_flows)

        if not gateway.is_fork:
            # Join: waits for a token on every incoming flow.
            body = self._consume(gateway)
            body.extend(self._produce(outs))
            self.transitions.append(
                Transition(gateway.id, self._enable(gateway, join=True), body)
            )
        elif len(gateway.in_flows) > 1:
            # Fork that is also a merge (e.g. a loop coming back in): each
            # arriving token starts every branch, so one transition per
            # incoming flow, each consuming only its own token.
            for flow in gateway.in_flows:
                place = self.seq_place(flow)
                body = [f"{place} = 0;"]
                body.extend(self._produce(outs))
                self.transitions.append(
                    Transition(
                        f"{flow.id}->{gateway.id}",
                        f"!{self.ended_flag(self._process_ids[-1])} && {place}",
                        body,
                    )
                )
        else:
            body = self._consume(gateway)
            body.extend(self._produce(outs))
            self.transitions.append(Transition(gateway.id, self._enable(gateway), body))
        return True

    def visit_message_flow(self, flow: MessageFlow) -> bool:
        return True

    def visit_process(self, process: Process) -> bool:
        self._process_ids.append(process.id)
        flag = self.ended_flag(process.id)
        self._ended_flags.append(flag)
        return True

    def visit_bpmn(self, bpmn: Bpmn) -> bool:
        self.defs.write_str(DEFS_STR)
        return True
