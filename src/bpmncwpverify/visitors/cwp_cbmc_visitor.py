from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState, CwpVisitor
from bpmncwpverify.util.stringmanager import (
    NL_DOUBLE,
    NL_SINGLE,
    IndentAction,
    StringManager,
)

START_STR = "//**********CWP VARIABLE DECLARATION************//"
END_STR = "//**********************************************//"
STATE_VAR = "cwp_state"
STATE_PREFIX = "CWP_STATE_"
PRIME_SUFFIX = "_prime"
CALCULATE_FUNC = "cwp_calculate_state"
UPDATE_FUNC = "cwp_update_state"


def _state_const(state: CwpState) -> str:
    return f"{STATE_PREFIX}{state.name}"


def _prime(state: CwpState) -> str:
    return f"{state.name}{PRIME_SUFFIX}"


def _edge_expr(edge: CwpEdge) -> str:
    return f"({edge.expression})" if edge.expression.strip() else "1"


class CwpCbmcVisitor(CwpVisitor):
    """
    Generates C for a CWP. The output is meant to be placed after the
    declarations of the state variables (the edge expressions use them) and
    needs <assert.h>. It provides:

    - enum cwp_state_id and `cwp_state`, the current CWP state
    - cwp_calculate_state(): sets `cwp_state` from the current variable values.
      Call it once, before the first workflow step
    - cwp_update_state(): call after a task whose behavior changed a variable.
      It asserts that exactly one state is active and that the move from
      `cwp_state` is either staying put or following an out edge, then moves
    """

    __slots__ = [
        "states",
        "cwp_states",
        "update_state_func",
        "calculate_state_func",
    ]

    def __init__(self) -> None:
        self.states: list[CwpState] = []
        self.cwp_states = StringManager()
        self.update_state_func = StringManager()
        self.calculate_state_func = StringManager()

    @staticmethod
    def _build_mapping_function(state: CwpState) -> str:
        """The state is active when all in edges hold and no out edge does."""
        ins = " && ".join(_edge_expr(e) for e in state.in_edges) or "1"
        outs = " || ".join(_edge_expr(e) for e in state.out_edges) or "0"
        return f"({ins}) && !({outs})"

    @staticmethod
    def _build_valid_move(state: CwpState) -> str:
        """A move from state is valid if it stays or follows an out edge."""
        dests = [_prime(state)]
        for edge in state.out_edges:
            if _prime(edge.dest) not in dests:
                dests.append(_prime(edge.dest))
        return f"{STATE_VAR} == {_state_const(state)} ? ({' || '.join(dests)})"

    def visit_state(self, state: CwpState) -> bool:
        self.states.append(state)
        return True

    def end_visit_state(self, state: CwpState) -> None:
        pass

    def visit_edge(self, edge: CwpEdge) -> bool:
        return True

    def end_visit_edge(self, edge: CwpEdge) -> None:
        pass

    def visit_cwp(self, model: Cwp) -> bool:
        self.cwp_states.write_str(START_STR, NL_SINGLE)
        return True

    def _create_declarations(self) -> None:
        sm = self.cwp_states
        sm.write_str("enum cwp_state_id {", NL_SINGLE, IndentAction.INC)
        for state in self.states:
            sm.write_str(f"{_state_const(state)},", NL_SINGLE)
        sm.write_str("};", NL_SINGLE, IndentAction.DEC)
        first = _state_const(self.states[0]) if self.states else "0"
        sm.write_str(f"static enum cwp_state_id {STATE_VAR} = {first};", NL_SINGLE)
        sm.write_str(END_STR, NL_DOUBLE)

    def _write_primes(self, sm: StringManager) -> None:
        for state in self.states:
            sm.write_str(
                f"_Bool {_prime(state)} = {self._build_mapping_function(state)};",
                NL_SINGLE,
            )

    def _write_state_sum(self, sm: StringManager, message: str) -> None:
        total = " + ".join(_prime(s) for s in self.states) or "0"
        sm.write_str(
            "// Properties 1 & 2: always in one state and only one state", NL_SINGLE
        )
        sm.write_str(f"int cwp_active_states = {total};", NL_SINGLE)
        sm.write_str(f'assert(cwp_active_states == 1 && "{message}");', NL_SINGLE)

    def _write_assign(self, sm: StringManager) -> None:
        for i, state in enumerate(self.states):
            keyword = "if" if i == 0 else "else if"
            sm.write_str(
                f"{keyword} ({_prime(state)}) {STATE_VAR} = {_state_const(state)};",
                NL_SINGLE,
            )

    def create_update_state_func(self) -> None:
        sm = self.update_state_func
        sm.write_str(f"static void {UPDATE_FUNC}(void) {{", NL_SINGLE, IndentAction.INC)
        self._write_primes(sm)
        self._write_state_sum(sm, "In more than one or no state")
        sm.write_str(
            "// Property 3: every move is staying put or following an edge", NL_SINGLE
        )
        moves = "".join(f"{self._build_valid_move(s)} : " for s in self.states)
        sm.write_str(
            f'assert(({moves}0) && "Not a valid CWP transition");',
            NL_SINGLE,
        )
        self._write_assign(sm)
        sm.write_str("}", NL_DOUBLE, IndentAction.DEC)

    def create_calculate_state_func(self) -> None:
        sm = self.calculate_state_func
        sm.write_str(
            f"static void {CALCULATE_FUNC}(void) {{", NL_SINGLE, IndentAction.INC
        )
        self._write_primes(sm)
        self._write_state_sum(sm, "Initial values are in more than one or no state")
        self._write_assign(sm)
        sm.write_str("}", NL_DOUBLE, IndentAction.DEC)

    def end_visit_cwp(self, model: Cwp) -> None:
        self._create_declarations()
        self.create_update_state_func()
        self.create_calculate_state_func()

    def __repr__(self) -> str:
        return f"{self.cwp_states}{self.update_state_func}{self.calculate_state_func}"
