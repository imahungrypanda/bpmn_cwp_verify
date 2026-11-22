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
STATE_VAR = "cwp_state"
COMPUTE_FUNC = "cwp_compute_state"
INIT_FUNC = "cwp_init"
UPDATE_FUNC = "cwp_update"


def state_const(state: CwpState) -> str:
    """Name of the C constant that stands for `state` in `cwp_state`."""
    return f"{STATE_PREFIX}{state.name}"


def _prime(state: CwpState) -> str:
    return f"{state.name}_prime"


def _cond(edge: CwpEdge) -> str:
    return f"({edge.expression})" if edge.expression.strip() else "true"


class CwpCbmcVisitor(CwpVisitor):
    """
    Generates C for a CWP. The current CWP state is one variable, `cwp_state`,
    so it is in exactly one state by construction. The state a set of variable
    values puts the CWP in is the same as in the SPIN model: all of the state's
    incoming edge expressions hold and none of its outgoing ones do.

    The output needs the workflow's variables declared before it, and it
    provides three things:
      - `void cwp_init(void)`: sets `cwp_state` from the current values
      - `void cwp_update(void)`: moves `cwp_state` after variables changed,
        asserting that it is in exactly one state and that the move is a stay
        or follows an edge
      - `cwp_state` itself
    """

    __slots__ = ["_states", "_start_state"]

    def __init__(self) -> None:
        self._states: dict[str, CwpState] = {}
        self._start_state: CwpState | None = None

    def _state_guard(self, state: CwpState) -> str:
        incoming = " && ".join(_cond(edge) for edge in state.in_edges)
        outgoing = " || ".join(_cond(edge) for edge in state.out_edges) or "false"
        return f"({incoming}) && !({outgoing})"

    def _build_declarations(self) -> StringManager:
        decl = StringManager()
        decl.write_str("#include <assert.h>", NL_SINGLE)
        decl.write_str("#include <stdbool.h>", NL_DOUBLE)
        decl.write_str("enum {", NL_SINGLE, IndentAction.INC)
        for state in self._states.values():
            decl.write_str(f"{state_const(state)},", NL_SINGLE)
        decl.write_str("};", NL_SINGLE, IndentAction.DEC)
        decl.write_str(f"static unsigned {STATE_VAR};", NL_DOUBLE)
        return decl

    def _build_compute(self) -> StringManager:
        # States without incoming edges are only ever the initial state. They
        # have no guard, so they can never be moved back to.
        guarded = [s for s in self._states.values() if s.in_edges]
        func = StringManager()
        func.write_str(
            f"static unsigned {COMPUTE_FUNC}(void) {{", NL_SINGLE, IndentAction.INC
        )
        for state in guarded:
            func.write_str(
                f"bool {_prime(state)} = {self._state_guard(state)};", NL_SINGLE
            )
        func.write_str(
            "// Verification of properties 1 & 2 (verifying that we are always in one state and only one state)",
            NL_SINGLE,
        )
        sum_expr = " + ".join(f"{_prime(s)}" for s in guarded) or "0"
        func.write_str(f"assert(({sum_expr}) == 1);", NL_SINGLE)
        chain = "".join(f"{_prime(s)} ? {state_const(s)} : " for s in guarded) + (
            state_const(guarded[-1]) if guarded else "0"
        )
        func.write_str(f"return {chain};", NL_SINGLE)
        func.write_str("}", NL_DOUBLE, IndentAction.DEC)
        return func

    def _build_init(self) -> StringManager:
        func = StringManager()
        func.write_str(f"static void {INIT_FUNC}(void) {{", NL_SINGLE, IndentAction.INC)
        start = self._start_state
        if start is not None and not start.in_edges:
            func.write_str(f"{STATE_VAR} = {state_const(start)};", NL_SINGLE)
        else:
            func.write_str(f"{STATE_VAR} = {COMPUTE_FUNC}();", NL_SINGLE)
        func.write_str("}", NL_DOUBLE, IndentAction.DEC)
        return func

    def _build_update(self) -> StringManager:
        func = StringManager()
        func.write_str(
            f"static void {UPDATE_FUNC}(void) {{", NL_SINGLE, IndentAction.INC
        )
        func.write_str(f"unsigned next = {COMPUTE_FUNC}();", NL_SINGLE)
        func.write_str(f"switch ({STATE_VAR}) {{", NL_SINGLE)
        for state in self._states.values():
            allowed = [state_const(state)] if state.in_edges else []
            allowed += [state_const(e.dest) for e in state.out_edges]
            cond = " || ".join(f"next == {c}" for c in allowed) or "0"
            func.write_str(f"case {state_const(state)}:", NL_SINGLE, IndentAction.INC)
            func.write_str(f"assert({cond}); // valid CWP transition", NL_SINGLE)
            func.write_str("break;", NL_SINGLE, IndentAction.DEC)
        func.write_str("default:", NL_SINGLE, IndentAction.INC)
        func.write_str("assert(0); // not in a CWP state", NL_SINGLE)
        func.write_str("break;", NL_SINGLE, IndentAction.DEC)
        func.write_str("}", NL_SINGLE)
        func.write_str(f"{STATE_VAR} = next;", NL_SINGLE)
        func.write_str("}", NL_DOUBLE, IndentAction.DEC)
        return func

    def visit_state(self, state: CwpState) -> bool:
        self._states.setdefault(state.name, state)
        return True

    def visit_cwp(self, model: Cwp) -> bool:
        self._start_state = getattr(model, "start_state", None)
        return True

    def end_visit_cwp(self, model: Cwp) -> None:
        pass

    def __repr__(self) -> str:
        out = StringManager()
        out.write_str(START_STR, NL_SINGLE)
        out.write_str(self._build_declarations())
        out.write_str(self._build_compute())
        out.write_str(self._build_init())
        out.write_str(self._build_update())
        out.write_str(END_STR, NL_DOUBLE)
        return str(out)
