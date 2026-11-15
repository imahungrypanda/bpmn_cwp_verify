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
from bpmncwpverify.visitors.cwp_cbmc_visitor import UPDATE_FUNC

##############
# Constants
##############
NL_NONE = 0
NL_SINGLE = 1
NL_DOUBLE = 2

HEADER_STR = "#include <stdbool.h>\n\nint nondet_int(void);\n"
COLLISION_FLAG = "token_collision"
CHOICE_VAR = "transition_choice"
BEHAVIOR_CHOICE_VAR = "behavior_choice"
##############

_TOKEN_RE = re.compile(
    r"""
    (?P<nl>\n)
  | (?P<ws>[ \t\r]+)
  | (?P<sep>::|->|;)
  | (?P<op>==|!=|<=|>=|&&|\|\||[-+*/%<>!=&|^~])
  | (?P<punct>[(),\[\]])
  | (?P<word>[A-Za-z_]\w*|\d+)
    """,
    re.VERBOSE,
)
_BINARY_OPS = {
    *("==", "!=", "<=", ">=", "&&", "||", "-", "+", "*", "/", "%", "<", ">"),
    *("&", "|", "^"),
}


class BehaviorError(Exception):
    pass


def _tokenize(code: str) -> list[str]:
    code = re.sub(r"/\*.*?\*/|//[^\n]*", " ", code, flags=re.S)
    tokens: list[str] = []
    pos = 0
    while pos < len(code):
        m = _TOKEN_RE.match(code, pos)
        if m is None:
            raise BehaviorError(f"unexpected character {code[pos]!r}")
        pos = m.end()
        if m.lastgroup != "ws":
            tokens.append(m.group())
    return tokens


class _BehaviorTranslator:
    """
    Translates the Promela subset task behaviors are written in into C
    statements: assignments, `skip`, `assert(...)`, and `if :: guard -> ... fi`.
    As in Promela, an `if` runs one of its enabled options, chosen
    nondeterministically; `else` is enabled when no other option is, and an `if`
    with no enabled option blocks, which here prunes the path.
    """

    def __init__(self, code: str, task_id: str, first_choice: int) -> None:
        self._toks = _tokenize(code)
        self._pos = 0
        self._task = task_id
        self.choices = first_choice

    def translate(self) -> list[str]:
        out = self._block(set())
        if self._pos < len(self._toks):
            raise BehaviorError(f"unexpected {self._toks[self._pos]!r}")
        return out

    def _peek(self) -> str | None:
        return self._toks[self._pos] if self._pos < len(self._toks) else None

    def _skip_separators(self) -> None:
        while self._peek() in ("\n", ";"):
            self._pos += 1

    def _expression(self, stops: set[str]) -> str:
        """Reads an expression up to a stop token, or the end of its statement."""
        out: list[str] = []
        depth = 0
        while (tok := self._peek()) is not None:
            if depth == 0 and (tok in stops or tok in (";", "::")):
                break
            if tok == "\n":
                if depth == 0:
                    nxt = self._pos + 1
                    while nxt < len(self._toks) and self._toks[nxt] == "\n":
                        nxt += 1
                    after = self._toks[nxt] if nxt < len(self._toks) else None
                    if (
                        not (out and out[-1] in _BINARY_OPS)
                        and after not in _BINARY_OPS
                    ):
                        break
                self._pos += 1
                continue
            depth += (tok == "(") - (tok == ")")
            if depth < 0:
                raise BehaviorError("unbalanced parentheses")
            out.append(tok)
            self._pos += 1
        if depth or not out:
            raise BehaviorError("missing or unbalanced expression")
        return re.sub(r"([(!]) | (\))", r"\1\2", " ".join(out))

    def _block(self, stops: set[str]) -> list[str]:
        """Statements up to (not including) a stop token."""
        out: list[str] = []
        while True:
            self._skip_separators()
            tok = self._peek()
            if tok is None or tok in stops:
                return out
            out += self._statement()

    def _statement(self) -> list[str]:
        tok = self._peek()
        assert tok is not None
        if tok == "skip":
            self._pos += 1
            return []
        if tok == "if":
            self._pos += 1
            return self._if()
        if tok == "assert":
            self._pos += 1
            expr = self._expression(set())
            if not (expr.startswith("(") and expr.endswith(")")):
                raise BehaviorError("malformed assert")
            msg = f"Behavior assertion failed in {self._task}: {expr}"
            msg = msg.replace("\\", "\\\\").replace('"', '\\"')
            return [f'__CPROVER_assert({expr}, "{msg}");']
        if re.fullmatch(r"[A-Za-z_]\w*", tok) and tok not in ("fi", "do", "od"):
            self._pos += 1
            if self._peek() != "=":
                raise BehaviorError(f"unsupported statement starting at {tok!r}")
            self._pos += 1
            return [f"{tok} = {self._expression(set())};"]
        raise BehaviorError(f"unsupported statement starting at {tok!r}")

    def _if(self) -> list[str]:
        options: list[tuple[str | None, list[str]]] = []  # None guard is `else`
        self._skip_separators()
        while self._peek() == "::":
            self._pos += 1
            if self._peek() == "else":
                self._pos += 1
                guard = None
            else:
                guard = self._expression({"->"})
            if self._peek() == "->":
                self._pos += 1
            options.append((guard, self._block({"::", "fi"})))
            self._skip_separators()
        if self._peek() != "fi" or not options:
            raise BehaviorError("malformed if")
        self._pos += 1

        others = [g for g, _ in options if g is not None]

        def condition(guard: str | None) -> str:
            if guard is None:
                return "!(" + " || ".join(f"({g})" for g in others) + ")"
            return guard

        if len(options) == 1:
            guard, body = options[0]
            if guard is None and not others:
                return body
            return [f"__CPROVER_assume({condition(guard)});"] + body

        var = f"{BEHAVIOR_CHOICE_VAR}_{self.choices}"
        self.choices += 1
        out = ["{", f"\tint {var} = nondet_int();"]
        out.append(f"\t__CPROVER_assume({var} >= 0 && {var} < {len(options)});")
        for i, (guard, body) in enumerate(options):
            keyword = "if" if i == 0 else "else if"
            out.append(f"\t{keyword} ({var} == {i}) {{")
            out.append(f"\t\t__CPROVER_assume({condition(guard)});")
            out += [f"\t\t{line}" for line in body]
            out.append("\t}")
        out.append("}")
        return out


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
        "_choices",
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
        self._choices = 0  # nondeterministic choices made by behaviors so far
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

    def _enable(
        self,
        seq: list[str],
        msgs: list[str],
        extra: str = "",
        need_all: bool = False,
    ) -> str:
        terms = [f"!{_ended(self._process)}"]
        if seq:
            terms.append("(" + (" && " if need_all else " || ").join(seq) + ")")
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
        """
        Statements for what a task does to the variables, ending with the CWP
        update if there is a behavior, as the Promela back end does. The CWP
        visitor's declarations have to come before the BPMN ones.
        """
        try:
            translator = _BehaviorTranslator(task.behavior, task.id, self._choices)
            body = translator.translate()
        except BehaviorError as e:
            self._unsupported(task, f"behavior: {e}")
            return []
        self._choices = translator.choices
        if not task.behavior.strip():
            return []
        return body + [f"{UPDATE_FUNC}();"]

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

    def _simple_node(
        self,
        element: Node,
        kind: str,
        end: bool = False,
        need_all: bool = False,
    ) -> bool:
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
        self._add_transition(
            f"{kind} {element.id}", self._enable(seq, msgs, need_all=need_all), body
        )
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
        # A fork starts on any incoming token, which lets a loop re-enter it. A join
        # waits for a token on every incoming flow.
        return self._simple_node(
            gateway,
            "parallel gateway",
            need_all=not gateway.is_fork,
        )

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
