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
GUARD_PREFIX = "cwp_guard_"
INIT_FUNC = "cwp_init"
UPDATE_FUNC = "cwp_update"


class CwpCbmcVisitor(CwpVisitor):
    """
    Generates C for a CWP. The generated code needs <assert.h> and the C
    declarations of the state variables the edge expressions use.

    The current CWP state is the single int `cwp_state`, holding one of the
    `CWP_STATE_<name>` constants. `cwp_init()` sets it from the current values
    of the variables, and `cwp_update()` moves it after variables change. Both
    assert that exactly one state is active. `cwp_update()` also asserts that
    the move is along an out edge, or stays in the same state.
    """

    __slots__ = [
        "states",
        "declarations",
        "init_function",
        "update_function",
    ]

    def __init__(self) -> None:
        self.states: list[CwpState] = []
        self.declarations = StringManager()
        self.init_function = StringManager()
        self.update_function = StringManager()

    @staticmethod
    def state_const(state: CwpState) -> str:
        return f"{STATE_PREFIX}{state.name}"

    @staticmethod
    def _guard_var(state: CwpState) -> str:
        return f"{GUARD_PREFIX}{state.name}"

    @staticmethod
    def _expr(edge: CwpEdge) -> str:
        return f"({edge.expression})" if edge.expression.strip() else "1"

    def _guard(self, state: CwpState) -> str:
        """
        A state is active when all its in edges hold and none of its out edges do.
        """
        in_expr = " && ".join(self._expr(e) for e in state.in_edges) or "1"
        out_expr = " || ".join(self._expr(e) for e in state.out_edges) or "0"
        return f"({in_expr}) && !({out_expr})"

    def _write_select_state(self, sm: StringManager, target: str) -> None:
        """
        Writes straight line code that finds the active states from the
        variables, asserts there is exactly one, and puts it in `target`.
        """
        for state in self.states:
            sm.write_str(
                f"int {self._guard_var(state)} = {self._guard(state)};", NL_SINGLE
            )
        active = " + ".join(self._guard_var(s) for s in self.states) or "0"
        sm.write_str(f"int cwp_active = {active};", NL_SINGLE)
        sm.write_str(
            'assert(cwp_active == 1 && "In more than one or no CWP state");',
            NL_SINGLE,
        )
        sm.write_str(f"int {target} = 0;", NL_SINGLE)
        for state in self.states:
            sm.write_str(
                f"if ({self._guard_var(state)}) {target} = {self.state_const(state)};",
                NL_SINGLE,
            )

    def _write_declarations(self) -> None:
        sm = self.declarations
        sm.write_str(START_STR, NL_SINGLE)
        sm.write_str("enum {", NL_SINGLE, IndentAction.INC)
        for state in self.states:
            sm.write_str(f"{self.state_const(state)},", NL_SINGLE)
        sm.write_str("};", NL_SINGLE, IndentAction.DEC)
        sm.write_str(f"static int {STATE_VAR} = 0;", NL_SINGLE)
        sm.write_str(f"static void {INIT_FUNC}(void);", NL_SINGLE)
        sm.write_str(f"static void {UPDATE_FUNC}(void);", NL_SINGLE)
        sm.write_str(END_STR, NL_DOUBLE)

    def _write_init(self) -> None:
        sm = self.init_function
        sm.write_str(f"static void {INIT_FUNC}(void) {{", NL_SINGLE, IndentAction.INC)
        self._write_select_state(sm, "cwp_next")
        sm.write_str(f"{STATE_VAR} = cwp_next;", NL_SINGLE)
        sm.write_str("}", NL_DOUBLE, IndentAction.DEC)

    def _write_valid_move(self, sm: StringManager) -> None:
        sm.write_str("int cwp_valid = 0;", NL_SINGLE)
        sm.write_str(f"switch ({STATE_VAR}) {{", NL_SINGLE, IndentAction.INC)
        for state in self.states:
            dests = [self.state_const(e.dest) for e in state.out_edges]
            if state.in_edges:  # no need to be moving through an edge every time
                dests.append(self.state_const(state))
            cond = " || ".join(f"cwp_next == {d}" for d in dests) or "0"
            sm.write_str(
                f"case {self.state_const(state)}: cwp_valid = {cond}; break;",
                NL_SINGLE,
            )
        sm.write_str("default: break;", NL_SINGLE)
        sm.write_str("}", NL_SINGLE, IndentAction.DEC)
        sm.write_str('assert(cwp_valid && "Not a valid CWP transition");', NL_SINGLE)

    def _write_update(self) -> None:
        sm = self.update_function
        sm.write_str(f"static void {UPDATE_FUNC}(void) {{", NL_SINGLE, IndentAction.INC)
        self._write_select_state(sm, "cwp_next")
        self._write_valid_move(sm)
        sm.write_str(f"{STATE_VAR} = cwp_next;", NL_SINGLE)
        sm.write_str("}", NL_DOUBLE, IndentAction.DEC)

    def visit_state(self, state: CwpState) -> bool:
        if state not in self.states:
            self.states.append(state)
            return True
        return False

    def end_visit_state(self, state: CwpState) -> None:
        pass

    def visit_edge(self, edge: CwpEdge) -> bool:
        return True

    def end_visit_edge(self, edge: CwpEdge) -> None:
        pass

    def visit_cwp(self, model: Cwp) -> bool:
        return True

    def end_visit_cwp(self, model: Cwp) -> None:
        self._write_declarations()
        self._write_init()
        self._write_update()

    def __repr__(self) -> str:
        return f"{self.declarations}{self.init_function}{self.update_function}"
