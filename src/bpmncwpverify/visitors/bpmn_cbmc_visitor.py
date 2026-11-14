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
from bpmncwpverify.core.error import BpmnUnsupportedForCError, Error
from bpmncwpverify.util.stringmanager import IndentAction, StringManager

##############
# Constants
##############
NL_NONE = 0
NL_SINGLE = 1
NL_DOUBLE = 2
CHOICE_VAR = "bpmn_choice"
NONDET_DECL = "unsigned int nondet_uint(void);"
ASSIGN_RE = re.compile(r"^[A-Za-z_]\w*(\[[^\]]*\])?\s*(=(?!=)|\+=|-=)\s*\S.*$")
INCDEC_RE = re.compile(r"^[A-Za-z_]\w*(\[[^\]]*\])?\s*(\+\+|--)$")
ASSERT_RE = re.compile(r"^assert\s*\((.*)\)$", re.DOTALL)
CWP_UPDATE = "cwp_update();"
NO_VIABLE_PATH_MSG = "No viable path to take"
OCCUPIED_MSG = "Attempting to place token in already-occupied place"


##############


def _sanitize(name: str) -> str:
    return re.sub(r"\W", "_", name)


def seq_place(flow_id: str) -> str:
    return f"tok_{_sanitize(flow_id)}"


def msg_place(flow_id: str) -> str:
    return f"msg_{_sanitize(flow_id)}"


def ended_flag(process_id: str) -> str:
    return f"ended_{_sanitize(process_id)}"


class _UnsupportedBehavior(Exception):
    pass


def _behavior_items(behavior: str) -> list[tuple[str, str]]:
    """
    Splits a behavior into ("if" | "fi" | "opt" | "stmt", text) items. An
    option's text is its guard; whatever follows `->` on its line becomes the
    next item.
    """
    items: list[tuple[str, str]] = []

    def add(text: str) -> None:
        text = text.strip()
        if not text:
            return
        if text.startswith("::"):
            guard, arrow, rest = text[2:].partition("->")
            items.append(("opt", guard.strip()))
            if arrow:
                add(rest)
        elif text == "if" or text.startswith("if "):
            items.append(("if", ""))
            add(text[2:])
        elif text == "fi":
            items.append(("fi", ""))
        else:
            items.append(("stmt", text))

    for line in behavior.split("\n"):
        # `;` separates statements, but not inside parentheses
        depth, start = 0, 0
        for pos, char in enumerate(line):
            depth += (char == "(") - (char == ")")
            if char == ";" and depth == 0:
                add(line[start:pos])
                start = pos + 1
        add(line[start:])
    return items


class _BehaviorTranslator:
    """
    Translates the Promela-flavored behavior of a task to C statements. Supports
    assignments, `assert`, `skip`, and (nested) `if ... fi`. An `if` picks a
    nondeterministic option whose guard holds; `else` is taken only when no
    other guard holds, and an `if` with nothing enabled blocks, as in Promela.
    """

    def __init__(self, behavior: str, task_id: str) -> None:
        self.items = _behavior_items(behavior)
        self.pos = 0
        self.task_id = task_id
        self.choices = 0

    def translate(self) -> list[str]:
        lines = self._block(0)
        if self.pos < len(self.items):
            raise _UnsupportedBehavior(self.items[self.pos][0])
        return lines

    def _block(self, depth: int) -> list[str]:
        out: list[str] = []
        indent = "\t" * depth
        while self.pos < len(self.items):
            kind, text = self.items[self.pos]
            if kind in ("fi", "opt"):
                break
            self.pos += 1
            if kind == "if":
                out += self._if(depth)
            elif text == "skip":
                continue
            elif match := ASSERT_RE.match(text):
                msg = f"Assert: behavior of {self.task_id}"
                out.append(f'{indent}__CPROVER_assert({match.group(1)}, "{msg}");')
            elif ASSIGN_RE.match(text) or INCDEC_RE.match(text):
                out.append(f"{indent}{text};")
            else:
                raise _UnsupportedBehavior(text)
        return out

    def _if(self, depth: int) -> list[str]:
        options: list[tuple[str, list[str]]] = []
        while self.pos < len(self.items) and self.items[self.pos][0] == "opt":
            guard = self.items[self.pos][1]
            self.pos += 1
            options.append((guard, self._block(depth + 2)))
        if (
            self.pos >= len(self.items)
            or self.items[self.pos][0] != "fi"
            or not options
        ):
            raise _UnsupportedBehavior("if")
        self.pos += 1

        indent = "\t" * depth
        var = f"bpmn_if_{self.choices}"
        self.choices += 1
        explicit = [f"({g})" for g, _ in options if g and g != "else"]
        out = [
            f"{indent}{{",
            f"{indent}\tunsigned int {var} = nondet_uint();",
            f"{indent}\t__CPROVER_assume({var} < {len(options)});",
            f"{indent}\tswitch ({var}) {{",
        ]
        for index, (guard, body) in enumerate(options):
            if guard == "else":
                cond = f"!({' || '.join(explicit)})" if explicit else "1"
            else:
                cond = f"({guard})"
            out.append(f"{indent}\tcase {index}:")
            out.append(f"{indent}\t\t__CPROVER_assume({cond});")
            out += body
            out.append(f"{indent}\t\tbreak;")
        out += [
            f"{indent}\tdefault:",
            f"{indent}\t\t__CPROVER_assume(0);",
            f"{indent}\t}}",
            f"{indent}}}",
        ]
        return out


class Transition:
    """
    One thing that can happen in a pass of the loop: its enable condition, the
    places it clears, the behavior it runs, and the places it fills.
    """

    __slots__ = [
        "label",
        "process_id",
        "enable",
        "clear",
        "behavior",
        "sets",
        "ends_process",
        "fails_with",
    ]

    def __init__(
        self,
        label: str,
        process_id: str,
        enable: str,
        clear: list[str],
        sets: list[str],
        behavior: list[str] | None = None,
        ends_process: bool = False,
        fails_with: str = "",
    ) -> None:
        self.label = label
        self.process_id = process_id
        self.enable = enable
        self.clear = clear
        self.sets = sets
        self.behavior = behavior if behavior is not None else []
        self.ends_process = ends_process
        self.fails_with = fails_with


class CbmcBpmnGenVisitor(BpmnVisitor):
    """
    Turns BPMN into the pieces of the C program that models how it runs:

    - `defs`: the token places, one flag per process saying it has ended, and
      the declaration of the nondeterministic choice function
    - `init`: statements that put the initial tokens on the start events
    - `step`: one pass of the workflow loop: pick one transition, assume it is
      enabled, run it. It contains no loop over the transitions.
    - `all_ended`: a C expression that is true once every process has ended
    """

    __slots__ = [
        "defs",
        "init",
        "step",
        "all_ended",
        "errors",
        "transitions",
        "_places",
        "_process_ids",
        "_current_process",
        "_seen",
    ]

    def __init__(self) -> None:
        self.defs = StringManager()
        self.init = StringManager()
        self.step = StringManager()
        self.all_ended = "true"
        self.errors: list[Error] = []
        self.transitions: list[Transition] = []
        self._places: dict[str, None] = {}
        self._process_ids: list[str] = []
        self._current_process = ""
        self._seen: set[str] = set()

    ####################
    # Helpers
    ####################

    def _unsupported(self, element: Node, element_type: str) -> bool:
        self.errors.append(BpmnUnsupportedForCError(element.id, element_type))
        return False

    def _first_visit(self, element: Node) -> bool:
        if element.id in self._seen:
            return False
        self._seen.add(element.id)
        return True

    def _declare(self, places: list[str]) -> None:
        for place in places:
            self._places[place] = None

    def _in_places(self, element: Node) -> tuple[list[str], list[str]]:
        """
        Returns the sequence flow places and the message flow places that
        feed the element. An element with no incoming flows has a place of its
        own.
        """
        if not (element.in_flows or element.in_msgs):
            return [seq_place(element.id)], []
        return (
            [seq_place(flow.id) for flow in element.in_flows],
            [msg_place(flow.id) for flow in element.in_msgs],
        )

    def _out_places(self, element: Node) -> list[str]:
        return [seq_place(flow.id) for flow in element.out_flows] + [
            msg_place(flow.id) for flow in element.out_msgs
        ]

    def _guard(self, element: Node, all_in: bool = False) -> str:
        """
        The element's incoming places: a token on any sequence flow (on every
        one if `all_in`), and on every message flow.
        """
        seq, msgs = self._in_places(element)
        joiner = " && " if all_in else " || "
        parts = [f"({joiner.join(seq)})"] if seq else []
        parts += [f"({' && '.join(msgs)})"] if msgs else []
        return " && ".join(parts)

    def _enable(self, element: Node, *extra: str, all_in: bool = False) -> str:
        parts = [
            f"!{ended_flag(self._current_process)}",
            self._guard(element, all_in),
        ]
        parts += extra
        return " && ".join(parts)

    def _add_transition(
        self,
        element: Node,
        label: str,
        enable: str,
        sets: list[str],
        behavior: list[str] | None = None,
        ends_process: bool = False,
        fails_with: str = "",
    ) -> None:
        seq, msgs = self._in_places(element)
        clear = seq + msgs
        self._declare(clear + sets)
        self.transitions.append(
            Transition(
                label,
                self._current_process,
                enable,
                clear,
                sets,
                behavior,
                ends_process,
                fails_with,
            )
        )

    def _gen_behavior(self, task: Task) -> list[str] | None:
        """
        The statements that run a task's behavior, ending with the CWP update
        when there is one. None if the behavior can't be expressed in C.
        """
        if not task.behavior:
            return []
        try:
            lines = _BehaviorTranslator(task.behavior, task.id).translate()
        except _UnsupportedBehavior:
            return None
        return [*lines, CWP_UPDATE]

    def _simple_transition(
        self,
        element: Node,
        behavior: list[str] | None = None,
        ends_process: bool = False,
    ) -> None:
        self._add_transition(
            element,
            element.id,
            self._enable(element),
            self._out_places(element),
            behavior,
            ends_process,
        )

    ####################
    # Output
    ####################

    def _build_transition(self, index: int, transition: Transition) -> StringManager:
        sm = StringManager()
        sm.write_str(
            f"case {index}: /* {transition.label} */", NL_SINGLE, IndentAction.INC
        )
        sm.write_str(f"__CPROVER_assume({transition.enable});", NL_SINGLE)
        if transition.fails_with:
            sm.write_str(f'__CPROVER_assert(0, "{transition.fails_with}");', NL_SINGLE)
        for place in transition.clear:
            sm.write_str(f"{place} = false;", NL_SINGLE)
        for line in transition.behavior:
            sm.write_str(line, NL_SINGLE)
        if transition.sets:
            occupied = " || ".join(transition.sets)
            sm.write_str(
                f'__CPROVER_assert(!({occupied}), "{OCCUPIED_MSG}");', NL_SINGLE
            )
        for place in transition.sets:
            sm.write_str(f"{place} = true;", NL_SINGLE)
        if transition.ends_process:
            sm.write_str(f"{ended_flag(transition.process_id)} = true;", NL_SINGLE)
        sm.write_str("break;", NL_SINGLE, IndentAction.DEC)
        return sm

    def _build_step(self) -> None:
        count = len(self.transitions)
        self.step.write_str("{", NL_SINGLE, IndentAction.INC)
        if count == 0:
            self.step.write_str("__CPROVER_assume(0);", NL_SINGLE)
        else:
            self.step.write_str(
                f"unsigned int {CHOICE_VAR} = nondet_uint();", NL_SINGLE
            )
            self.step.write_str(f"__CPROVER_assume({CHOICE_VAR} < {count});", NL_SINGLE)
            self.step.write_str(
                f"switch ({CHOICE_VAR}) {{", NL_SINGLE, IndentAction.INC
            )
            for index, transition in enumerate(self.transitions):
                self.step.write_str(self._build_transition(index, transition))
            self.step.write_str("default:", NL_SINGLE, IndentAction.INC)
            self.step.write_str("__CPROVER_assume(0);", NL_SINGLE)
            self.step.write_str("break;", NL_SINGLE, IndentAction.DEC)
            self.step.write_str("}", NL_SINGLE, IndentAction.DEC)
        self.step.write_str("}", NL_SINGLE, IndentAction.DEC)

    def result(self) -> Result[str, Error]:
        """
        The generated C, or the first element that C can't express.
        """
        if self.errors:
            return Failure(self.errors[0])
        return Success(repr(self))

    def __repr__(self) -> str:
        return f"{self.defs}{self.init}{self.step}"

    ####################
    # Visitor Methods
    ####################

    def visit_start_event(self, event: StartEvent) -> bool:
        if not self._first_visit(event):
            return False
        if event.in_flows or event.in_msgs:
            return self._unsupported(event, "start event with incoming flows")
        self._simple_transition(event)
        place = seq_place(event.id)
        self.init.write_str(f"{place} = true;", NL_SINGLE)
        return True

    def visit_end_event(self, event: EndEvent) -> bool:
        if not self._first_visit(event):
            return False
        self._simple_transition(event, ends_process=True)
        return True

    def visit_intermediate_event(self, event: IntermediateEvent) -> bool:
        if not self._first_visit(event):
            return False
        self._simple_transition(event)
        return True

    def visit_task(self, task: Task) -> bool:
        if not self._first_visit(task):
            return False
        if task.msg_boundary_events:
            return self._unsupported(task, "task with boundary events")
        behavior = self._gen_behavior(task)
        if behavior is None:
            return self._unsupported(task, "task behavior")
        self._simple_transition(task, behavior)
        return True

    def visit_boundary_event(self, boundary_event: Task.BoundaryEvent) -> bool:
        return self._unsupported(boundary_event, "boundary event")

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        if not self._first_visit(gateway):
            return False
        expressions = [" ".join(flow.expression.split()) for flow in gateway.out_flows]
        for flow, expression in zip(gateway.out_flows, expressions):
            extra = [f"({expression})"] if expression else []
            self._add_transition(
                gateway,
                f"{gateway.id} -> {flow.id}",
                self._enable(gateway, *extra),
                [seq_place(flow.id)],
            )
        if gateway.out_flows and all(expressions):
            none_hold = [f"!({expression})" for expression in expressions]
            self._add_transition(
                gateway,
                f"{gateway.id} -> no viable path",
                self._enable(gateway, *none_hold),
                [],
                fails_with=NO_VIABLE_PATH_MSG,
            )
        return True

    def visit_parallel_gateway(self, gateway: ParallelGatewayNode) -> bool:
        if not self._first_visit(gateway):
            return False
        # A fork starts when any incoming flow has a token (a loop can come
        # back into it); a join waits for all of them
        self._add_transition(
            gateway,
            gateway.id,
            self._enable(gateway, all_in=not gateway.is_fork),
            self._out_places(gateway),
        )
        return True

    def visit_message_flow(self, flow: MessageFlow) -> bool:
        # Message flows become places through the nodes at their ends
        return True

    def visit_process(self, process: Process) -> bool:
        self._current_process = process.id
        self._process_ids.append(process.id)
        return True

    def visit_bpmn(self, bpmn: Bpmn) -> bool:
        return True

    def end_visit_bpmn(self, bpmn: Bpmn) -> None:
        self.defs.write_str(NONDET_DECL, NL_DOUBLE)
        for place in self._places:
            self.defs.write_str(f"static bool {place} = false;", NL_SINGLE)
        for process_id in self._process_ids:
            self.defs.write_str(
                f"static bool {ended_flag(process_id)} = false;", NL_SINGLE
            )
        self.defs.write_str("", NL_SINGLE)
        if self._process_ids:
            self.all_ended = " && ".join(ended_flag(p) for p in self._process_ids)
        self._build_step()
