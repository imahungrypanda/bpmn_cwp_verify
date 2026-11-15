from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState, CwpVisitor
from bpmncwpverify.util.stringmanager import (
    NL_DOUBLE,
    NL_SINGLE,
    IndentAction,
    StringManager,
)

START_STR = "//**********CWP VARIABLE DECLARATION************//"
END_STR = "//**********************************************//"
STATE_PREFIX = "CWP_STATE_"
NEXT_PREFIX = "cwp_next_"
STATE_VAR = "cwp_state"


class CwpCbmcVisitor(CwpVisitor):
    """
    Generates C for a CWP. The output needs <stdbool.h> and <assert.h>, and the
    state variables used by the edge expressions must be declared before it.

    - `cwp_state` holds the one active CWP state (an enum constant), so
      exactly one state is active by construction.
    - `cwp_calculate_state()` puts `cwp_state` where the current variable
      values say it belongs. Call it once after the variables are initialized.
    - `cwp_update_state()` moves `cwp_state` after the variables change. It
      asserts that exactly one state matches the new values (properties 1 & 2)
      and that the move is staying put or following an out edge.
    """

    __slots__ = [
        "start_state",
        "enum_names",
        "tracked_states",
        "valid_moves",
        "seen",
        "declarations",
        "calculate_state_func",
        "update_state_func",
    ]

    def __init__(self) -> None:
        self.start_state: CwpState | None = None
        self.enum_names: list[str] = []
        self.tracked_states: list[CwpState] = []  # states that have in edges
        self.valid_moves: list[str] = []
        self.seen: set[str] = set()
        self.declarations = StringManager()
        self.calculate_state_func = StringManager()
        self.update_state_func = StringManager()

    @staticmethod
    def _enum_name(state: CwpState) -> str:
        return f"{STATE_PREFIX}{state.name}"

    @staticmethod
    def _next_name(state: CwpState) -> str:
        return f"{NEXT_PREFIX}{state.name}"

    @staticmethod
    def _build_mapping_function(state: CwpState) -> str:
        """The state holds when all in edges hold and no out edge does."""
        in_expr = (
            " && ".join(f"({edge.expression})" for edge in state.in_edges)
            if state.in_edges
            else "true"
        )
        out_expr = (
            " || ".join(f"({edge.expression})" for edge in state.out_edges)
            if state.out_edges
            else "false"
        )
        return f"({in_expr}) && !({out_expr})"

    def _write_next_decls(self, func: StringManager) -> None:
        for state in self.tracked_states:
            func.write_str(
                f"bool {self._next_name(state)} = {self._build_mapping_function(state)};",
                NL_SINGLE,
            )

    def _write_active_count(self, func: StringManager) -> None:
        total = " + ".join(f"(int){self._next_name(s)}" for s in self.tracked_states)
        func.write_str(f"int cwp_active_count = {total or '0'};", NL_SINGLE)

    def _write_assign_state(self, func: StringManager) -> None:
        for state in self.tracked_states:
            func.write_str(
                f"if ({self._next_name(state)}) {STATE_VAR} = {self._enum_name(state)};",
                NL_SINGLE,
            )

    def _record_moves(self, state: CwpState) -> None:
        for out_edge in state.out_edges:
            self.valid_moves.append(
                f"({STATE_VAR} == {self._enum_name(state)} && {self._next_name(out_edge.dest)})"
            )
        if state.in_edges:
            # Staying in the same state is always allowed.
            self.valid_moves.append(
                f"({STATE_VAR} == {self._enum_name(state)} && {self._next_name(state)})"
            )

    def visit_state(self, state: CwpState) -> bool:
        if state.name in self.seen:
            return True
        self.seen.add(state.name)
        self.enum_names.append(self._enum_name(state))
        if state.in_edges:
            self.tracked_states.append(state)
        self._record_moves(state)
        return True

    def end_visit_state(self, state: CwpState) -> None:
        pass

    def visit_edge(self, edge: CwpEdge) -> bool:
        return True

    def end_visit_edge(self, edge: CwpEdge) -> None:
        pass

    def visit_cwp(self, model: Cwp) -> bool:
        self.start_state = model.start_state
        return True

    def _create_declarations(self) -> None:
        self.declarations.write_str(START_STR, NL_SINGLE)
        enum_body = ", ".join(self.enum_names)
        self.declarations.write_str(f"enum {{ {enum_body} }};", NL_SINGLE)
        assert self.start_state is not None
        self.declarations.write_str(
            f"int {STATE_VAR} = {self._enum_name(self.start_state)};", NL_SINGLE
        )
        self.declarations.write_str(END_STR, NL_DOUBLE)

    def _create_calculate_state(self) -> None:
        func = self.calculate_state_func
        assert self.start_state is not None
        func.write_str("void cwp_calculate_state(void) {", NL_SINGLE, IndentAction.INC)
        self._write_next_decls(func)
        self._write_active_count(func)
        func.write_str("assert(cwp_active_count <= 1);", NL_SINGLE)
        # With no matching state, the CWP is still in its start state.
        func.write_str(f"{STATE_VAR} = {self._enum_name(self.start_state)};", NL_SINGLE)
        self._write_assign_state(func)
        func.write_str("}", NL_DOUBLE, IndentAction.DEC)

    def _create_update_state(self) -> None:
        func = self.update_state_func
        func.write_str("void cwp_update_state(void) {", NL_SINGLE, IndentAction.INC)
        self._write_next_decls(func)
        self._write_active_count(func)
        func.write_str(
            "// Verification of properties 1 & 2 (verifying that we are always in one state and only one state)",
            NL_SINGLE,
        )
        func.write_str("assert(cwp_active_count == 1);", NL_SINGLE)
        func.write_str(
            "// Verification that the move follows a valid CWP edge", NL_SINGLE
        )
        moves = " || ".join(self.valid_moves) or "false"
        func.write_str(f"bool cwp_valid_move = {moves};", NL_SINGLE)
        func.write_str("assert(cwp_valid_move);", NL_SINGLE)
        self._write_assign_state(func)
        func.write_str("}", NL_DOUBLE, IndentAction.DEC)

    def end_visit_cwp(self, model: Cwp) -> None:
        self._create_declarations()
        self._create_calculate_state()
        self._create_update_state()

    def __repr__(self) -> str:
        return f"{self.declarations}{self.calculate_state_func}{self.update_state_func}"
