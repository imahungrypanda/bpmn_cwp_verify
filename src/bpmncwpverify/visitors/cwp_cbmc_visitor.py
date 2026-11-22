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
NEXT_VAR = "cwp_next_state"
NONE_STATE = "CWP_STATE_NONE"
CALCULATE_FUNC = "cwp_calculate_state"
UPDATE_FUNC = "cwp_update_state"


class CwpCbmcVisitor(CwpVisitor):
    """
    Generates C for a CWP. The output is meant to be placed after the state
    variable declarations and before ``main()``:

    * ``CWP_STATE_<name>`` constants, one per state, and ``unsigned char cwp_state``,
      the one variable holding the current CWP state
    * ``CWP_IN_<name>`` macros: the condition on the variables under which the CWP
      is in that state (all in edges hold and no out edge holds)
    * ``void cwp_calculate_state(void)``: puts ``cwp_state`` in the state the
      current variable values map to. Call it once before the main loop
    * ``void cwp_update_state(void)``: moves ``cwp_state`` to the state the
      variable values now map to, asserting that exactly one state is active
      and that the move is staying put or following an edge. Call it once per
      pass of the main loop, after a task whose behavior changes variables

    Nothing in the generated functions loops over anything, so CBMC does not
    unroll them.
    """

    __slots__ = [
        "state_defines",
        "guards",
        "calculate_state_func",
        "update_state_func",
        "state_names",
        "calculate_chain",
        "update_chain",
        "transitions",
    ]

    def __init__(self) -> None:
        self.state_defines = StringManager()
        self.guards = StringManager()
        self.calculate_state_func = StringManager()
        self.update_state_func = StringManager()
        self.state_names: list[str] = []
        self.calculate_chain = StringManager()
        self.update_chain = StringManager()
        self.transitions: list[str] = []

    @staticmethod
    def _state_const(state: CwpState) -> str:
        return f"CWP_STATE_{state.name}"

    @staticmethod
    def _guard_macro(state: CwpState) -> str:
        return f"CWP_IN_{state.name}"

    def _build_guard(self, state: CwpState) -> str:
        in_expr = (
            " && ".join(f"({edge.expression})" for edge in state.in_edges)
            if state.in_edges
            else "1"
        )
        out_expr = (
            " || ".join(f"({edge.expression})" for edge in state.out_edges)
            if state.out_edges
            else "0"
        )
        return f"(({in_expr}) && !({out_expr}))"

    def visit_state(self, state: CwpState) -> bool:
        const = self._state_const(state)
        macro = self._guard_macro(state)
        index = len(self.state_names)
        self.state_names.append(state.name)

        self.state_defines.write_str(f"#define {const} {index}", NL_SINGLE)

        for edge in state.out_edges:
            self.transitions.append(
                f"({STATE_VAR} == {const} && {NEXT_VAR} == {self._state_const(edge.dest)})"
            )

        if state.in_edges:
            self.guards.write_str(
                f"#define {macro} {self._build_guard(state)}", NL_SINGLE
            )
            self.calculate_chain.write_str(
                f"if ({macro}) {STATE_VAR} = {const};", NL_SINGLE
            )
            self.update_chain.write_str(
                f"if ({macro}) {{ {NEXT_VAR} = {const}; active_states++; }}",
                NL_SINGLE,
            )
        else:
            # Same as the SPIN model: a state nothing leads into holds at the
            # start and can never be mapped back to from the variables.
            self.calculate_chain.write_str(f"{STATE_VAR} = {const};", NL_SINGLE)

        return True

    def end_visit_state(self, state: CwpState) -> None:
        pass

    def visit_edge(self, edge: CwpEdge) -> bool:
        return True

    def end_visit_edge(self, edge: CwpEdge) -> None:
        pass

    def visit_cwp(self, model: Cwp) -> bool:
        self.state_defines.write_str(START_STR, NL_SINGLE)
        return True

    def create_calculate_state_func(self) -> None:
        func = self.calculate_state_func
        func.write_str(f"void {CALCULATE_FUNC}(void) {{", NL_SINGLE, IndentAction.INC)
        func.write_str(f"{STATE_VAR} = {NONE_STATE};", NL_SINGLE)
        func.write_str(self.calculate_chain)
        func.write_str("}", NL_SINGLE, IndentAction.DEC)

    def create_update_state_func(self) -> None:
        func = self.update_state_func
        valid = " ||\n\t\t".join([f"{NEXT_VAR} == {STATE_VAR}"] + self.transitions)
        func.write_str(f"void {UPDATE_FUNC}(void) {{", NL_SINGLE, IndentAction.INC)
        func.write_str(f"unsigned char {NEXT_VAR} = {NONE_STATE};", NL_SINGLE)
        func.write_str("int active_states = 0;", NL_SINGLE)
        func.write_str(self.update_chain)
        func.write_str(
            "// Verification of properties 1 & 2 (verifying that we are always in one state and only one state)",
            NL_SINGLE,
        )
        func.write_str(
            '__CPROVER_assert(active_states == 1, "In more than one or no state");',
            NL_SINGLE,
        )
        func.write_str(
            "// Verification of the CWP transition (stay put or follow an edge)",
            NL_SINGLE,
        )
        func.write_str(
            f'__CPROVER_assert(({valid}), "Not a valid CWP transition");',
            NL_SINGLE,
        )
        func.write_str(f"{STATE_VAR} = {NEXT_VAR};", NL_SINGLE)
        func.write_str("}", NL_SINGLE, IndentAction.DEC)

    def end_visit_cwp(self, model: Cwp) -> None:
        self.state_defines.write_str(f"#define {NONE_STATE} 255", NL_SINGLE)
        self.state_defines.write_str(
            f"unsigned char {STATE_VAR} = {NONE_STATE};", NL_SINGLE
        )
        self.state_defines.write_str(END_STR, NL_DOUBLE)
        self.create_calculate_state_func()
        self.create_update_state_func()

    def __repr__(self) -> str:
        return (
            f"{self.state_defines}{self.guards}\n"
            f"{self.calculate_state_func}\n{self.update_state_func}"
        )
