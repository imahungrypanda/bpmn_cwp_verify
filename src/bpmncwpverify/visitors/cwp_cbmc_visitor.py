from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState, CwpVisitor
from bpmncwpverify.util.stringmanager import (
    NL_DOUBLE,
    NL_SINGLE,
    IndentAction,
    StringManager,
)

START_STR = "//**********CWP VARIABLE DECLARATION************//"
END_STR = "//**********************************************//"
STATE_PREFIX = "CWP_"
NEXT_PREFIX = "cwp_next_"
STATE_VAR = "cwp_state"
START_ACTIVE_VAR = "cwp_start_active"
CALCULATE_FUNC = "cwp_calculate_state"
UPDATE_FUNC = "cwp_update_state"


def _expr(edges: list[CwpEdge]) -> list[str]:
    return [f"({edge.expression})" if edge.expression else "1" for edge in edges]


class CwpCbmcVisitor(CwpVisitor):
    """
    Generates the C for a CWP. The output needs the state's variables and
    constants declared before it, and is meant to be called from the main loop:

    - `cwp_state` is the current CWP state (`CWP_<name>`).
    - `cwp_calculate_state()` sets `cwp_state` from the initial variable values.
    - `cwp_update_state()` recomputes the state after variables changed and
      asserts that exactly one state is active and that the move is a valid
      CWP edge (or staying put).

    Like the SPIN model, the start state (the one with no incoming edges) is
    only active at the start: it is never recomputed and it can only be left
    along one of its outgoing edges.
    """

    __slots__ = ["states", "_seen", "start_name", "c"]

    def __init__(self) -> None:
        self.states: list[CwpState] = []
        self._seen: set[str] = set()
        self.start_name: str | None = None
        self.c = StringManager()

    @staticmethod
    def _guard(state: CwpState) -> str:
        incoming = " && ".join(_expr(state.in_edges)) or "1"
        outgoing = " || ".join(_expr(state.out_edges)) or "0"
        return f"({incoming}) && !({outgoing})"

    def _declarations(self) -> StringManager:
        out = StringManager()
        out.write_str(START_STR, NL_SINGLE)
        names = ", ".join(f"{STATE_PREFIX}{s.name}" for s in self.states)
        out.write_str(f"enum cwp_state_id {{ {names} }};", NL_SINGLE)
        initial = f"{STATE_PREFIX}{self.start_name}"
        out.write_str(f"static enum cwp_state_id {STATE_VAR} = {initial};", NL_SINGLE)
        out.write_str(f"static _Bool {START_ACTIVE_VAR} = 1;", NL_SINGLE)
        out.write_str(END_STR, NL_DOUBLE)
        return out

    def _moving(self) -> list[CwpState]:
        """States that are computed from the variables (all but the start state)."""
        return [s for s in self.states if s.in_edges]

    def _calculate(self) -> StringManager:
        out = StringManager()
        out.write_str(
            f"static void {CALCULATE_FUNC}(void) {{", NL_SINGLE, IndentAction.INC
        )
        keyword = "if"
        for state in self._moving():
            out.write_str(f"{keyword} ({self._guard(state)})", NL_SINGLE)
            out.write_str(f"\t{STATE_VAR} = {STATE_PREFIX}{state.name};", NL_SINGLE)
            keyword = "else if"
        out.write_str("}", NL_DOUBLE, IndentAction.DEC)
        return out

    def _valid_moves(self) -> list[str]:
        moving = {s.name for s in self._moving()}
        valid: list[str] = []
        for state in self.states:
            dests = sorted({e.dest.name for e in state.out_edges} & moving)
            if state.in_edges:
                # Staying in the same state is always allowed.
                dests.insert(0, state.name)
                current = f"{STATE_VAR} == {STATE_PREFIX}{state.name}"
            else:
                current = START_ACTIVE_VAR
            if dests:
                nxt = " || ".join(f"{NEXT_PREFIX}{d}" for d in dests)
                valid.append(f"({current} && ({nxt}))")
        return valid

    def _update(self) -> StringManager:
        out = StringManager()
        moving = self._moving()

        out.write_str(
            f"static void {UPDATE_FUNC}(void) {{", NL_SINGLE, IndentAction.INC
        )
        for state in moving:
            out.write_str(
                f"_Bool {NEXT_PREFIX}{state.name} = {self._guard(state)};", NL_SINGLE
            )

        # Properties 1 & 2: always in exactly one state.
        total = " + ".join(f"{NEXT_PREFIX}{s.name}" for s in moving) or "0"
        out.write_str(f"int cwp_active_states = {total};", NL_SINGLE)
        out.write_str(
            '__CPROVER_assert(cwp_active_states == 1, "CWP: in more than one or no state");',
            NL_SINGLE,
        )

        # Every move follows an edge (or stays in the same state).
        valid = " || ".join(self._valid_moves()) or "0"
        out.write_str(
            f'__CPROVER_assert({valid}, "CWP: not a valid CWP transition");',
            NL_SINGLE,
        )

        for state in moving:
            out.write_str(
                f"if ({NEXT_PREFIX}{state.name}) {STATE_VAR} = {STATE_PREFIX}{state.name};",
                NL_SINGLE,
            )
        out.write_str(f"{START_ACTIVE_VAR} = 0;", NL_SINGLE)
        out.write_str("}", NL_DOUBLE, IndentAction.DEC)
        return out

    def visit_state(self, state: CwpState) -> bool:
        if state.name in self._seen:
            return False
        self._seen.add(state.name)
        self.states.append(state)
        if not state.in_edges:
            self.start_name = state.name
        return True

    def visit_cwp(self, model: Cwp) -> bool:
        return True

    def end_visit_cwp(self, model: Cwp) -> None:
        if self.start_name is None:
            self.start_name = model.start_state.name
        self.c.write_str(self._declarations())
        self.c.write_str(self._calculate())
        self.c.write_str(self._update())

    def __repr__(self) -> str:
        return str(self.c)
