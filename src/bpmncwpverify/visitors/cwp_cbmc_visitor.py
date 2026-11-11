import re

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
STATE_TYPE = "cwp_state_t"
STATE_PREFIX = "CWP_STATE_"
INIT_FUNC = "cwp_init"
UPDATE_FUNC = "cwp_update"


def _c_name(state: CwpState) -> str:
    """The C enumerator for a CWP state."""
    return STATE_PREFIX + re.sub(r"\W", "_", state.name)


def _edge_expr(edge: CwpEdge) -> str:
    return f"({edge.expression})" if edge.expression.strip() else "1"


class CwpCbmcVisitor(CwpVisitor):
    """
    Generates C for a CWP. The generated code defines:

    - an enum `cwp_state_t` with one value per CWP state
    - a variable `cwp_state`, the current CWP state
    - `void cwp_init(void)`, which sets `cwp_state` from the variables' current
      values (call it once, after the variables are initialized)
    - `void cwp_update(void)`, which moves `cwp_state` after the variables
      change (call it once after a task whose behavior changes a variable)

    A state is active when all of its incoming edge expressions hold and none of
    its outgoing edge expressions do, as in the Promela back end. Both functions
    assert that exactly one state is active; `cwp_update` also asserts that the
    new state is the current state or the destination of one of its out edges.
    Neither contains a loop. Edge expressions refer to the state's variables by
    name, so those must be declared before this code. It uses `__CPROVER_assert`.
    """

    __slots__ = ["states", "enum_values", "active_checks", "valid_moves"]

    def __init__(self) -> None:
        self.states: dict[str, CwpState] = {}
        self.enum_values = StringManager()
        self.active_checks = StringManager()
        self.valid_moves = StringManager()

    @staticmethod
    def _active_condition(state: CwpState) -> str:
        incoming = " && ".join(_edge_expr(e) for e in state.in_edges) or "1"
        outgoing = " || ".join(_edge_expr(e) for e in state.out_edges) or "0"
        return f"({incoming}) && !({outgoing})"

    def visit_state(self, state: CwpState) -> bool:
        if state.name in self.states:
            return False
        self.states[state.name] = state
        name = _c_name(state)
        self.enum_values.write_str(f"{name},", NL_SINGLE)
        self.active_checks.write_str(
            f"if ({self._active_condition(state)}) {{ active++; next = {name}; }}",
            NL_SINGLE,
        )
        targets = [name] + [_c_name(e.dest) for e in state.out_edges]
        allowed = " || ".join(
            f"next == {t}"
            for t in dict.fromkeys(targets)  # dedupe, keep order
        )
        self.valid_moves.write_str(f"case {name}:", NL_SINGLE, IndentAction.INC)
        self.valid_moves.write_str(f"valid = {allowed};", NL_SINGLE)
        self.valid_moves.write_str("break;", NL_SINGLE, IndentAction.DEC)
        return True

    def visit_edge(self, edge: CwpEdge) -> bool:
        return True

    def visit_cwp(self, model: Cwp) -> bool:
        return True

    def _compute_next(self, out: StringManager) -> None:
        out.write_str(f"{STATE_TYPE} next = {STATE_VAR};", NL_SINGLE)
        out.write_str("int active = 0;", NL_SINGLE)
        out.write_str(self.active_checks)
        out.write_str(
            '__CPROVER_assert(active == 1, "CWP: in more than one state or no state");',
            NL_SINGLE,
        )

    def _build(self) -> StringManager:
        out = StringManager()
        out.write_str(START_STR, NL_SINGLE)
        out.write_str("typedef enum {", NL_SINGLE, IndentAction.INC)
        out.write_str(self.enum_values)
        out.write_str(f"}} {STATE_TYPE};", NL_SINGLE, IndentAction.DEC)
        out.write_str(f"{STATE_TYPE} {STATE_VAR};", NL_DOUBLE)

        out.write_str(f"static void {INIT_FUNC}(void) {{", NL_SINGLE, IndentAction.INC)
        self._compute_next(out)
        out.write_str(f"{STATE_VAR} = next;", NL_SINGLE)
        out.write_str("}", NL_DOUBLE, IndentAction.DEC)

        out.write_str(
            f"static void {UPDATE_FUNC}(void) {{", NL_SINGLE, IndentAction.INC
        )
        self._compute_next(out)
        out.write_str("int valid = 0;", NL_SINGLE)
        out.write_str(f"switch ({STATE_VAR}) {{", NL_SINGLE, IndentAction.INC)
        out.write_str(self.valid_moves)
        out.write_str("}", NL_SINGLE, IndentAction.DEC)
        out.write_str(
            '__CPROVER_assert(valid, "CWP: not a valid CWP transition");', NL_SINGLE
        )
        out.write_str(f"{STATE_VAR} = next;", NL_SINGLE)
        out.write_str("}", NL_SINGLE, IndentAction.DEC)
        out.write_str(END_STR, NL_DOUBLE)
        return out

    def __repr__(self) -> str:
        return str(self._build())
