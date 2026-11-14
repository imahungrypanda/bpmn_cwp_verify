import re

from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState, CwpVisitor
from bpmncwpverify.util.stringmanager import (
    NL_DOUBLE,
    NL_NONE,
    NL_SINGLE,
    IndentAction,
    StringManager,
)

START_STR = "//**********CWP VARIABLE DECLARATION************//"
END_STR = "//**********************************************//"
STATE_PREFIX = "CWP_"
STATE_VAR = "cwp_state"
NEXT_VAR = "cwp_next_state"


def _c_name(state: CwpState) -> str:
    return re.sub(r"\W", "_", state.name)


def _enum_name(state: CwpState) -> str:
    return f"{STATE_PREFIX}{_c_name(state)}"


def _active_name(state: CwpState) -> str:
    return f"cwp_active_{_c_name(state)}"


def _expression(edge: CwpEdge) -> str:
    return f"({edge.expression})" if edge.expression.strip() else "1"


class CwpCbmcVisitor(CwpVisitor):
    """
    Generates C for a CWP. The generated code assumes the state variables are
    declared before it and provides:

    - `cwp_state`: the current CWP state (an enum value)
    - `cwp_init()`: sets `cwp_state` from the current variable values
    - `cwp_update()`: recomputes the active state from the variable values,
      asserts that exactly one state is active and that the move from the
      previous state is a valid edge (or staying put), then moves to it.
      Call it once after every task that may change a variable.
    """

    __slots__ = [
        "states",
        "_seen",
        "enum_decl",
        "active_flags",
        "sum_expr",
        "select_next",
        "valid_moves",
        "declarations",
        "functions",
    ]

    def __init__(self) -> None:
        self.states: list[CwpState] = []
        self._seen: set[str] = set()
        self.enum_decl = StringManager()
        self.active_flags = StringManager()
        self.sum_expr = StringManager()
        self.select_next = StringManager()
        self.valid_moves = StringManager()
        self.declarations = StringManager()
        self.functions = StringManager()

    def _guard(self, state: CwpState) -> str:
        incoming = (
            " && ".join(_expression(e) for e in state.in_edges)
            if state.in_edges
            else "1"
        )
        outgoing = (
            " || ".join(_expression(e) for e in state.out_edges)
            if state.out_edges
            else "0"
        )
        return f"({incoming}) && !({outgoing})"

    def _build_valid_moves(self, state: CwpState) -> None:
        dests = sorted({_enum_name(e.dest) for e in state.out_edges})
        allowed = " || ".join(
            f"{NEXT_VAR} == {name}" for name in [_enum_name(state), *dests]
        )
        self.valid_moves.write_str(
            f"case {_enum_name(state)}:", NL_SINGLE, IndentAction.INC
        )
        self.valid_moves.write_str(
            f'assert(({allowed}) && "CWP: not a valid CWP transition");',
            NL_SINGLE,
        )
        self.valid_moves.write_str("break;", NL_SINGLE)
        self.valid_moves.write_str("", NL_NONE, IndentAction.DEC)

    def visit_state(self, state: CwpState) -> bool:
        if state.id in self._seen:
            return False
        self._seen.add(state.id)
        self.states.append(state)

        self.active_flags.write_str(
            f"_Bool {_active_name(state)} = {self._guard(state)};", NL_SINGLE
        )
        self.select_next.write_str(
            f"if ({_active_name(state)}) {NEXT_VAR} = {_enum_name(state)};",
            NL_SINGLE,
        )
        self._build_valid_moves(state)
        return True

    def end_visit_state(self, state: CwpState) -> None:
        pass

    def visit_edge(self, edge: CwpEdge) -> bool:
        return True

    def end_visit_edge(self, edge: CwpEdge) -> None:
        pass

    def visit_cwp(self, model: Cwp) -> bool:
        return True

    def _build_enum(self) -> StringManager:
        out = StringManager()
        out.write_str(START_STR, NL_SINGLE)
        out.write_str("#include <assert.h>", NL_DOUBLE)
        out.write_str("typedef enum {", NL_SINGLE, IndentAction.INC)
        out.write_str(
            ",\n\t".join(_enum_name(s) for s in self.states) or STATE_PREFIX + "NONE",
            NL_SINGLE,
        )
        out.write_str("} cwp_state_t;", NL_SINGLE, IndentAction.DEC)
        out.write_str(f"cwp_state_t {STATE_VAR};", NL_SINGLE)
        out.write_str(END_STR, NL_DOUBLE)
        return out

    def _build_functions(self) -> StringManager:
        out = StringManager()
        out.write_str(
            "static cwp_state_t cwp_compute_state(void) {", NL_SINGLE, IndentAction.INC
        )
        out.write_str(self.active_flags)
        total = " + ".join(_active_name(s) for s in self.states) or "0"
        out.write_str(f"int cwp_sum_of_active_states = {total};", NL_SINGLE)
        out.write_str(
            'assert(cwp_sum_of_active_states == 1 && "CWP: not in exactly one state");',
            NL_SINGLE,
        )
        first = _enum_name(self.states[0]) if self.states else "0"
        out.write_str(f"cwp_state_t {NEXT_VAR} = {first};", NL_SINGLE)
        out.write_str(self.select_next)
        out.write_str(f"return {NEXT_VAR};", NL_SINGLE)
        out.write_str("}", NL_DOUBLE, IndentAction.DEC)

        out.write_str("void cwp_init(void) {", NL_SINGLE, IndentAction.INC)
        out.write_str(f"{STATE_VAR} = cwp_compute_state();", NL_SINGLE)
        out.write_str("}", NL_DOUBLE, IndentAction.DEC)

        out.write_str("void cwp_update(void) {", NL_SINGLE, IndentAction.INC)
        out.write_str(f"cwp_state_t {NEXT_VAR} = cwp_compute_state();", NL_SINGLE)
        out.write_str(f"switch ({STATE_VAR}) {{", NL_SINGLE)
        out.write_str(self.valid_moves)
        out.write_str("default:", NL_SINGLE, IndentAction.INC)
        out.write_str('assert(0 && "CWP: invalid current state");', NL_SINGLE)
        out.write_str("break;", NL_SINGLE)
        out.write_str("}", NL_SINGLE, IndentAction.DEC)
        out.write_str(f"{STATE_VAR} = {NEXT_VAR};", NL_SINGLE)
        out.write_str("}", NL_SINGLE, IndentAction.DEC)
        return out

    def end_visit_cwp(self, model: Cwp) -> None:
        self.declarations = self._build_enum()
        self.functions = self._build_functions()

    def __repr__(self) -> str:
        return f"{self.declarations}{self.functions}"
