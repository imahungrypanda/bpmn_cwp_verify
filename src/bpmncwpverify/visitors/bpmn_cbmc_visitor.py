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
from bpmncwpverify.core.error import BpmnCbmcUnsupportedError, Error
from bpmncwpverify.util.stringmanager import IndentAction, StringManager

##############
# Constants
##############
NL_NONE = 0
NL_SINGLE = 1
NL_DOUBLE = 2

HEADER_STR = "#include <stdbool.h>\n\nint nondet_int(void);\n"
COLLISION_FLAG = "token_collision"
CHOICE_VAR = "transition_choice"
##############


def _ident(element_id: str) -> str:
    return re.sub(r"\W", "_", element_id)


def _place(element_id: str) -> str:
    return f"tok_{_ident(element_id)}"


def _ended(process_id: str) -> str:
    return f"ended_{_ident(process_id)}"


class Transition:
    """
    One step of the workflow: when `enable` holds, the transition can be picked
    and `body` runs. `enable` is a C expression, `body` is a list of C statements.
    """

    __slots__ = ["index", "label", "enable", "body"]

    def __init__(self, index: int, label: str, enable: str, body: list[str]) -> None:
        self.index = index
        self.label = label
        self.enable = enable
        self.body = body

    @property
    def enable_name(self) -> str:
        return f"enabled_{self.index}"

    @property
    def fire_name(self) -> str:
        return f"fire_{self.index}"


class CbmcBpmnVisitor(BpmnVisitor):
    """
    Turns a BPMN model into the pieces of the C program that CBMC checks:

    - `declarations`: the headers, the token places, the per-process ended flags,
      and one `enabled_N()` and one `fire_N()` function per transition. It reads the
      variables the expressions on exclusive gateway flows mention, so it has to be
      placed after the declarations of those variables.
    - `step`: the statements for one pass of the main loop. It picks one transition
      with a nondeterministic choice, assumes it is enabled, and fires it. Nothing
      in it loops over the transitions.
    - `all_ended`: a C expression that is true when every process has ended.
    - `num_transitions`: the number of transitions.

    Call `result()` after the visitor has traversed the Bpmn. It is a Failure if an
    element could not be expressed in C.
    """

    __slots__ = [
        "_places",
        "_processes",
        "_process",
        "_seen",
        "_transitions",
        "_errors",
        "declarations",
        "step",
    ]

    def __init__(self) -> None:
        self._places: dict[str, bool] = {}  # place name -> initial token
        self._processes: list[str] = []
        self._process: str = ""
        self._seen: set[str] = set()
        self._transitions: list[Transition] = []
        self._errors: list[Error] = []
        self.declarations = StringManager()
        self.step = StringManager()

    ####################
    # Helpers
    ####################

    @property
    def num_transitions(self) -> int:
        return len(self._transitions)

    @property
    def all_ended(self) -> str:
        if not self._processes:
            return "true"
        return " && ".join(_ended(p) for p in self._processes)

    def result(self) -> Result["CbmcBpmnVisitor", Error]:
        if self._errors:
            return Failure(self._errors[0])
        return Success(self)

    def _unsupported(self, element: Node, reason: str) -> bool:
        self._errors.append(BpmnCbmcUnsupportedError(element.id, reason))
        return False

    def _declare(self, place: str, initial: bool = False) -> str:
        self._places[place] = self._places.get(place, False) or initial
        return place

    def _in_places(self, element: Node) -> tuple[list[str], list[str]]:
        """
        Returns the (in process, message) places a node consumes from. A start event
        has a place of its own that holds its initial token.
        """
        if isinstance(element, StartEvent):
            seq = [self._declare(_place(element.id), initial=True)]
        else:
            seq = [self._declare(_place(f.id)) for f in element.in_flows]
        msgs = [self._declare(_place(m.id)) for m in element.in_msgs]
        return seq, msgs

    def _out_places(self, element: Node) -> list[str]:
        return [
            self._declare(_place(f.id)) for f in element.out_flows + element.out_msgs
        ]

    def _enable(self, seq: list[str], msgs: list[str], extra: str = "") -> str:
        terms = [f"!{_ended(self._process)}"]
        if seq:
            terms.append("(" + " || ".join(seq) + ")")
        if msgs:
            terms.append("(" + " && ".join(msgs) + ")")
        if extra:
            terms.append(f"({extra})")
        return " && ".join(terms)

    def _add_transition(self, label: str, enable: str, body: list[str]) -> None:
        self._transitions.append(
            Transition(len(self._transitions), label, enable, body)
        )

    def _behavior(self, task: Task) -> list[str]:
        """Statements for what a task does to the variables."""
        return []

    def _put_tokens(self, places: list[str]) -> list[str]:
        """
        Sets the places. Whether any of them is already occupied is recorded in one
        assignment, and checked once at the end of the pass.
        """
        if not places:
            return []
        return [f"{COLLISION_FLAG} = {' || '.join(places)};"] + [
            f"{p} = true;" for p in places
        ]

    def _simple_node(self, element: Node, kind: str, end: bool = False) -> bool:
        if element.id in self._seen:
            return False
        self._seen.add(element.id)

        seq, msgs = self._in_places(element)
        if not (seq or msgs):
            return self._unsupported(element, f"{kind} has no incoming flow")

        body = [f"{p} = false;" for p in seq + msgs]
        if isinstance(element, Task):
            body += self._behavior(element)
        body += self._put_tokens(self._out_places(element))
        if end:
            body.append(f"{_ended(self._process)} = true;")
        self._add_transition(f"{kind} {element.id}", self._enable(seq, msgs), body)
        return True

    ####################
    # Visitor Methods
    ####################

    def visit_start_event(self, event: StartEvent) -> bool:
        return self._simple_node(event, "start event")

    def visit_end_event(self, event: EndEvent) -> bool:
        return self._simple_node(event, "end event", end=True)

    def visit_intermediate_event(self, event: IntermediateEvent) -> bool:
        return self._simple_node(event, "intermediate event")

    def visit_task(self, task: Task) -> bool:
        if task.msg_boundary_events:
            self._seen.add(task.id)
            return self._unsupported(task, "tasks with boundary events")
        return self._simple_node(task, "task")

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        if gateway.id in self._seen:
            return False
        self._seen.add(gateway.id)

        seq, msgs = self._in_places(gateway)
        if not seq or msgs or gateway.out_msgs:
            return self._unsupported(
                gateway, "exclusive gateway needs incoming flows and no messages"
            )
        if not gateway.out_flows:
            return self._unsupported(gateway, "exclusive gateway has no outgoing flow")

        exprs: list[str] = []
        for flow in gateway.out_flows:
            expr = flow.expression.replace("\n", " ").strip()
            if not expr:
                return self._unsupported(
                    gateway, f"outgoing flow {flow.id} has no condition"
                )
            exprs.append(expr)

        clear = [f"{p} = false;" for p in seq]
        for flow, expr in zip(gateway.out_flows, exprs):
            self._add_transition(
                f"exclusive gateway {gateway.id} to {flow.id}",
                self._enable(seq, msgs, expr),
                clear + self._put_tokens([self._declare(_place(flow.id))]),
            )
        # SPIN asserts when no flow can be taken, so this does too.
        none_true = "!(" + " || ".join(f"({e})" for e in exprs) + ")"
        self._add_transition(
            f"exclusive gateway {gateway.id} has no viable path",
            self._enable(seq, msgs, none_true),
            [f'__CPROVER_assert(false, "No viable path to take at {gateway.id}");'],
        )
        return True

    def visit_parallel_gateway(self, gateway: ParallelGatewayNode) -> bool:
        self._seen.add(gateway.id)
        return self._unsupported(gateway, "parallel gateways")

    def visit_message_flow(self, flow: MessageFlow) -> bool:
        return True

    def visit_process(self, process: Process) -> bool:
        self._process = process.id
        self._processes.append(process.id)
        return True

    def end_visit_bpmn(self, bpmn: Bpmn) -> None:
        self._render_declarations()
        self._render_step()

    ####################
    # Rendering
    ####################

    def _render_declarations(self) -> None:
        d = self.declarations
        d.write_str(HEADER_STR, NL_SINGLE)
        for place, initial in self._places.items():
            d.write_str(f"bool {place} = {'true' if initial else 'false'};", NL_SINGLE)
        for process in self._processes:
            d.write_str(f"bool {_ended(process)} = false;", NL_SINGLE)
        d.write_str(f"bool {COLLISION_FLAG} = false;", NL_DOUBLE)

        for t in self._transitions:
            d.write_str(f"/* {t.label} */", NL_SINGLE)
            d.write_str(f"static bool {t.enable_name}(void) {{", NL_SINGLE)
            d.write_str(f"\treturn {t.enable};", NL_SINGLE)
            d.write_str("}", NL_SINGLE)
            d.write_str(f"static void {t.fire_name}(void) {{", NL_SINGLE)
            for stmt in t.body:
                d.write_str(f"\t{stmt}", NL_SINGLE)
            d.write_str("}", NL_DOUBLE)

    def _render_step(self) -> None:
        s = self.step
        s.write_str(f"int {CHOICE_VAR} = nondet_int();", NL_SINGLE)
        s.write_str(
            f"__CPROVER_assume({CHOICE_VAR} >= 0 && {CHOICE_VAR} < {len(self._transitions)});",
            NL_SINGLE,
        )
        s.write_str(f"{COLLISION_FLAG} = false;", NL_SINGLE)
        s.write_str(f"switch ({CHOICE_VAR}) {{", NL_SINGLE)
        for t in self._transitions:
            s.write_str(f"case {t.index}: /* {t.label} */", NL_SINGLE, IndentAction.INC)
            s.write_str(f"__CPROVER_assume({t.enable_name}());", NL_SINGLE)
            s.write_str(f"{t.fire_name}();", NL_SINGLE)
            s.write_str("break;", NL_SINGLE, IndentAction.DEC)
        s.write_str("default:", NL_SINGLE, IndentAction.INC)
        s.write_str("__CPROVER_assume(false);", NL_SINGLE)
        s.write_str("break;", NL_SINGLE, IndentAction.DEC)
        s.write_str("}", NL_SINGLE)
        s.write_str(
            f'__CPROVER_assert(!{COLLISION_FLAG}, "Attempting to place token in already-occupied place");',
            NL_SINGLE,
        )
