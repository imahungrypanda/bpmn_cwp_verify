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


class CwpPromelaVisitor(CwpVisitor):
    __slots__ = [
        "cwp_states",
        "update_state_inline",
        "caculate_state_inline",
        "prime_vars",
        "vars",
        "proper_path_block",
        "var_reassignment",
        "list_of_cwp_states",
    ]

    def __init__(self) -> None:
        self.cwp_states = StringManager()
        self.update_state_inline = StringManager()
        self.caculate_state_inline = StringManager()
        self.prime_vars = StringManager()
        self.vars = StringManager()
        self.proper_path_block = StringManager()
        self.var_reassignment = StringManager()
        self.list_of_cwp_states: list[str] = []

    def _build_mapping_function(self, state: CwpState) -> StringManager:
        guard = StringManager()

        guard.write_str("(")
        guard.write_str(
            " && ".join(
                [f"{edge.expression}" for edge in state.in_edges]
                if state.in_edges
                else ["true"]
            )
        )  # ["true"] in case no in edges

        guard.write_str(") && !(")

        guard.write_str(
            " || ".join(
                [f"{edge.expression}" for edge in state.out_edges]
                if state.out_edges
                else ["false"]
            )
        )  # ["false"] in case no out edges

        guard.write_str(")")

        return guard

    def _build_prime_var(self, state: CwpState) -> None:
        mapping_func = self._build_mapping_function(state)
        self.prime_vars.write_str(
            f"bool {state.name}{PRIME_SUFFIX} = {mapping_func}", NL_SINGLE
        )

    def _build_vars(self, state: CwpState) -> None:
        mapping_func = self._build_mapping_function(state)
        self.vars.write_str(f"{state.name} = {mapping_func}", NL_SINGLE)

    def _build_proper_path_block(self, state: CwpState) -> None:
        for out_edge in state.out_edges:
            self.proper_path_block.write_str(
                f":: {state.name} && {out_edge.dest.name}{PRIME_SUFFIX}", NL_SINGLE
            )

    def _add_stationary_state(self, state: CwpState) -> None:
        """
        Allows the state to remain the same. We don't always need to be moving
        through an edge.
        """
        self.proper_path_block.write_str(
            f":: {state.name} && {state.name}{PRIME_SUFFIX}", NL_SINGLE
        )

    def _reassign_vars_to_primes(self, state: CwpState) -> None:
        self.var_reassignment.write_str(
            f"{state.name} = {state.name}{PRIME_SUFFIX}", NL_SINGLE
        )

    def build_XOR_block(self) -> StringManager:
        nWayXor = StringManager()
        nWayXor.write_str(
            "// Verification of properties 1 & 2 (verifying that we are always in one state and only one state)",
            NL_SINGLE,
        )
        nWayXor.write_str("int sumOfActiveStates = ")

        nWayXor.write_str(
            " + ".join([state for state in self.list_of_cwp_states]), NL_DOUBLE
        )

        nWayXor.write_str("if", NL_SINGLE, IndentAction.INC)

        nWayXor.write_str(
            ':: (sumOfActiveStates != 1) -> {printf("Assert: In more that one or no state"); assert false}',
            NL_SINGLE,
        )
        nWayXor.write_str(":: else -> skip", NL_SINGLE)

        nWayXor.write_str("fi", NL_SINGLE, IndentAction.DEC)

        return nWayXor

    def visit_state(self, state: CwpState) -> bool:
        if state.in_edges:
            self.list_of_cwp_states.append(state.name)
            new_str = f"bool {state.name} = false"
            self.cwp_states.write_str(new_str, NL_SINGLE)

            self._build_prime_var(state)
            self._build_vars(state)
            self._build_proper_path_block(state)
            self._add_stationary_state(state)
            self._reassign_vars_to_primes(state)
        else:
            self.cwp_states.write_str(f"bool {state.name} = true", NL_SINGLE)
            self._build_proper_path_block(state)
            self.var_reassignment.write_str(f"{state.name} = false", NL_SINGLE)

        return True

    def end_visit_state(self, state: CwpState) -> None:
        pass

    def visit_edge(self, edge: CwpEdge) -> bool:
        return True

    def create_update_state_inline(
        self,
    ) -> None:
        new_str = "inline updateState() {"
        self.update_state_inline.write_str(new_str, NL_SINGLE, IndentAction.INC)

        self.update_state_inline.write_str(self.prime_vars)

        self.update_state_inline.write_str("if", NL_SINGLE, IndentAction.INC)

        self.update_state_inline.write_str(self.proper_path_block)

        self.update_state_inline.write_str(
            ':: else -> printf("Assert: Not a valid CWP transition"); assert false',
            NL_SINGLE,
        )

        self.update_state_inline.write_str("fi", NL_SINGLE, IndentAction.DEC)

        self.update_state_inline.write_str(self.var_reassignment)

        self.update_state_inline.write_str(self.build_XOR_block())

        self.update_state_inline.write_str("}", NL_SINGLE, IndentAction.DEC)

    def create_caculate_state_inline(self) -> None:
        self.caculate_state_inline.write_str(
            "inline caculateState() {", NL_SINGLE, IndentAction.INC
        )

        self.caculate_state_inline.write_str(self.vars)

        self.caculate_state_inline.write_str("}", NL_SINGLE, IndentAction.DEC)

    def end_visit_edge(self, edge: CwpEdge) -> None:
        pass

    def visit_cwp(self, model: Cwp) -> bool:
        self.cwp_states.write_str(START_STR, NL_SINGLE)
        return True

    def end_visit_cwp(self, model: Cwp) -> None:
        self.cwp_states.write_str(END_STR, NL_DOUBLE)
        self.create_update_state_inline()
        self.create_caculate_state_inline()

    def __repr__(self) -> str:
        return (
            f"{self.cwp_states}{self.update_state_inline}{self.caculate_state_inline}"
        )
