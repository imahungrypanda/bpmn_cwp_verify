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
ACTIVE_PREFIX = "cwp_active_"
PRIME_PREFIX = "cwp_prime_"
CALCULATE_STATE_FUNC = "cwp_calculate_state"
UPDATE_STATE_FUNC = "cwp_update_state"


def _state_id(state: CwpState) -> str:
    return f"{STATE_PREFIX}{state.name}"


class CwpCbmcVisitor(CwpVisitor):
    """
    Generates C for a CWP. The current CWP state is the int `cwp_state`, which
    holds one of the CWP_STATE_<name> constants.

    - `cwp_calculate_state()` sets `cwp_state` from the current variable
      values. Call it once, before the workflow starts.
    - `cwp_update_state()` moves `cwp_state` after a task changes variables.
      It asserts that exactly one state is active afterwards and that the move
      follows an edge (or stays put).

    Both use the variables of the state file, so the output has to come after
    their declarations. Assertions use `__CPROVER_assert`.
    """

    __slots__ = ["states", "defines", "calculate_state_func", "update_state_func"]

    def __init__(self) -> None:
        self.states: list[CwpState] = []
        self.defines = StringManager()
        self.calculate_state_func = StringManager()
        self.update_state_func = StringManager()

    @staticmethod
    def _build_mapping_function(state: CwpState) -> str:
        """The state is active when all its in edges hold and no out edge does."""
        ins = " && ".join(f"({e.expression})" for e in state.in_edges) or "1"
        outs = " || ".join(f"({e.expression})" for e in state.out_edges) or "0"
        return f"({ins}) && !({outs})"

    def _write_flags(self, sm: StringManager, prefix: str) -> None:
        for state in self.states:
            sm.write_str(
                f"_Bool {prefix}{state.name} = {self._build_mapping_function(state)};",
                NL_SINGLE,
            )

    def _write_sum_check(self, sm: StringManager, prefix: str) -> None:
        sm.write_str(
            "// Verification of properties 1 & 2 (verifying that we are always in one state and only one state)",
            NL_SINGLE,
        )
        total = " + ".join(f"{prefix}{s.name}" for s in self.states) or "0"
        sm.write_str(f"unsigned int cwp_sum = {total};", NL_SINGLE)
        sm.write_str(
            '__CPROVER_assert(cwp_sum == 1, "In more that one or no state");', NL_SINGLE
        )

    def _write_assign(self, sm: StringManager, var: str, prefix: str) -> None:
        """Assign to `var` the id of the active state (-1 if none is)."""
        chain = "".join(f"{prefix}{s.name} ? {_state_id(s)} : " for s in self.states)
        sm.write_str(f"{var} = {chain}-1;", NL_SINGLE)

    def _build_valid_moves(self) -> str:
        """A move is valid if it follows an out edge of the current state or stays put."""
        moves: list[str] = []
        for s in self.states:
            dests = [f"{PRIME_PREFIX}{e.dest.name}" for e in s.out_edges]
            dests.append(f"{PRIME_PREFIX}{s.name}")
            moves.append(f"({STATE_VAR} == {_state_id(s)} && ({' || '.join(dests)}))")
        return " || ".join(moves) or "0"

    def create_calculate_state_func(self) -> None:
        sm = self.calculate_state_func
        sm.write_str(
            f"static void {CALCULATE_STATE_FUNC}(void) {{", NL_SINGLE, IndentAction.INC
        )
        self._write_flags(sm, ACTIVE_PREFIX)
        self._write_sum_check(sm, ACTIVE_PREFIX)
        self._write_assign(sm, STATE_VAR, ACTIVE_PREFIX)
        sm.write_str("}", NL_DOUBLE, IndentAction.DEC)

    def create_update_state_func(self) -> None:
        sm = self.update_state_func
        sm.write_str(
            f"static void {UPDATE_STATE_FUNC}(void) {{", NL_SINGLE, IndentAction.INC
        )
        self._write_flags(sm, PRIME_PREFIX)
        self._write_sum_check(sm, PRIME_PREFIX)
        sm.write_str("int cwp_next;", NL_SINGLE)
        self._write_assign(sm, "cwp_next", PRIME_PREFIX)
        sm.write_str(f"_Bool cwp_valid_move = {self._build_valid_moves()};", NL_SINGLE)
        sm.write_str(
            '__CPROVER_assert(cwp_valid_move, "Not a valid CWP transition");', NL_SINGLE
        )
        sm.write_str(f"{STATE_VAR} = cwp_next;", NL_SINGLE)
        sm.write_str("}", NL_DOUBLE, IndentAction.DEC)

    def visit_state(self, state: CwpState) -> bool:
        if state in self.states:
            return False
        self.states.append(state)
        self.defines.write_str(
            f"#define {_state_id(state)} {len(self.states) - 1}", NL_SINGLE
        )
        return True

    def visit_edge(self, edge: CwpEdge) -> bool:
        return True

    def visit_cwp(self, model: Cwp) -> bool:
        self.defines.write_str(START_STR, NL_SINGLE)
        return True

    def end_visit_cwp(self, model: Cwp) -> None:
        self.defines.write_str(f"int {STATE_VAR};", NL_SINGLE)
        self.defines.write_str(END_STR, NL_DOUBLE)
        self.create_calculate_state_func()
        self.create_update_state_func()

    def __repr__(self) -> str:
        return f"{self.defines}{self.calculate_state_func}{self.update_state_func}"
