import re

from returns.pipeline import is_successful
from returns.result import Failure, Result, Success

from bpmncwpverify.builder.cbmc_bound import get_unwinding_bound
from bpmncwpverify.core.bpmn import Bpmn
from bpmncwpverify.core.cwp import Cwp
from bpmncwpverify.core.error import CbmcBuildError, Error, NotInitializedError
from bpmncwpverify.core.state import State
from bpmncwpverify.util.stringmanager import NL_DOUBLE, NL_SINGLE, StringManager
from bpmncwpverify.visitors.bpmn_cbmc_visitor import CHOICE_VAR, CbmcBpmnVisitor
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    CALCULATE_FUNC,
    STATE_PREFIX,
    STATE_VAR,
    UPDATE_FUNC,
    CwpCbmcVisitor,
)

PASS_VAR = "pass_count"
BOUND_MACRO = "UNWINDING_BOUND"
REACHABILITY_MACRO = "REACHABILITY"
CWP_REACHED_PREFIX = "reached_cwp_"
END_REACHED_PREFIX = "reached_end_"
END_EVENT_LABEL = "end event "

_C_TYPES = {
    "bit": "unsigned char",
    "bool": "bool",
    "byte": "unsigned char",
    "short": "short",
    "int": "int",
}


def _c_type(type_: str, enums: set[str]) -> Result[str, Error]:
    if type_ in enums:
        return Success(f"enum {type_}")
    if type_ in _C_TYPES:
        return Success(_C_TYPES[type_])
    return Failure(CbmcBuildError(f"variable type '{type_}' has no C equivalent"))


def _generate_state_c(state: State) -> Result[str, Error]:
    sm = StringManager()
    enums = {enum.id for enum in state.enums}
    sm.write_str("#include <assert.h>", NL_SINGLE)
    sm.write_str("#include <stdbool.h>", NL_DOUBLE)
    sm.write_str("//**********VARIABLE DECLARATION************//", NL_SINGLE)
    for const_decl in state.consts:
        sm.write_str(f"#define {const_decl.id} {const_decl.init.value}", NL_SINGLE)
    for enum_decl in state.enums:
        values = ", ".join(sorted(value.value for value in enum_decl.values))
        sm.write_str(f"enum {enum_decl.id} {{{values}}};", NL_SINGLE)
    for var_decl in state.vars:
        c_type = _c_type(var_decl.type_, enums)
        if not is_successful(c_type):
            return c_type
        sm.write_str(
            f"{c_type.unwrap()} {var_decl.id} = {var_decl.init.value};", NL_SINGLE
        )
    sm.write_str("", NL_SINGLE)
    return Success(str(sm))


def _ident(name: str) -> str:
    return re.sub(r"\W", "_", name)


def _reachability_targets(
    cwp: Cwp, bpmn_visitor: CbmcBpmnVisitor
) -> list[tuple[str, str]]:
    """
    (flag, condition) for each end event and each CWP state but the start state.
    The flag is set once the condition holds right after a pass. The start state
    is left out: the initial values already put the CWP in the state after it.
    """
    targets: list[tuple[str, str]] = []
    # the visitor numbers its transitions, and labels the end events' ones
    for transition in bpmn_visitor._transitions:  # pyright: ignore[reportPrivateUsage]
        if transition.label.startswith(END_EVENT_LABEL):
            event_id = transition.label[len(END_EVENT_LABEL) :]
            targets.append(
                (
                    f"{END_REACHED_PREFIX}{_ident(event_id)}",
                    f"{CHOICE_VAR} == {transition.index}",
                )
            )
    for state in cwp.states.values():
        if state is not cwp.start_state:
            targets.append(
                (
                    f"{CWP_REACHED_PREFIX}{_ident(state.name)}",
                    f"{STATE_VAR} == {STATE_PREFIX}{state.name}",
                )
            )
    return targets


def _generate_main(
    bpmn_visitor: CbmcBpmnVisitor, bound: int, targets: list[tuple[str, str]]
) -> str:
    sm = StringManager()
    sm.write_str(f"#define {BOUND_MACRO} {bound}", NL_DOUBLE)
    sm.write_str(f"#ifdef {REACHABILITY_MACRO}", NL_SINGLE)
    for flag, _ in targets:
        sm.write_str(f"bool {flag} = false;", NL_SINGLE)
    sm.write_str("#endif", NL_DOUBLE)
    sm.write_str("int main(void) {", NL_SINGLE)
    sm.write_str(f"\t{CALCULATE_FUNC}();", NL_SINGLE)
    sm.write_str(f"#ifdef {REACHABILITY_MACRO}", NL_SINGLE)
    for flag, condition in targets:
        if condition.startswith(STATE_VAR):
            sm.write_str(f"\t{flag} = {condition};", NL_SINGLE)
    sm.write_str("#endif", NL_SINGLE)
    sm.write_str(
        f"\tfor (int {PASS_VAR} = 0; !({bpmn_visitor.all_ended}) && "
        f"{PASS_VAR} < {BOUND_MACRO}; {PASS_VAR}++) {{",
        NL_SINGLE,
    )
    for line in str(bpmn_visitor.step).splitlines():
        sm.write_str(f"\t\t{line}", NL_SINGLE)
    sm.write_str(f"\t\t{UPDATE_FUNC}();", NL_SINGLE)
    sm.write_str(f"#ifdef {REACHABILITY_MACRO}", NL_SINGLE)
    for flag, condition in targets:
        sm.write_str(f"\t\t{flag} = {flag} || ({condition});", NL_SINGLE)
    sm.write_str("#endif", NL_SINGLE)
    sm.write_str("\t}", NL_SINGLE)
    sm.write_str(f"#ifdef {REACHABILITY_MACRO}", NL_SINGLE)
    for flag, _ in targets:
        sm.write_str(f"\t__CPROVER_cover({flag});", NL_SINGLE)
    sm.write_str("#endif", NL_SINGLE)
    sm.write_str("\treturn 0;", NL_SINGLE)
    sm.write_str("}", NL_SINGLE)
    return str(sm)


def _generate_c(state: State, cwp: Cwp, bpmn: Bpmn) -> Result[str, Error]:
    if not cwp.states:
        return Failure(CbmcBuildError("the CWP has no states"))

    cwp_visitor = CwpCbmcVisitor()
    cwp.accept(cwp_visitor)
    bpmn_visitor = CbmcBpmnVisitor()
    bpmn.accept(bpmn_visitor)
    bound = get_unwinding_bound(bpmn)

    def assemble(state_c: str, visitor: CbmcBpmnVisitor) -> Result[str, Error]:
        # The BPMN and CWP code read the state variables, so they come after them
        return Success(
            f"{state_c}static void {UPDATE_FUNC}(void);\n\n{visitor.declarations}\n{cwp_visitor}\n"
            f"{_generate_main(visitor, bound, _reachability_targets(cwp, visitor))}"
        )

    result: Result[str, Error] = _generate_state_c(state).bind(  # pyright: ignore[reportUnknownMemberType]
        lambda state_c: bpmn_visitor.result().bind(  # pyright: ignore[reportUnknownMemberType]
            lambda visitor: assemble(state_c, visitor)
        )
    )
    return result


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

    def unwinding_bound(self) -> Result[int, Error]:
        """
        Number of passes of main()'s loop. CBMC needs `--unwind` set to this plus one.
        """
        return self.bpmn.map(get_unwinding_bound)

    def with_bpmn(self, bpmn: Bpmn) -> "CbmcBuilder":
        self.bpmn = Success(bpmn)
        return self

    def with_cwp(self, cwp: Cwp) -> "CbmcBuilder":
        self.cwp = Success(cwp)
        return self

    def with_state(self, state: State) -> "CbmcBuilder":
        self.state = Success(state)
        return self
