import re

from returns.result import Failure, Result, Success

from bpmncwpverify.core.bpmn import (
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
from bpmncwpverify.util.stringmanager import (
    NL_DOUBLE,
    NL_SINGLE,
    IndentAction,
    StringManager,
)

START_STR = "//**********BPMN TOKEN DECLARATION************//"
END_STR = "//********************************************//"
OVERFLOW_VAR = "bpmn_overflow"
INIT_FUNC = "bpmn_init"
STEP_FUNC = "bpmn_step"
ALL_DONE_FUNC = "bpmn_all_done"
NONDET_FUNC = "nondet_uint"


def _ident(name: str) -> str:
    """Turns a BPMN id into something that is safe to use in a C identifier."""
    return re.sub(r"\W", "_", name)


def place_name(source_id: str) -> str:
    """Name of the C boolean that holds the token of a flow or start event."""
    return f"tok_{_ident(source_id)}"


def done_name(process_id: str) -> str:
    """Name of the C boolean that is set once a process has reached an end event."""
    return f"done_{_ident(process_id)}"


class _Transition:
    """One thing a pass of the loop can run, with its enable condition and body."""

    __slots__ = ["name", "enable", "body"]

    def __init__(self, name: str, enable: str, body: list[str]) -> None:
        self.name = name
        self.enable = enable
        self.body = body


class BpmnCbmcVisitor(BpmnVisitor):
    """
    Generates C that models how a BPMN runs. Token places are booleans: one per
    start event and one per sequence or message flow. A transition is a start
    event, a task, an end event, an intermediate event, or one outgoing flow of
    an exclusive gateway.

    The output provides:
      - the token places, and `void bpmn_init(void)` that puts a token on every
        start event
      - `bool bpmn_all_done(void)`: true when every process has ended
      - `void bpmn_step(void)`: one pass of the loop. It picks one transition
        with a nondeterministic choice, assumes that it is enabled and runs it:
        clear the incoming places, run the behavior, set the outgoing places.
        Nothing in it loops over the transitions. Tokens landing on occupied
        places are checked with one assertion at the end of the pass.

    Elements that C cannot express (for now parallel gateways and tasks with
    boundary events) are recorded in `errors`, see `result()`.
    """

    __slots__ = [
        "_places",
        "_starts",
        "_transitions",
        "_processes",
        "_process",
        "errors",
    ]

    def __init__(self) -> None:
        self._places: dict[str, None] = {}
        self._starts: list[str] = []
        self._transitions: list[_Transition] = []
        self._processes: list[str] = []
        self._process = ""
        self.errors: list[Error] = []

    @property
    def transition_count(self) -> int:
        return len(self._transitions)

    def result(self) -> Result[str, Error]:
        """The generated C, or the first element that could not be expressed."""
        if self.errors:
            return Failure(self.errors[0])
        return Success(str(self))

    ####################
    # Helpers
    ####################

    def _unsupported(self, element: Node, kind: str) -> None:
        self.errors.append(BpmnCbmcUnsupportedElementError(element.id, kind))

    def _in_places(self, node: Node) -> tuple[list[str], list[str]]:
        """The (sequence, message) places a node consumes from."""
        if not (node.in_flows or node.in_msgs):
            return [place_name(node.id)], []
        return (
            [place_name(f.id) for f in node.in_flows],
            [place_name(m.id) for m in node.in_msgs],
        )

    def _out_places(self, node: Node) -> list[str]:
        return [place_name(f.id) for f in node.out_flows + node.out_msgs]

    def _declare(self, node: Node) -> None:
        seq, msgs = self._in_places(node)
        for place in seq + msgs + self._out_places(node):
            self._places.setdefault(place)

    def _enable(self, node: Node, condition: str = "") -> str:
        """
        Any incoming sequence place has a token, and every incoming message
        place has one, and the flow's condition holds.
        """
        seq, msgs = self._in_places(node)
        parts: list[str] = []
        if seq:
            parts.append("(" + " || ".join(seq) + ")")
        if msgs:
            parts.append("(" + " && ".join(msgs) + ")")
        if condition:
            parts.append(f"({condition})")
        return " && ".join(parts)

    def _body(
        self, node: Node, outs: list[str], extra: list[str] | None = None
    ) -> list[str]:
        seq, msgs = self._in_places(node)
        lines = [f"{place} = false;" for place in seq + msgs]
        lines += extra or []
        if outs:
            lines.append(
                f"{OVERFLOW_VAR} = {OVERFLOW_VAR} || " + " || ".join(outs) + ";"
            )
        lines += [f"{place} = true;" for place in outs]
        return lines

    def _add(self, name: str, enable: str, body: list[str]) -> None:
        name = _ident(name)
        if all(t.name != name for t in self._transitions):
            self._transitions.append(_Transition(name, enable, body))

    def _add_simple(self, node: Node, extra: list[str] | None = None) -> None:
        self._declare(node)
        self._add(
            node.id,
            self._enable(node),
            self._body(node, self._out_places(node), extra),
        )

    ####################
    # Generation
    ####################

    def _build_declarations(self) -> StringManager:
        decl = StringManager()
        decl.write_str("#include <assert.h>", NL_SINGLE)
        decl.write_str("#include <stdbool.h>", NL_DOUBLE)
        decl.write_str(f"unsigned {NONDET_FUNC}(void);", NL_DOUBLE)
        for place in self._places:
            decl.write_str(f"static bool {place};", NL_SINGLE)
        for process in self._processes:
            decl.write_str(f"static bool {done_name(process)};", NL_SINGLE)
        decl.write_str(f"static bool {OVERFLOW_VAR};", NL_DOUBLE)
        return decl

    def _build_init(self) -> StringManager:
        func = StringManager()
        func.write_str(f"static void {INIT_FUNC}(void) {{", NL_SINGLE, IndentAction.INC)
        for place in self._starts:
            func.write_str(f"{place} = true;", NL_SINGLE)
        func.write_str("}", NL_DOUBLE, IndentAction.DEC)
        return func

    def _build_all_done(self) -> StringManager:
        done = " && ".join(done_name(p) for p in self._processes) or "true"
        func = StringManager()
        func.write_str(
            f"static bool {ALL_DONE_FUNC}(void) {{", NL_SINGLE, IndentAction.INC
        )
        func.write_str(f"return {done};", NL_SINGLE)
        func.write_str("}", NL_DOUBLE, IndentAction.DEC)
        return func

    def _build_transitions(self) -> StringManager:
        out = StringManager()
        for t in self._transitions:
            out.write_str(
                f"static bool bpmn_enabled_{t.name}(void) {{",
                NL_SINGLE,
                IndentAction.INC,
            )
            out.write_str(f"return {t.enable};", NL_SINGLE)
            out.write_str("}", NL_DOUBLE, IndentAction.DEC)
            out.write_str(
                f"static void bpmn_fire_{t.name}(void) {{", NL_SINGLE, IndentAction.INC
            )
            for line in t.body:
                out.write_str(line, NL_SINGLE)
            out.write_str("}", NL_DOUBLE, IndentAction.DEC)
        return out

    def _build_step(self) -> StringManager:
        func = StringManager()
        func.write_str(f"static void {STEP_FUNC}(void) {{", NL_SINGLE, IndentAction.INC)
        func.write_str(f"unsigned t = {NONDET_FUNC}();", NL_SINGLE)
        func.write_str(f"__CPROVER_assume(t < {len(self._transitions)}u);", NL_SINGLE)
        func.write_str(f"{OVERFLOW_VAR} = false;", NL_SINGLE)
        func.write_str("switch (t) {", NL_SINGLE)
        for i, t in enumerate(self._transitions):
            func.write_str(f"case {i}: // {t.name}", NL_SINGLE, IndentAction.INC)
            func.write_str(f"__CPROVER_assume(bpmn_enabled_{t.name}());", NL_SINGLE)
            func.write_str(f"bpmn_fire_{t.name}();", NL_SINGLE)
            func.write_str("break;", NL_SINGLE, IndentAction.DEC)
        func.write_str("default:", NL_SINGLE, IndentAction.INC)
        func.write_str("__CPROVER_assume(false);", NL_SINGLE)
        func.write_str("break;", NL_SINGLE, IndentAction.DEC)
        func.write_str("}", NL_SINGLE)
        func.write_str(
            f"assert(!{OVERFLOW_VAR}); // token placed in an already-occupied place",
            NL_SINGLE,
        )
        func.write_str("}", NL_DOUBLE, IndentAction.DEC)
        return func

    def __repr__(self) -> str:
        out = StringManager()
        out.write_str(START_STR, NL_SINGLE)
        out.write_str(self._build_declarations())
        out.write_str(self._build_init())
        out.write_str(self._build_all_done())
        out.write_str(self._build_transitions())
        out.write_str(self._build_step())
        out.write_str(END_STR, NL_DOUBLE)
        return str(out)

    ####################
    # Visitor Methods
    ####################

    def visit_start_event(self, event: StartEvent) -> bool:
        place = place_name(event.id)
        if place not in self._starts:
            self._starts.append(place)
        self._add_simple(event)
        return True

    def visit_end_event(self, event: EndEvent) -> bool:
        self._add_simple(event, [f"{done_name(self._process)} = true;"])
        return True

    def visit_intermediate_event(self, event: IntermediateEvent) -> bool:
        self._add_simple(event)
        return True

    def visit_task(self, task: Task) -> bool:
        if task.msg_boundary_events:
            self._unsupported(task, "Task with boundary events")
        # Placeholder for the task's behavior
        self._add_simple(task, [f"// behavior of {task.id}"])
        return True

    def visit_boundary_event(self, boundary_event: Task.BoundaryEvent) -> bool:
        self._unsupported(boundary_event, "Boundary event")
        return False

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        self._declare(gateway)
        for flow in gateway.out_flows:
            self._add(
                f"{gateway.id}__{flow.id}",
                self._enable(gateway, " ".join(flow.expression.split())),
                self._body(gateway, [place_name(flow.id)]),
            )
        return True

    def visit_parallel_gateway(self, gateway: ParallelGatewayNode) -> bool:
        self._unsupported(gateway, "Parallel gateway")
        return False

    def visit_sequence_flow(self, flow: SequenceFlow) -> bool:
        return True

    def visit_message_flow(self, flow: MessageFlow) -> bool:
        return True

    def visit_process(self, process: Process) -> bool:
        self._process = process.id
        if process.id not in self._processes:
            self._processes.append(process.id)
        return True
