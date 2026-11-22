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
STATE_VAR = "cwp_state"
STATE_PREFIX = "CWP_STATE_"
UPDATE_FUNC = "cwp_update_state"
CALCULATE_FUNC = "cwp_calculate_state"
ACTIVE_SUFFIX = "_active"
PRIME_SUFFIX = "_prime"


class CwpCbmcVisitor(CwpVisitor):
    """
    Generates C for a CWP. The output needs <stdbool.h> and the state
    variables (which the edge expressions refer to) declared before it.

    - `cwp_state` holds the current CWP state, one of the `CWP_STATE_<name>`
      enum constants.
    - `cwp_calculate_state()` sets `cwp_state` from the current variable
      values. Call it once, before the first step of the workflow.
    - `cwp_update_state()` recomputes the state from the variable values and
      checks that exactly one state is active and that moving to it is either
      staying put or following an out edge of the current state. Call it after
      each task whose behavior changes a variable.

    Both functions use `__CPROVER_assert`, so no `assert.h` is needed.
    """

    __slots__ = [
        "states",
        "cwp_states",
        "calculate_state_func",
        "update_state_func",
        "_seen",
    ]

    def __init__(self) -> None:
        self.states: list[CwpState] = []
        self.cwp_states = StringManager()
        self.calculate_state_func = StringManager()
        self.update_state_func = StringManager()
        self._seen: set[str] = set()

    @staticmethod
    def _guard(state: CwpState) -> str:
        """The state is active when all in edges hold and no out edge does."""
        ins = " && ".join(f"({e.expression})" for e in state.in_edges) or "true"
        outs = " || ".join(f"({e.expression})" for e in state.out_edges) or "false"
        return f"({ins}) && !({outs})"

    @staticmethod
    def _const(state: CwpState) -> str:
        return f"{STATE_PREFIX}{state.name}"

    def _write_select(self, sm: StringManager, suffix: str, target: str) -> None:
        """Writes `target = <constant of the active state>`."""
        for i, state in enumerate(self.states):
            keyword = "if" if i == 0 else "else if"
            sm.write_str(
                f"{keyword} ({state.name}{suffix}) {target} = {self._const(state)};",
                NL_SINGLE,
            )

    def _write_exactly_one(self, sm: StringManager, suffix: str, msg: str) -> None:
        sm.write_str("int cwp_sum_of_active_states = ", NL_NONE)
        sm.write_str(
            " + ".join(f"(int){s.name}{suffix}" for s in self.states) + ";",
            NL_SINGLE,
        )
        sm.write_str(
            f'__CPROVER_assert(cwp_sum_of_active_states == 1, "{msg}");', NL_SINGLE
        )

    def _write_active_vars(self, sm: StringManager, suffix: str) -> None:
        for state in self.states:
            sm.write_str(
                f"bool {state.name}{suffix} = {self._guard(state)};", NL_SINGLE
            )

    def visit_state(self, state: CwpState) -> bool:
        if state.id in self._seen:
            return False
        self._seen.add(state.id)
        self.states.append(state)
        return True

    def visit_edge(self, edge: CwpEdge) -> bool:
        return True

    def visit_cwp(self, model: Cwp) -> bool:
        self.cwp_states.write_str(START_STR, NL_SINGLE)
        return True

    def end_visit_cwp(self, model: Cwp) -> None:
        if not self.states:
            return
        self._create_declarations()
        self._create_calculate_state()
        self._create_update_state()

    def _create_declarations(self) -> None:
        names = ", ".join(self._const(s) for s in self.states)
        self.cwp_states.write_str(f"enum cwp_state_type {{ {names} }};", NL_SINGLE)
        self.cwp_states.write_str(
            f"enum cwp_state_type {STATE_VAR} = {self._const(self.states[0])};",
            NL_SINGLE,
        )
        self.cwp_states.write_str(END_STR, NL_DOUBLE)

    def _create_calculate_state(self) -> None:
        sm = self.calculate_state_func
        sm.write_str(f"void {CALCULATE_FUNC}(void) {{", NL_SINGLE, IndentAction.INC)
        self._write_active_vars(sm, ACTIVE_SUFFIX)
        self._write_exactly_one(
            sm,
            ACTIVE_SUFFIX,
            "CWP: initial values are in more than one or no state",
        )
        self._write_select(sm, ACTIVE_SUFFIX, STATE_VAR)
        sm.write_str("}", NL_DOUBLE, IndentAction.DEC)

    def _create_update_state(self) -> None:
        sm = self.update_state_func
        sm.write_str(f"void {UPDATE_FUNC}(void) {{", NL_SINGLE, IndentAction.INC)
        self._write_active_vars(sm, PRIME_SUFFIX)
        # Properties 1 & 2: always in exactly one state
        self._write_exactly_one(sm, PRIME_SUFFIX, "CWP: in more than one or no state")
        sm.write_str(f"enum cwp_state_type cwp_next = {STATE_VAR};", NL_SINGLE)
        self._write_select(sm, PRIME_SUFFIX, "cwp_next")
        # Only valid moves: stay put or follow an out edge
        sm.write_str("bool cwp_valid_transition = false;", NL_SINGLE)
        sm.write_str(f"switch ({STATE_VAR}) {{", NL_SINGLE, IndentAction.INC)
        for state in self.states:
            dests = [state.name] + [e.dest.name for e in state.out_edges]
            cond = " || ".join(
                f"cwp_next == {STATE_PREFIX}{d}" for d in dict.fromkeys(dests)
            )
            sm.write_str(f"case {self._const(state)}:", NL_SINGLE, IndentAction.INC)
            sm.write_str(f"cwp_valid_transition = {cond};", NL_SINGLE)
            sm.write_str("break;", NL_SINGLE, IndentAction.DEC)
        sm.write_str("default:", NL_SINGLE, IndentAction.INC)
        sm.write_str("break;", NL_SINGLE, IndentAction.DEC)
        sm.write_str("}", NL_SINGLE, IndentAction.DEC)
        sm.write_str(
            '__CPROVER_assert(cwp_valid_transition, "CWP: not a valid CWP transition");',
            NL_SINGLE,
        )
        sm.write_str(f"{STATE_VAR} = cwp_next;", NL_SINGLE)
        sm.write_str("}", NL_DOUBLE, IndentAction.DEC)

    def __repr__(self) -> str:
        return f"{self.cwp_states}{self.calculate_state_func}{self.update_state_func}"
