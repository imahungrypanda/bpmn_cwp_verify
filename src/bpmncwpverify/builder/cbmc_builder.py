import re

from returns.result import Failure, Result, Success

from bpmncwpverify.builder.cbmc_bound import compute_bound
from bpmncwpverify.core.bpmn import Bpmn
from bpmncwpverify.core.cwp import Cwp
from bpmncwpverify.core.error import CbmcBuildError, Error, NotInitializedError
from bpmncwpverify.core.state import State
from bpmncwpverify.util.stringmanager import (
    NL_DOUBLE,
    NL_SINGLE,
    IndentAction,
    StringManager,
)
from bpmncwpverify.visitors.bpmn_cbmc_visitor import CbmcBpmnGenVisitor
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    STATE_PREFIX,
    STATE_VAR,
    CwpCbmcVisitor,
)

BOUND_MACRO = "BPMN_BOUND"
PASS_VAR = "bpmn_pass"
UNWIND_EXTRA = 1
REACHABILITY_MACRO = "REACHABILITY"
NON_WORD = r"\W"
GOALS_FUNC = "reach_goals"

_C_TYPES = {
    "bit": "unsigned char",
    "bool": "bool",
    "byte": "unsigned char",
    "short": "short",
    "int": "int",
}


def _c_type(type_: str, state: State) -> Result[str, Error]:
    if type_ in {enum.id for enum in state.enums}:
        return Success(type_)
    if type_ in _C_TYPES:
        return Success(_C_TYPES[type_])
    return Failure(CbmcBuildError(f"type '{type_}' has no C equivalent"))


def _generate_state_c(state: State) -> Result[str, Error]:
    sm = StringManager()
    sm.write_str("//**********VARIABLE DECLARATION************//", NL_SINGLE)
    sm.write_str("#include <stdbool.h>", NL_SINGLE)
    sm.write_str("#include <assert.h>", NL_SINGLE)
    for const_decl in state.consts:
        sm.write_str(f"#define {const_decl.id} {const_decl.init.value}", NL_SINGLE)
    for enum_decl in state.enums:
        values = ", ".join(value.value for value in enum_decl.values)
        sm.write_str(f"typedef enum {{ {values} }} {enum_decl.id};", NL_SINGLE)
    for var_decl in state.vars:
        c_type = _c_type(var_decl.type_, state)
        if isinstance(c_type, Failure):
            return c_type
        sm.write_str(
            f"{c_type.unwrap()} {var_decl.id} = {var_decl.init.value};", NL_SINGLE
        )
    sm.write_str("", NL_SINGLE)
    return Success(str(sm))


def _generate_covers(cwp: Cwp, bpmn_visitor: CbmcBpmnGenVisitor) -> str:
    """
    Cover goals for the reachability run: each end event has its token, and
    each CWP state but the start state is the current one. The start state is
    left out because the initial values put the CWP straight into the state
    after it, so the C never makes the start state the current one.
    """
    sm = StringManager()
    sm.write_str(f"#ifdef {REACHABILITY_MACRO}", NL_SINGLE)
    sm.write_str(f"static void {GOALS_FUNC}(void) {{", NL_SINGLE, IndentAction.INC)
    for transition in bpmn_visitor.transitions:
        if transition.ends_process:
            sm.write_str(
                f"__CPROVER_cover({transition.enable}); /* end event {transition.label} */",
                NL_SINGLE,
            )
    for state in cwp.states.values():
        if state.id != cwp.start_state.id:
            name = f"{STATE_PREFIX}{re.sub(NON_WORD, '_', state.name)}"
            sm.write_str(
                f"__CPROVER_cover({STATE_VAR} == {name}); /* CWP state {state.name} */",
                NL_SINGLE,
            )
    sm.write_str("}", NL_SINGLE, IndentAction.DEC)
    sm.write_str("#endif", NL_DOUBLE)
    return str(sm)


def _generate_main(bpmn_visitor: CbmcBpmnGenVisitor, bound: int) -> str:
    # One function holds the cover goals, so each is a single goal for CBMC
    # however many passes the loop is unrolled into
    covers = f"#ifdef {REACHABILITY_MACRO}\n{GOALS_FUNC}();\n#endif\n"
    sm = StringManager()
    sm.write_str(f"#define {BOUND_MACRO} {bound}", NL_DOUBLE)
    sm.write_str("int main(void) {", NL_SINGLE, IndentAction.INC)
    sm.write_str(bpmn_visitor.init)
    sm.write_str("cwp_init();", NL_SINGLE)
    sm.write_str(covers)
    sm.write_str(
        f"for (unsigned int {PASS_VAR} = 0; {PASS_VAR} < {BOUND_MACRO}; {PASS_VAR}++) {{",
        NL_SINGLE,
        IndentAction.INC,
    )
    sm.write_str(f"if ({bpmn_visitor.all_ended}) break;", NL_SINGLE)
    sm.write_str(bpmn_visitor.step)
    sm.write_str("cwp_update();", NL_SINGLE)
    sm.write_str(covers)
    sm.write_str("}", NL_SINGLE, IndentAction.DEC)
    sm.write_str("return 0;", NL_SINGLE)
    sm.write_str("}", NL_SINGLE, IndentAction.DEC)
    return str(sm)


def _generate_c(state: State, cwp: Cwp, bpmn: Bpmn) -> Result[str, Error]:
    cwp_visitor = CwpCbmcVisitor()
    cwp.accept(cwp_visitor)
    bpmn_visitor = CbmcBpmnGenVisitor()
    bpmn.accept(bpmn_visitor)
    bpmn_result = bpmn_visitor.result()
    if isinstance(bpmn_result, Failure):
        return bpmn_result
    return _generate_state_c(state).map(
        lambda state_c: (
            f"{state_c}{cwp_visitor}\n{bpmn_visitor.defs}"
            f"{_generate_covers(cwp, bpmn_visitor)}"
            f"{_generate_main(bpmn_visitor, compute_bound(bpmn))}"
        )
    )


class CbmcBuilder:
    __slots__ = [
        "bpmn",
        "cwp",
        "state",
    ]

    def __init__(self) -> None:
        self.bpmn: Result[Bpmn, Error] = Failure(
            NotInitializedError("CbmcBuilder.bpmn")
        )
        self.cwp: Result[Cwp, Error] = Failure(NotInitializedError("CbmcBuilder.cwp"))
        self.state: Result[State, Error] = Failure(
            NotInitializedError("CbmcBuilder.state")
        )

    def build(self) -> Result[str, Error]:
        result: Result[str, Error] = self.state.bind(  # pyright: ignore[reportUnknownMemberType]
            lambda state: self.cwp.bind(  # pyright: ignore[reportUnknownMemberType]
                lambda cwp: self.bpmn.bind(  # pyright: ignore[reportUnknownMemberType]
                    lambda bpmn: _generate_c(state, cwp, bpmn)
                )
            )
        )
        return result

    def bound(self) -> Result[int, Error]:
        """The number of passes of the main loop; CBMC needs --unwind bound() + 1."""
        return self.bpmn.map(compute_bound)

    def unwind(self) -> Result[int, Error]:
        """The value to give CBMC's --unwind."""
        return self.bound().map(lambda bound: bound + UNWIND_EXTRA)

    def with_bpmn(self, bpmn: Bpmn) -> "CbmcBuilder":
        self.bpmn = Success(bpmn)
        return self

    def with_cwp(self, cwp: Cwp) -> "CbmcBuilder":
        self.cwp = Success(cwp)
        return self

    def with_state(self, state: State) -> "CbmcBuilder":
        self.state = Success(state)
        return self
