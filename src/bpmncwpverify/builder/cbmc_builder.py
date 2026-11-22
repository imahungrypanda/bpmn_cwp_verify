from returns.result import Failure, Result, Success

from bpmncwpverify.builder.cbmc_bound import calculate_cbmc_bound
from bpmncwpverify.core.bpmn import Bpmn, EndEvent
from bpmncwpverify.core.cwp import Cwp
from bpmncwpverify.core.error import CbmcBuildError, Error, NotInitializedError
from bpmncwpverify.core.state import State
from bpmncwpverify.util.stringmanager import (
    NL_DOUBLE,
    NL_SINGLE,
    IndentAction,
    StringManager,
)
from bpmncwpverify.visitors.bpmn_cbmc_visitor import (
    ALL_DONE_FUNC,
    STEP_FUNC,
    BpmnCbmcVisitor,
    _ident,  # pyright: ignore[reportPrivateUsage]
)
from bpmncwpverify.visitors.bpmn_cbmc_visitor import INIT_FUNC as BPMN_INIT_FUNC
from bpmncwpverify.visitors.cwp_cbmc_visitor import INIT_FUNC as CWP_INIT_FUNC
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    STATE_VAR,
    CwpCbmcVisitor,
    state_const,
)

STATE_START_STR = "//**********VARIABLE DECLARATION************//"
REACHABILITY_MACRO = "REACHABILITY"
COVER_FUNC = "check_reachability"
STATE_END_STR = "//******************************************//"

_C_TYPES = {
    "bit": "unsigned char",
    "bool": "bool",
    "byte": "unsigned char",
    "short": "short",
    "int": "int",
}


class CbmcOutputs:
    """
    What CBMC needs: the C program and the loop bound it was built for.
    """

    __slots__ = ["c_code", "bound"]

    def __init__(self, c_code: str, bound: int) -> None:
        self.c_code = c_code
        self.bound = bound

    @property
    def unwind(self) -> int:
        """Value for `--unwind`: one more than the bound, so CBMC can check that
        the main loop stops there"""
        return self.bound + 1


def _c_type(state: State, type_: str) -> str:
    if type_ in {enum.id for enum in state.enums}:
        return f"enum {type_}"
    return _C_TYPES.get(type_, type_)


def _generate_state_c(state: State) -> str:
    out = StringManager()
    out.write_str(STATE_START_STR, NL_SINGLE)
    out.write_str("#include <stdbool.h>", NL_DOUBLE)
    for const_decl in state.consts:
        out.write_str(f"#define {const_decl.id} {const_decl.init.value}", NL_SINGLE)
    for enum_decl in state.enums:
        values = ", ".join(sorted(value.value for value in enum_decl.values))
        out.write_str(f"enum {enum_decl.id} {{{values}}};", NL_SINGLE)
    for var_decl in state.vars:
        out.write_str(
            f"static {_c_type(state, var_decl.type_)} {var_decl.id} = {var_decl.init.value};",
            NL_SINGLE,
        )
    out.write_str(STATE_END_STR, NL_DOUBLE)
    return str(out)


def _generate_covers(cwp: Cwp, bpmn: Bpmn, bpmn_c: str) -> str:
    """
    One cover per end event and per CWP state, only seen by the reachability
    run. An end event is reached when a token is on its incoming flow, since
    nothing else stops it from firing. The CWP's start state is left out: the
    initial values put the CWP in the state after it.
    """
    out = StringManager()
    out.write_str(f"#ifdef {REACHABILITY_MACRO}", NL_SINGLE)
    out.write_str(f"static void {COVER_FUNC}(void) {{", NL_SINGLE, IndentAction.INC)
    for process in bpmn.processes.values():
        for node in process.all_items().values():
            func = f"bpmn_enabled_{_ident(node.id)}"
            if isinstance(node, EndEvent) and f"{func}(" in bpmn_c:
                out.write_str(f"__CPROVER_cover({func}());", NL_SINGLE)
    for state in cwp.states.values():
        if state is not cwp.start_state:
            out.write_str(
                f"__CPROVER_cover({STATE_VAR} == {state_const(state)});", NL_SINGLE
            )
    out.write_str("}", NL_SINGLE, IndentAction.DEC)
    out.write_str("#endif", NL_DOUBLE)
    return str(out)


def _generate_main(bound: int) -> str:
    # The CWP is put in the state the initial values give it before any step,
    # like caculateState() in the Promela init block
    out = StringManager()
    out.write_str("int main(void) {", NL_SINGLE, IndentAction.INC)
    out.write_str(f"{CWP_INIT_FUNC}();", NL_SINGLE)
    out.write_str(f"{BPMN_INIT_FUNC}();", NL_SINGLE)
    out.write_str(f"#ifdef {REACHABILITY_MACRO}", NL_SINGLE)
    out.write_str(f"{COVER_FUNC}();", NL_SINGLE)
    out.write_str("#endif", NL_SINGLE)
    out.write_str(f"for (unsigned pass = 0; pass < {bound}u; pass++) {{", NL_SINGLE)
    out.write_str(f"    if ({ALL_DONE_FUNC}()) break;", NL_SINGLE)
    out.write_str(f"    {STEP_FUNC}();", NL_SINGLE)
    out.write_str(f"#ifdef {REACHABILITY_MACRO}", NL_SINGLE)
    out.write_str(f"    {COVER_FUNC}();", NL_SINGLE)
    out.write_str("#endif", NL_SINGLE)
    out.write_str("}", NL_SINGLE)
    out.write_str("return 0;", NL_SINGLE)
    out.write_str("}", NL_SINGLE, IndentAction.DEC)
    return str(out)


def _generate_c(state: State, cwp: Cwp, bpmn: Bpmn) -> Result[CbmcOutputs, Error]:
    if not cwp.states:
        return Failure(CbmcBuildError("the CWP has no states"))
    if not any(p.get_start_states() for p in bpmn.processes.values()):
        return Failure(CbmcBuildError("the BPMN has no start event"))

    cwp_visitor = CwpCbmcVisitor()
    cwp.accept(cwp_visitor)
    bpmn_visitor = BpmnCbmcVisitor()
    bpmn.accept(bpmn_visitor)

    bound = calculate_cbmc_bound(bpmn)
    return bpmn_visitor.result().map(
        lambda bpmn_c: CbmcOutputs(
            f"{_generate_state_c(state)}{cwp_visitor}{bpmn_c}"
            f"{_generate_covers(cwp, bpmn, bpmn_c)}{_generate_main(bound)}\n",
            bound,
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

    def build(self) -> Result[CbmcOutputs, Error]:
        result: Result[CbmcOutputs, Error] = self.state.bind(  # pyright: ignore[reportUnknownMemberType]
            lambda state: self.cwp.bind(  # pyright: ignore[reportUnknownMemberType]
                lambda cwp: self.bpmn.bind(  # pyright: ignore[reportUnknownMemberType]
                    lambda bpmn: _generate_c(state, cwp, bpmn)
                )
            )
        )
        return result

    def with_bpmn(self, bpmn: Bpmn) -> "CbmcBuilder":
        self.bpmn = Success(bpmn)
        return self

    def with_cwp(self, cwp: Cwp) -> "CbmcBuilder":
        self.cwp = Success(cwp)
        return self

    def with_state(self, state: State) -> "CbmcBuilder":
        self.state = Success(state)
        return self
