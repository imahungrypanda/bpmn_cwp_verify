from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState, CwpVisitor
from bpmncwpverify.util.stringmanager import (
    NL_DOUBLE,
    NL_SINGLE,
    IndentAction,
    StringManager,
)

START_STR = "//**********CWP VARIABLE DECLARATION************//"
END_STR = "//**********************************************//"
PRIME_SUFFIX = "_prime"


class CwpCbmcVisitor(CwpVisitor):
    """
    Turns a CWP into C. The output needs <stdbool.h> and <assert.h> (the
    builder is responsible for the includes) and defines:

    - one ``bool`` per CWP state (the start state begins true, the rest false)
    - ``void calculateState(void)``: derives each non-start state from the
      edge expressions
    - ``void updateState(void)``: moves along a CWP edge (or stays put) and
      asserts that the move was valid and that exactly one state is active
    """

    __slots__ = [
        "cwp_states",
        "update_state_function",
        "calculate_state_function",
        "prime_vars",
        "vars",
        "proper_path_block",
        "var_reassignment",
        "list_of_cwp_states",
        "_visited",
    ]

    def __init__(self) -> None:
        self.cwp_states = StringManager()
        self.update_state_function = StringManager()
        self.calculate_state_function = StringManager()
        self.prime_vars = StringManager()
        self.vars = StringManager()
        self.proper_path_block = StringManager()
        self.var_reassignment = StringManager()
        self.list_of_cwp_states: list[str] = []
        self._visited: set[str] = set()

    @staticmethod
    def _expr(edge: CwpEdge) -> str:
        # An edge with no expression places no constraint.
        return f"({edge.expression})" if edge.expression.strip() else "true"

    def _build_mapping_function(self, state: CwpState) -> str:
        in_exprs = " && ".join(self._expr(e) for e in state.in_edges) or "true"
        out_exprs = " || ".join(self._expr(e) for e in state.out_edges) or "false"
        return f"({in_exprs}) && !({out_exprs})"

    def _build_prime_var(self, state: CwpState) -> None:
        self.prime_vars.write_str(
            f"bool {state.name}{PRIME_SUFFIX} = {self._build_mapping_function(state)};",
            NL_SINGLE,
        )

    def _build_vars(self, state: CwpState) -> None:
        self.vars.write_str(
            f"{state.name} = {self._build_mapping_function(state)};", NL_SINGLE
        )

    def _build_proper_path_block(self, state: CwpState) -> None:
        for out_edge in state.out_edges:
            self.proper_path_block.write_str(
                f"|| ({state.name} && {out_edge.dest.name}{PRIME_SUFFIX})", NL_SINGLE
            )

    def _add_stationary_state(self, state: CwpState) -> None:
        """
        Allows the state to remain the same. We don't always need to be moving
        through an edge.
        """
        self.proper_path_block.write_str(
            f"|| ({state.name} && {state.name}{PRIME_SUFFIX})", NL_SINGLE
        )

    def _reassign_vars_to_primes(self, state: CwpState) -> None:
        self.var_reassignment.write_str(
            f"{state.name} = {state.name}{PRIME_SUFFIX};", NL_SINGLE
        )

    def build_XOR_block(self) -> StringManager:
        xor = StringManager()
        xor.write_str(
            "// Verification of properties 1 & 2 (verifying that we are always in one state and only one state)",
            NL_SINGLE,
        )
        total = " + ".join(f"(int){s}" for s in self.list_of_cwp_states) or "0"
        xor.write_str(f"int sumOfActiveStates = {total};", NL_SINGLE)
        xor.write_str(
            'assert(sumOfActiveStates == 1 && "In more than one or no state");',
            NL_SINGLE,
        )
        return xor

    def visit_state(self, state: CwpState) -> bool:
        if state.name in self._visited:
            return False
        self._visited.add(state.name)

        if state.in_edges:
            self.list_of_cwp_states.append(state.name)
            self.cwp_states.write_str(f"bool {state.name} = false;", NL_SINGLE)

            self._build_prime_var(state)
            self._build_vars(state)
            self._build_proper_path_block(state)
            self._add_stationary_state(state)
            self._reassign_vars_to_primes(state)
        else:
            self.cwp_states.write_str(f"bool {state.name} = true;", NL_SINGLE)
            self._build_proper_path_block(state)
            self.var_reassignment.write_str(f"{state.name} = false;", NL_SINGLE)

        return True

    def end_visit_state(self, state: CwpState) -> None:
        pass

    def visit_edge(self, edge: CwpEdge) -> bool:
        return True

    def end_visit_edge(self, edge: CwpEdge) -> None:
        pass

    def create_update_state_function(self) -> None:
        out = self.update_state_function
        out.write_str("void updateState(void) {", NL_SINGLE, IndentAction.INC)
        out.write_str(self.prime_vars)

        out.write_str("bool validTransition = false", NL_SINGLE, IndentAction.INC)
        out.write_str(self.proper_path_block)
        out.write_str(";", NL_SINGLE, IndentAction.DEC)
        out.write_str(
            'assert(validTransition && "Not a valid CWP transition");', NL_SINGLE
        )

        out.write_str(self.var_reassignment)
        out.write_str(self.build_XOR_block())
        out.write_str("}", NL_SINGLE, IndentAction.DEC)

    def create_calculate_state_function(self) -> None:
        out = self.calculate_state_function
        out.write_str("void calculateState(void) {", NL_SINGLE, IndentAction.INC)
        out.write_str(self.vars)
        out.write_str("}", NL_SINGLE, IndentAction.DEC)

    def visit_cwp(self, model: Cwp) -> bool:
        self.cwp_states.write_str(START_STR, NL_SINGLE)
        return True

    def end_visit_cwp(self, model: Cwp) -> None:
        self.cwp_states.write_str(END_STR, NL_DOUBLE)
        self.create_update_state_function()
        self.create_calculate_state_function()

    def __repr__(self) -> str:
        return f"{self.cwp_states}{self.update_state_function}{self.calculate_state_function}"
