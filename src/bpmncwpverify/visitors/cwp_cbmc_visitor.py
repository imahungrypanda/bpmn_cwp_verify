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
ACTIVE_PREFIX = "cwp_active_"
CURRENT_STATE = "cwp_state"
CALCULATE_FUNC = "cwp_calculate_state"
INIT_FUNC = "cwp_init"
UPDATE_FUNC = "cwp_update"
EDGE_TABLE = "cwp_valid_edge"


class CwpCbmcVisitor(CwpVisitor):
    """
    Generates C for a CWP. The generated code needs <assert.h> and defines:

    - ``int cwp_state``: the current CWP state, one of the ``CWP_STATE_<name>``
      constants
    - ``cwp_init()``: sets ``cwp_state`` from the initial variable values
    - ``cwp_update()``: recalculates the state from the variables and asserts
      that exactly one state is active and that the move is along an edge (or
      stays put). Call it once, after a task that changes a variable.
    """

    __slots__ = ["states", "edges", "output"]

    def __init__(self) -> None:
        self.states: list[CwpState] = []
        self.edges: list[tuple[str, str]] = []
        self.output = StringManager()

    @staticmethod
    def _expr(edge: CwpEdge) -> str:
        return f"({edge.expression})" if edge.expression.strip() else "1"

    def _guard(self, state: CwpState) -> str:
        """The state is active when all its in edges hold and none of its out edges do."""
        in_part = " && ".join(self._expr(e) for e in state.in_edges)
        out_part = " || ".join(self._expr(e) for e in state.out_edges) or "0"
        return f"({in_part}) && !({out_part})"

    def _write_enum(self, out: StringManager) -> None:
        out.write_str("enum {", NL_SINGLE, IndentAction.INC)
        for i, state in enumerate(self.states):
            out.write_str(f"{STATE_PREFIX}{state.name} = {i},", NL_SINGLE)
        out.write_str(f"CWP_STATE_COUNT = {len(self.states)}", NL_SINGLE)
        out.write_str("};", NL_SINGLE, IndentAction.DEC)
        out.write_str(f"static int {CURRENT_STATE};", NL_DOUBLE)

    def _write_edge_table(self, out: StringManager) -> None:
        index = {s.name: i for i, s in enumerate(self.states)}
        valid = {(index[a], index[b]) for a, b in self.edges}
        valid |= {(i, i) for i in index.values()}  # staying put is always allowed
        out.write_str(
            f"static const unsigned char {EDGE_TABLE}[CWP_STATE_COUNT][CWP_STATE_COUNT] = {{",
            NL_SINGLE,
            IndentAction.INC,
        )
        for i in range(len(self.states)):
            row = ", ".join(
                "1" if (i, j) in valid else "0" for j in range(len(self.states))
            )
            out.write_str(f"{{{row}}},", NL_SINGLE)
        out.write_str("};", NL_DOUBLE, IndentAction.DEC)

    def _write_calculate(self, out: StringManager) -> None:
        out.write_str(
            f"static int {CALCULATE_FUNC}(void) {{", NL_SINGLE, IndentAction.INC
        )
        names: list[str] = []
        for state in self.states:
            # A state without in edges is only the initial state, never re-entered
            guard = self._guard(state) if state.in_edges else "0"
            out.write_str(f"int {ACTIVE_PREFIX}{state.name} = {guard};", NL_SINGLE)
            names.append(f"{ACTIVE_PREFIX}{state.name}")
        out.write_str(
            "// Verification of properties 1 & 2 (verifying that we are always in one state and only one state)",
            NL_SINGLE,
        )
        out.write_str(
            f"int sum_of_active_states = {' + '.join(names) or '0'};", NL_SINGLE
        )
        out.write_str("assert(sum_of_active_states == 1);", NL_SINGLE)
        # Exactly one is active, so the weighted sum is the index of that state
        weighted = " + ".join(
            f"{ACTIVE_PREFIX}{s.name} * {STATE_PREFIX}{s.name}" for s in self.states
        )
        out.write_str(f"return {weighted or '0'};", NL_SINGLE)
        out.write_str("}", NL_DOUBLE, IndentAction.DEC)

    def _write_init(self, out: StringManager) -> None:
        out.write_str(f"static void {INIT_FUNC}(void) {{", NL_SINGLE, IndentAction.INC)
        initial = [s for s in self.states if not s.in_edges]
        if initial:
            out.write_str(
                f"{CURRENT_STATE} = {STATE_PREFIX}{initial[0].name};", NL_SINGLE
            )
        else:
            out.write_str(f"{CURRENT_STATE} = {CALCULATE_FUNC}();", NL_SINGLE)
        out.write_str("}", NL_DOUBLE, IndentAction.DEC)

    def _write_update(self, out: StringManager) -> None:
        out.write_str(
            f"static void {UPDATE_FUNC}(void) {{", NL_SINGLE, IndentAction.INC
        )
        out.write_str(f"int next_state = {CALCULATE_FUNC}();", NL_SINGLE)
        out.write_str(
            "// Verification of property 3 (every move follows a valid edge)", NL_SINGLE
        )
        out.write_str(f"assert({EDGE_TABLE}[{CURRENT_STATE}][next_state]);", NL_SINGLE)
        out.write_str(f"{CURRENT_STATE} = next_state;", NL_SINGLE)
        out.write_str("}", NL_DOUBLE, IndentAction.DEC)

    def visit_state(self, state: CwpState) -> bool:
        if any(s.name == state.name for s in self.states):
            return False
        self.states.append(state)
        return True

    def end_visit_state(self, state: CwpState) -> None:
        pass

    def visit_edge(self, edge: CwpEdge) -> bool:
        if edge.source is not None:
            self.edges.append((edge.source.name, edge.dest.name))
        return True

    def end_visit_edge(self, edge: CwpEdge) -> None:
        pass

    def visit_cwp(self, model: Cwp) -> bool:
        self.output.write_str(START_STR, NL_SINGLE)
        return True

    def end_visit_cwp(self, model: Cwp) -> None:
        self._write_enum(self.output)
        self._write_edge_table(self.output)
        self._write_calculate(self.output)
        self._write_init(self.output)
        self._write_update(self.output)
        self.output.write_str(END_STR, NL_DOUBLE)

    def __repr__(self) -> str:
        return str(self.output)
