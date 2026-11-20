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
STATE_PREFIX = "CWP_"
UPDATE_FUNCTION = "cwp_update_state"
CALCULATE_FUNCTION = "cwp_calculate_state"


def _enum_name(state: CwpState) -> str:
    return f"{STATE_PREFIX}{state.name}"


class CwpCbmcVisitor(CwpVisitor):
    """
    Generates C for a CWP. The current state is a single enum variable, so
    exactly one state is active by construction; the update function asserts
    that the variable holds a valid state and that every move follows an edge.

    The output has three parts, which the caller places in this order, after
    the declarations of the state variables the edge expressions refer to:

    - ``declarations``: includes, the state enum, ``cwp_state``, and the
      prototype of ``nondet_uint``
    - ``calculate_function``: ``cwp_calculate_state()``, run once at start-up
      to put the CWP in the state the initial variable values give
    - ``update_function``: ``cwp_update_state()``, run after every task that
      changes a variable
    """

    __slots__ = [
        "declarations",
        "calculate_function",
        "update_function",
        "states",
        "start_state",
    ]

    def __init__(self) -> None:
        self.declarations = StringManager()
        self.calculate_function = StringManager()
        self.update_function = StringManager()
        self.states: list[CwpState] = []
        self.start_state: CwpState | None = None

    @staticmethod
    def _mapping_expression(state: CwpState) -> str:
        """The condition (as in the SPIN model) under which the variables put
        the CWP in this state: all in edges hold and no out edge does."""
        ins = " && ".join(f"({e.expression})" for e in state.in_edges) or "true"
        outs = " || ".join(f"({e.expression})" for e in state.out_edges) or "false"
        return f"({ins}) && !({outs})"

    def _build_declarations(self) -> None:
        d = self.declarations
        d.write_str(START_STR, NL_SINGLE)
        d.write_str("#include <stdbool.h>", NL_SINGLE)
        d.write_str("unsigned int nondet_uint(void);", NL_SINGLE)
        d.write_str("enum CwpState {", NL_SINGLE, IndentAction.INC)
        d.write_str(
            ",\n\t".join(_enum_name(s) for s in self.states) or f"{STATE_PREFIX}NONE",
            NL_SINGLE,
        )
        d.write_str("};", NL_SINGLE, IndentAction.DEC)
        initial = _enum_name(self.start_state) if self.start_state else "0"
        d.write_str(f"enum CwpState {STATE_VAR} = {initial};", NL_SINGLE)
        d.write_str(END_STR, NL_DOUBLE)

    def _build_calculate_function(self) -> None:
        f = self.calculate_function
        f.write_str(f"void {CALCULATE_FUNCTION}(void) {{", NL_SINGLE, IndentAction.INC)
        # A state without in edges can only be the start state, and it is the
        # initial state unless another state matches the initial values.
        start_is_default = (
            self.start_state is not None and not self.start_state.in_edges
        )
        f.write_str(f"int matches = {1 if start_is_default else 0};", NL_SINGLE)
        for state in self.states:
            if not state.in_edges:
                continue
            f.write_str(
                f"if ({self._mapping_expression(state)}) {{",
                NL_SINGLE,
                IndentAction.INC,
            )
            f.write_str(f"{STATE_VAR} = {_enum_name(state)};", NL_SINGLE)
            f.write_str("matches++;", NL_SINGLE)
            f.write_str("}", NL_SINGLE, IndentAction.DEC)
        f.write_str(
            '__CPROVER_assert(matches == 1, "Assert: Not in exactly one state");',
            NL_SINGLE,
        )
        f.write_str("}", NL_DOUBLE, IndentAction.DEC)

    def _build_case(self, state: CwpState) -> None:
        """One case of the switch: the moves available from this state. A
        state with in edges may also stay where it is."""
        f = self.update_function
        options: list[tuple[CwpState, str]] = [
            (e.dest, self._mapping_expression(e.dest)) for e in state.out_edges
        ]
        if state.in_edges:
            options.append((state, self._mapping_expression(state)))

        f.write_str(f"case {_enum_name(state)}: {{", NL_SINGLE, IndentAction.INC)
        for i, (_, cond) in enumerate(options):
            f.write_str(f"bool enabled{i} = {cond};", NL_SINGLE)
        enabled_any = " || ".join(f"enabled{i}" for i in range(len(options))) or "false"
        f.write_str(
            f'__CPROVER_assert({enabled_any}, "Assert: Not a valid CWP transition");',
            NL_SINGLE,
        )
        if options:
            f.write_str("unsigned int choice = nondet_uint();", NL_SINGLE)
            f.write_str("switch (choice) {", NL_SINGLE, IndentAction.INC)
            for i, (dest, _) in enumerate(options):
                f.write_str(f"case {i}:", NL_SINGLE, IndentAction.INC)
                f.write_str(f"__CPROVER_assume(enabled{i});", NL_SINGLE)
                f.write_str(f"{STATE_VAR} = {_enum_name(dest)};", NL_SINGLE)
                f.write_str("break;", NL_SINGLE, IndentAction.DEC)
            f.write_str("default:", NL_SINGLE, IndentAction.INC)
            f.write_str("__CPROVER_assume(false);", NL_SINGLE, IndentAction.DEC)
            f.write_str("}", NL_SINGLE, IndentAction.DEC)
        f.write_str("break;", NL_SINGLE)
        f.write_str("}", NL_SINGLE, IndentAction.DEC)

    def _build_update_function(self) -> None:
        f = self.update_function
        f.write_str(f"void {UPDATE_FUNCTION}(void) {{", NL_SINGLE, IndentAction.INC)
        f.write_str(f"switch ({STATE_VAR}) {{", NL_SINGLE, IndentAction.INC)
        for state in self.states:
            self._build_case(state)
        f.write_str("default:", NL_SINGLE, IndentAction.INC)
        f.write_str(
            '__CPROVER_assert(false, "Assert: In no state");',
            NL_SINGLE,
        )
        f.write_str("break;", NL_SINGLE, IndentAction.DEC)
        f.write_str("}", NL_SINGLE, IndentAction.DEC)
        f.write_str("}", NL_DOUBLE, IndentAction.DEC)

    def visit_state(self, state: CwpState) -> bool:
        if all(s is not state for s in self.states):
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
        self.start_state = model.start_state
        return True

    def end_visit_cwp(self, model: Cwp) -> None:
        self._build_declarations()
        self._build_calculate_function()
        self._build_update_function()

    def __repr__(self) -> str:
        return f"{self.declarations}{self.calculate_function}{self.update_function}"
