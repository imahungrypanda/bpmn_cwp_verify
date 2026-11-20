import re

from bpmncwpverify.core.bpmn import (
    Bpmn,
    BpmnVisitor,
    EndEvent,
    ExclusiveGatewayNode,
    IntermediateEvent,
    Node,
    ParallelGatewayNode,
    Process,
    StartEvent,
    Task,
)
from bpmncwpverify.core.error import BpmnCbmcUnsupportedElementError, Error
from bpmncwpverify.util.stringmanager import IndentAction, StringManager
from bpmncwpverify.visitors.cwp_cbmc_visitor import UPDATE_FUNCTION

##############
# Constants
##############
NL_NONE = 0
NL_SINGLE = 1
NL_DOUBLE = 2

DEFS_STR = "#include <stdbool.h>\n\nunsigned int nondet_uint(void);\n"
OCCUPIED_MSG = "Attempting to place token in already-occupied place"


def _c_name(raw_id: str) -> str:
    return re.sub(r"\W", "_", raw_id)


def _place(raw_id: str) -> str:
    return f"tok_{_c_name(raw_id)}"


# A line of generated C and what it does to the indentation after it.
Line = tuple[str, IndentAction]

_UNSUPPORTED_KEYWORDS = {"do", "od", "atomic", "d_step", "break", "goto", "printf"}


class _BehaviorError(Exception):
    pass


class _BehaviorTranslator:
    """
    Translates a task behavior, written in the Promela subset the SPIN back end
    accepts, into C: assignments, and `if :: guard -> ... :: else -> ... fi`
    blocks, which may nest. An `if` picks nondeterministically among the
    options whose guard holds, and an `else` option is only open when no other
    guard holds. If no option is open the path is not feasible, as in Promela.
    """

    def __init__(self, text: str) -> None:
        self._lines = [
            part.strip()
            for line in text.split("\n")
            for part in line.split(";")
            if part.strip()
        ]
        self._pos = 0
        self._count = 0
        self.out: list[Line] = []

    def translate(self) -> list[Line]:
        self._block(top=True)
        return self.out

    def _emit(self, text: str, action: IndentAction = IndentAction.NIL) -> None:
        self.out.append((text, action))

    def _statement(self, text: str) -> None:
        if text == "skip":
            return
        if text.split(" ")[0] in _UNSUPPORTED_KEYWORDS or "->" in text:
            raise _BehaviorError(text)
        self._emit(f"{text};")

    def _block(self, top: bool = False) -> None:
        """Statements up to the `::` or `fi` that ends them."""
        while self._pos < len(self._lines):
            line = self._lines[self._pos]
            if line == "fi" or line.startswith("::"):
                if top:
                    raise _BehaviorError(line)
                return
            self._pos += 1
            if line == "if":
                self._if()
            else:
                self._statement(line)

    def _if(self) -> None:
        index = self._count
        self._count += 1
        body: list[list[Line]] = []
        guards: list[str] = []
        while True:
            if self._pos >= len(self._lines):
                raise _BehaviorError("if without fi")
            line = self._lines[self._pos]
            if line == "fi":
                self._pos += 1
                break
            if not line.startswith("::") or "->" not in line:
                raise _BehaviorError(line)
            guard, rest = line[2:].split("->", 1)
            guards.append(guard.strip().replace("\n", " "))
            self._pos += 1
            saved, self.out = self.out, []
            if rest.strip():
                self._lines.insert(self._pos, rest.strip())
            self._block()
            body.append(self.out)
            self.out = saved
        if not guards:
            raise _BehaviorError("empty if")

        choice = f"choice{index}"
        others = " || ".join(f"({g})" for g in guards if g != "else") or "false"
        self._emit("{", IndentAction.INC)
        self._emit(f"unsigned int {choice} = nondet_uint();")
        self._emit(f"switch ({choice}) {{", IndentAction.INC)
        for i, (guard, lines) in enumerate(zip(guards, body)):
            self._emit(f"case {i}:", IndentAction.INC)
            cond = f"!({others})" if guard == "else" else guard
            self._emit(f"__CPROVER_assume({cond});")
            self.out.extend(lines)
            self._emit("break;", IndentAction.DEC)
        self._emit("default:", IndentAction.INC)
        self._emit("__CPROVER_assume(0);", IndentAction.DEC)
        self._emit("}", IndentAction.DEC)
        self._emit("}", IndentAction.DEC)


def _ended(process_id: str) -> str:
    return f"ended_{_c_name(process_id)}"


class Transition:
    """
    One thing that can happen in a pass of the loop: a start event, a task,
    an end event, or one outgoing flow of an exclusive gateway.
    """

    __slots__ = ["label", "enable", "consume", "produce", "ends", "behavior"]

    def __init__(
        self,
        label: str,
        enable: str,
        consume: list[str],
        produce: list[str],
        ends: str = "",
        behavior: list[Line] | None = None,
    ) -> None:
        self.behavior = behavior or []
        self.label = label
        self.enable = enable
        self.consume = consume
        self.produce = produce
        self.ends = ends


class CbmcBpmnVisitor(BpmnVisitor):
    """
    Turns BPMN into the pieces of the C program that models how it runs.

    `defs`      the token places and the process-ended flags
    `init`      statements that put the initial tokens on the start events
    `step`      one pass of the loop: pick a transition, assume it is enabled,
                run it, check that no token landed on an occupied place.
                It is a block, meant to go inside the loop in `main()`.
    `all_ended` a C expression that is true once every process has ended
    `errors`    BPMN elements that C cannot express
    """

    __slots__ = [
        "_places",
        "_processes",
        "_transitions",
        "_seen",
        "_process_id",
        "errors",
    ]

    def __init__(self) -> None:
        self._places: dict[str, bool] = {}
        self._processes: list[str] = []
        self._transitions: list[Transition] = []
        self._seen: set[str] = set()
        self._process_id = ""
        self.errors: list[Error] = []

    ####################
    # Helpers
    ####################

    def _unsupported(self, node: Node, element_type: str) -> None:
        self.errors.append(BpmnCbmcUnsupportedElementError(node.id, element_type))

    def _add_place(self, name: str, initial: bool = False) -> str:
        self._places[name] = self._places.get(name, False) or initial
        return name

    def _consume_places(self, node: Node) -> tuple[list[str], list[str]]:
        """
        Returns (sequence places, message places) the node waits on.
        """
        seq = [self._add_place(_place(flow.id)) for flow in node.in_flows]
        msgs = [self._add_place(_place(flow.id)) for flow in node.in_msgs]
        return seq, msgs

    def _produce_places(self, node: Node) -> list[str]:
        return [
            self._add_place(_place(flow.id)) for flow in node.out_flows + node.out_msgs
        ]

    def _enable(
        self,
        seq: list[str],
        msgs: list[str],
        extra: str = "",
        all_seq: bool = False,
    ) -> str:
        parts: list[str] = []
        if seq:
            parts.append("(" + (" && " if all_seq else " || ").join(seq) + ")")
        if msgs:
            parts.append("(" + " && ".join(msgs) + ")")
        if extra:
            parts.append(f"({extra})")
        return " && ".join(parts) if parts else "0"

    def _add_transition(
        self,
        node: Node,
        seq: list[str],
        msgs: list[str],
        produce: list[str],
        extra: str = "",
        label: str = "",
        ends: bool = False,
        all_seq: bool = False,
        behavior: list[Line] | None = None,
    ) -> None:
        self._transitions.append(
            Transition(
                label or node.id,
                self._enable(seq, msgs, extra, all_seq),
                seq + msgs,
                produce,
                _ended(self._process_id) if ends else "",
                behavior,
            )
        )

    def _visit_plain(
        self,
        node: Node,
        own_place: bool = False,
        all_seq: bool = False,
        behavior: list[Line] | None = None,
    ) -> None:
        seq, msgs = self._consume_places(node)
        if own_place:
            seq = [self._add_place(_place(node.id), initial=True)] + seq
        elif not (seq or msgs):
            seq = [self._add_place(_place(node.id))]
        self._add_transition(
            node,
            seq,
            msgs,
            self._produce_places(node),
            ends=isinstance(node, EndEvent),
            all_seq=all_seq,
            behavior=behavior,
        )

    def _task_behavior(self, task: Task) -> list[Line]:
        """The C for the task's behavior, ending with the CWP update."""
        if not task.behavior.strip():
            return []
        try:
            lines = _BehaviorTranslator(task.behavior).translate()
        except _BehaviorError:
            self._unsupported(task, "task behavior")
            return []
        return lines + [(f"{UPDATE_FUNCTION}();", IndentAction.NIL)]

    def _first_visit(self, node: Node) -> bool:
        if node.id in self._seen:
            return False
        self._seen.add(node.id)
        return True

    ####################
    # Output
    ####################

    @property
    def transition_count(self) -> int:
        return len(self._transitions)

    @property
    def all_ended(self) -> str:
        if not self._processes:
            return "1"
        return " && ".join(_ended(p) for p in self._processes)

    @property
    def defs(self) -> StringManager:
        sm = StringManager()
        sm.write_str(DEFS_STR, NL_DOUBLE)
        for name in self._places:
            sm.write_str(f"bool {name} = 0;", NL_SINGLE)
        for process_id in self._processes:
            sm.write_str(f"bool {_ended(process_id)} = 0;", NL_SINGLE)
        return sm

    @property
    def init(self) -> StringManager:
        sm = StringManager()
        for name, initial in self._places.items():
            if initial:
                sm.write_str(f"{name} = 1;", NL_SINGLE)
        return sm

    @property
    def step(self) -> StringManager:
        sm = StringManager()
        sm.write_str("{", NL_SINGLE, IndentAction.INC)
        sm.write_str("unsigned int transition = nondet_uint();", NL_SINGLE)
        sm.write_str("bool occupied = 0;", NL_SINGLE)
        sm.write_str("switch (transition) {", NL_SINGLE, IndentAction.INC)
        for index, t in enumerate(self._transitions):
            sm.write_str(f"case {index}: /* {t.label} */", NL_SINGLE, IndentAction.INC)
            sm.write_str(f"__CPROVER_assume({t.enable});", NL_SINGLE)
            for place in t.consume:
                sm.write_str(f"{place} = 0;", NL_SINGLE)
            for text, action in t.behavior:
                sm.write_str(text, NL_SINGLE, action)
            if t.produce:
                sm.write_str(f"occupied = {' || '.join(t.produce)};", NL_SINGLE)
            for place in t.produce:
                sm.write_str(f"{place} = 1;", NL_SINGLE)
            if t.ends:
                sm.write_str(f"{t.ends} = 1;", NL_SINGLE)
            sm.write_str("break;", NL_SINGLE, IndentAction.DEC)
        sm.write_str("default:", NL_SINGLE, IndentAction.INC)
        sm.write_str("__CPROVER_assume(0);", NL_SINGLE, IndentAction.DEC)
        sm.write_str("}", NL_SINGLE, IndentAction.DEC)
        sm.write_str(f'__CPROVER_assert(!occupied, "{OCCUPIED_MSG}");', NL_SINGLE)
        sm.write_str("}", NL_SINGLE, IndentAction.DEC)
        return sm

    def __repr__(self) -> str:
        return f"{self.defs}{self.step}"

    ####################
    # Visitor Methods
    ####################

    def visit_start_event(self, event: StartEvent) -> bool:
        if self._first_visit(event):
            self._visit_plain(event, own_place=True)
        return True

    def visit_end_event(self, event: EndEvent) -> bool:
        if self._first_visit(event):
            self._visit_plain(event)
        return True

    def visit_intermediate_event(self, event: IntermediateEvent) -> bool:
        if self._first_visit(event):
            self._visit_plain(event)
        return True

    def visit_task(self, task: Task) -> bool:
        if self._first_visit(task):
            self._visit_plain(task, behavior=self._task_behavior(task))
            for boundary_event in task.msg_boundary_events:
                self._unsupported(boundary_event, "boundary event")
        return True

    def visit_boundary_event(self, boundary_event: Task.BoundaryEvent) -> bool:
        # Reported by visit_task; nothing is generated for it.
        return False

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        if not self._first_visit(gateway):
            return True
        seq, msgs = self._consume_places(gateway)
        for flow in gateway.out_flows:
            if not flow.expression:
                self._unsupported(gateway, "exclusive gateway flow without condition")
                continue
            self._add_transition(
                gateway,
                seq,
                msgs,
                [self._add_place(_place(flow.id))],
                extra=flow.expression.replace("\n", " "),
                label=f"{gateway.id} -> {flow.id}",
            )
        return True

    def visit_parallel_gateway(self, gateway: ParallelGatewayNode) -> bool:
        if self._first_visit(gateway):
            # A fork starts when any incoming flow has a token, since a loop
            # can come back into it; a join waits for every incoming flow.
            self._visit_plain(gateway, all_seq=not gateway.is_fork)
        return True

    def visit_process(self, process: Process) -> bool:
        self._process_id = process.id
        self._processes.append(process.id)
        return True

    def end_visit_bpmn(self, bpmn: Bpmn) -> None:
        # Message flows are places even if only one end of them was visited.
        for msg in bpmn.inter_process_msgs.values():
            self._add_place(_place(msg.id))
