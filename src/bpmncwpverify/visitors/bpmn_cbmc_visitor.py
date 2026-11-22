import re

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
from bpmncwpverify.core.error import BpmnCbmcUnsupportedElementError
from bpmncwpverify.util.stringmanager import IndentAction, StringManager
from bpmncwpverify.visitors.cwp_cbmc_visitor import UPDATE_FUNC

##############
# Constants
##############
DEFS_HEADER_STR = "#include <stdbool.h>\n\nunsigned int nondet_uint(void);\n\n"
OCCUPIED_MSG = "Attempting to place token in already-occupied place"
NL_NONE = 0
NL_SINGLE = 1
NL_DOUBLE = 2

_C_IDENTIFIER_TAIL = re.compile(r"\w+", re.ASCII)


class Transition:
    """
    One step the workflow can take: an element, or one outgoing flow of an
    exclusive gateway. `enabled` is a C expression, `body` is a list of C
    statements that run once the transition is chosen.
    """

    __slots__ = ["label", "enabled", "body"]

    def __init__(self, label: str, enabled: str, body: list[str]) -> None:
        self.label = label
        self.enabled = enabled
        self.body = body


class CbmcBpmnGenVisitor(BpmnVisitor):
    """
    Generates the BPMN half of the C program. The pieces are kept apart so the
    builder can place them:

    - `defs`: includes and the global token places and end flags
    - `init`: statements that put a token on every start event
    - `step`: statements for ONE pass of the main loop: pick a transition,
      assume it's enabled, run it. It contains no loop over the transitions.
    - `all_ended`: C expression that is true once every process has ended
    """

    __slots__ = [
        "defs",
        "init",
        "step",
        "transitions",
        "_places",
        "_ended_flags",
        "_start_places",
        "_visited",
        "_process_id",
        "_step_built",
        "_choice_count",
    ]

    def __init__(self) -> None:
        self.defs = StringManager()
        self.init = StringManager()
        self.step = StringManager()
        self.transitions: list[Transition] = []
        self._places: list[str] = []
        self._ended_flags: list[str] = []
        self._start_places: list[str] = []
        self._visited: set[str] = set()
        self._process_id = ""
        self._step_built = False
        self._choice_count = 0

    @property
    def all_ended(self) -> str:
        if not self._ended_flags:
            return "true"
        return " && ".join(self._ended_flags)

    ####################
    # Helpers
    ####################

    def _unsupported(
        self, element_id: str, reason: str
    ) -> BpmnCbmcUnsupportedElementError:
        return BpmnCbmcUnsupportedElementError(element_id, reason)

    def _name(self, prefix: str, element_id: str) -> str:
        if not _C_IDENTIFIER_TAIL.fullmatch(element_id):
            raise Exception(
                self._unsupported(
                    element_id, "its id is not usable as part of a C identifier"
                )
            )
        return f"{prefix}_{element_id}"

    def _place(self, prefix: str, element_id: str) -> str:
        name = self._name(prefix, element_id)
        if name not in self._places:
            self._places.append(name)
            self.defs.write_str(f"static bool {name} = false;", NL_SINGLE)
        return name

    def _seq_in_places(self, node: Node) -> list[str]:
        if isinstance(node, StartEvent):
            return [self._place("tok", node.id)]
        return [self._place("tok", flow.id) for flow in node.in_flows]

    def _msg_in_places(self, node: Node) -> list[str]:
        return [self._place("msg", msg.id) for msg in node.in_msgs]

    def _consume_places(self, node: Node) -> list[str]:
        return self._seq_in_places(node) + self._msg_in_places(node)

    def _enable_expr(
        self, node: Node, extra: str = "", require_all: bool = False
    ) -> str:
        """
        Enable condition: a token on any incoming place (or on every one, for a
        join; or the start event's own place), a token on every incoming
        message place, and for an exclusive gateway's flow, the flow's
        condition.
        """
        parts: list[str] = []
        seq = self._seq_in_places(node)
        msgs = self._msg_in_places(node)
        if seq:
            joiner = " && " if require_all else " || "
            parts.append("(" + joiner.join(seq) + ")")
        if msgs:
            parts.append("(" + " && ".join(msgs) + ")")
        if not parts:
            raise Exception(
                self._unsupported(
                    node.id, "it has no incoming flow, so it can't be enabled"
                )
            )
        if extra:
            parts.append(f"({extra})")
        return " && ".join(parts)

    def _behavior(self, task: Task) -> list[str]:
        """
        Statements for a task's behavior, followed by the CWP update. The
        behavior is Promela-style: assignments, and `if :: guard -> ... fi`
        blocks that nondeterministically pick one option whose guard holds.
        """
        lines = [
            part.strip()
            for line in task.behavior.split("\n")
            for part in line.split(";")
            if part.strip()
        ]
        if not lines:
            return []
        self._choice_count = 0
        stmts, index = self._parse_block(task.id, lines, 0)
        if index < len(lines):
            raise Exception(
                self._unsupported(task.id, f"unexpected '{lines[index]}' in behavior")
            )
        return ["{", *stmts, f"{UPDATE_FUNC}();", "}"]

    def _parse_block(
        self, task_id: str, lines: list[str], index: int
    ) -> tuple[list[str], int]:
        """Translate lines until an option (`::`), `fi`, or the end."""
        out: list[str] = []
        while index < len(lines):
            line = lines[index]
            if line == "fi" or line.startswith("::"):
                break
            index += 1
            if line == "if":
                stmts, index = self._parse_if(task_id, lines, index)
                out += stmts
            elif line == "skip":
                continue
            elif line.startswith("assert(") or line.startswith("assert "):
                cond = line[len("assert") :].strip()
                out.append(f'__CPROVER_assert({cond}, "behavior of {task_id}");')
            else:
                out.append(f"{line};")
        return out, index

    def _parse_if(
        self, task_id: str, lines: list[str], index: int
    ) -> tuple[list[str], int]:
        options: list[tuple[str, list[str]]] = []
        while index < len(lines) and lines[index].startswith("::"):
            head = lines[index][2:]
            index += 1
            if "->" not in head:
                raise Exception(
                    self._unsupported(task_id, f"option '{head.strip()}' has no '->'")
                )
            guard, rest = head.split("->", 1)
            guard = guard.strip()
            if rest.strip():
                # the option's first statement is on the same line
                index -= 1
                lines[index] = rest.strip()
            body, index = self._parse_block(task_id, lines, index)
            options.append((guard, body))
        if index >= len(lines) or lines[index] != "fi" or not options:
            raise Exception(
                self._unsupported(task_id, "malformed if ... fi in behavior")
            )
        index += 1
        return self._choose(options), index

    def _choose(self, options: list[tuple[str, list[str]]]) -> list[str]:
        name = f"choice_{self._choice_count}"
        self._choice_count += 1
        others = [f"({g})" for g, _ in options if g != "else"]
        out = ["{", f"unsigned int {name} = nondet_uint();"]
        out.append(f"__CPROVER_assume({name} < {len(options)}u);")
        out.append(f"switch ({name}) {{")
        for i, (guard, body) in enumerate(options):
            cond = f"!({' || '.join(others)})" if guard == "else" else f"({guard})"
            if guard == "else" and not others:
                cond = "true"
            out.append(f"case {i}:")
            out.append(f"__CPROVER_assume({cond});")
            out += body
            out.append("break;")
        out += ["}", "}"]
        return out

    def _add_transition(
        self,
        node: Node,
        label: str,
        out_places: list[str],
        extra_enable: str = "",
        behavior: list[str] | None = None,
        end_flag: str = "",
        require_all: bool = False,
    ) -> None:
        body = [f"{place} = false;" for place in self._consume_places(node)]
        body += behavior or []
        if out_places:
            body.append(
                f'__CPROVER_assert(!({" || ".join(out_places)}), "{OCCUPIED_MSG}");'
            )
            body += [f"{place} = true;" for place in out_places]
        if end_flag:
            body.append(f"{end_flag} = true;")
        self.transitions.append(
            Transition(label, self._enable_expr(node, extra_enable, require_all), body)
        )

    def _out_places(self, node: Node) -> list[str]:
        return [self._place("tok", flow.id) for flow in node.out_flows] + [
            self._place("msg", msg.id) for msg in node.out_msgs
        ]

    def _first_visit(self, node: Node) -> bool:
        if node.id in self._visited:
            return False
        self._visited.add(node.id)
        return True

    def _build_step(self) -> None:
        self.step = StringManager()
        if not self.transitions:
            self.step.write_str("__CPROVER_assume(false);", NL_SINGLE)
            return
        self.step.write_str("unsigned int transition = nondet_uint();", NL_SINGLE)
        self.step.write_str(
            f"__CPROVER_assume(transition < {len(self.transitions)}u);", NL_SINGLE
        )
        self.step.write_str("switch (transition) {", NL_SINGLE)
        for index, transition in enumerate(self.transitions):
            self.step.write_str(
                f"case {index}: /* {transition.label} */",
                NL_SINGLE,
                IndentAction.INC,
            )
            self.step.write_str(f"__CPROVER_assume({transition.enabled});", NL_SINGLE)
            for stmt in transition.body:
                self.step.write_str(stmt, NL_SINGLE)
            self.step.write_str("break;", NL_SINGLE, IndentAction.DEC)
        self.step.write_str("}", NL_SINGLE)

    def __repr__(self) -> str:
        return f"{self.defs}\n{self.init}\n{self.step}"

    ####################
    # Visitor Methods
    ####################

    def visit_start_event(self, event: StartEvent) -> bool:
        if not self._first_visit(event):
            return False
        place = self._place("tok", event.id)
        if place not in self._start_places:
            self._start_places.append(place)
            self.init.write_str(f"{place} = true;", NL_SINGLE)
        self._add_transition(event, f"start event {event.id}", self._out_places(event))
        return True

    def visit_end_event(self, event: EndEvent) -> bool:
        if not self._first_visit(event):
            return False
        if event.out_flows or event.out_msgs:
            raise Exception(
                self._unsupported(event.id, "an end event can't have outgoing flows")
            )
        self._add_transition(
            event,
            f"end event {event.id}",
            [],
            end_flag=self._name("ended", self._process_id),
        )
        return True

    def visit_intermediate_event(self, event: IntermediateEvent) -> bool:
        if not self._first_visit(event):
            return False
        self._add_transition(
            event, f"intermediate event {event.id}", self._out_places(event)
        )
        return True

    def visit_task(self, task: Task) -> bool:
        if task.msg_boundary_events:
            raise Exception(
                self._unsupported(task.id, "boundary events are not supported")
            )
        if not self._first_visit(task):
            return False
        self._add_transition(
            task,
            f"task {task.id}",
            self._out_places(task),
            behavior=self._behavior(task),
        )
        return True

    def visit_boundary_event(self, boundary_event: Task.BoundaryEvent) -> bool:
        raise Exception(
            self._unsupported(boundary_event.id, "boundary events are not supported")
        )

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        if not self._first_visit(gateway):
            return False
        if gateway.out_msgs or gateway.in_msgs:
            raise Exception(
                self._unsupported(
                    gateway.id, "a gateway can't send or receive messages"
                )
            )
        if not gateway.out_flows:
            raise Exception(
                self._unsupported(
                    gateway.id, "an exclusive gateway has no outgoing flow"
                )
            )
        for flow in gateway.out_flows:
            expression = " ".join(flow.expression.split())
            if not expression and len(gateway.out_flows) > 1:
                raise Exception(
                    self._unsupported(
                        flow.id,
                        "a flow leaving an exclusive gateway with several flows needs a condition",
                    )
                )
            self._add_transition(
                gateway,
                f"exclusive gateway {gateway.id} via flow {flow.id}",
                [self._place("tok", flow.id)],
                extra_enable=expression,
            )
        return True

    def visit_parallel_gateway(self, gateway: ParallelGatewayNode) -> bool:
        if not self._first_visit(gateway):
            return False
        if gateway.out_msgs or gateway.in_msgs:
            raise Exception(
                self._unsupported(
                    gateway.id, "a gateway can't send or receive messages"
                )
            )
        if not gateway.out_flows:
            raise Exception(
                self._unsupported(gateway.id, "a parallel gateway has no outgoing flow")
            )
        # A fork starts every branch and is enabled by any one incoming flow
        # (a loop can come back into it); a join waits for all of them.
        kind = "fork" if gateway.is_fork else "join"
        self._add_transition(
            gateway,
            f"parallel gateway {gateway.id} ({kind})",
            self._out_places(gateway),
            require_all=not gateway.is_fork,
        )
        return True

    def visit_message_flow(self, flow: MessageFlow) -> bool:
        # Message places are created from the nodes at either end of the flow.
        return True

    def visit_process(self, process: Process) -> bool:
        self._process_id = process.id
        flag = self._name("ended", process.id)
        self._ended_flags.append(flag)
        self.defs.write_str(f"static bool {flag} = false;", NL_SINGLE)
        return True

    def end_visit_process(self, process: Process) -> None:
        self._process_id = ""

    def visit_bpmn(self, bpmn: Bpmn) -> bool:
        self.defs.write_str(DEFS_HEADER_STR, NL_NONE)
        return True

    def end_visit_bpmn(self, bpmn: Bpmn) -> None:
        self._build_step()
