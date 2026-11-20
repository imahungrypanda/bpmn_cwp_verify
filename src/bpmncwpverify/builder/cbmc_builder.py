from returns.result import Failure, Result, Success

from bpmncwpverify.builder.cbmc_bound import compute_bound
from bpmncwpverify.core.bpmn import Bpmn, EndEvent
from bpmncwpverify.core.cwp import Cwp
from bpmncwpverify.core.error import CbmcBuildError, Error, NotInitializedError
from bpmncwpverify.core.state import State
from bpmncwpverify.util.stringmanager import NL_SINGLE, IndentAction, StringManager
from bpmncwpverify.visitors.bpmn_cbmc_visitor import CbmcBpmnGenVisitor
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    CURRENT_STATE,
    INIT_FUNC,
    STATE_PREFIX,
    CwpCbmcVisitor,
)

STEP_VAR = "step"
BOUND_MACRO = "BOUND"
REACHABILITY_MACRO = "REACHABILITY"

_C_TYPES = {
    "bit": "unsigned char",
    "bool": "unsigned char",
    "byte": "unsigned char",
    "short": "short",
    "int": "int",
}


class CbmcProgram:
    """The generated C and the number of passes of its main loop."""

    __slots__ = ["code", "bound"]

    def __init__(self, code: str, bound: int) -> None:
        self.code = code
        self.bound = bound

    @property
    def unwind(self) -> int:
        """Value for ``cbmc --unwind``: one more than the bound, so CBMC checks the loop stops."""
        return self.bound + 1

    def __str__(self) -> str:
        return self.code


def _generate_state_c(state: State) -> str:
    lines = ["//**********VARIABLE DECLARATION************//"]
    for const_decl in state.consts:
        lines.append(f"#define {const_decl.id} {const_decl.init.value}")
    enum_ids = {enum.id for enum in state.enums}
    for enum_decl in state.enums:
        values = ", ".join(value.value for value in enum_decl.values)
        lines.append(f"enum {enum_decl.id} {{{values}}};")
    for var_decl in state.vars:
        if var_decl.type_ in enum_ids:
            c_type = f"enum {var_decl.type_}"
        else:
            c_type = _C_TYPES.get(var_decl.type_, var_decl.type_)
        lines.append(f"{c_type} {var_decl.id} = {var_decl.init.value};")
    return "\n".join(lines) + "\n\n"


def _end_event_covers(bpmn: Bpmn, bpmn_visitor: CbmcBpmnGenVisitor) -> list[str]:
    """One cover per end event: a token is waiting on its incoming place."""
    covers: list[str] = []
    for process in bpmn.processes.values():
        for node in process.all_items().values():
            if isinstance(node, EndEvent):
                seq, msg = bpmn_visitor._in_places(node)  # pyright: ignore[reportPrivateUsage]
                places = " || ".join(seq + msg)
                covers.append(f"__CPROVER_cover({places}); /* end event {node.id} */")
    return covers


def _generate_main(
    bpmn_visitor: CbmcBpmnGenVisitor,
    bound: int,
    end_covers: list[str],
    cwp_visitor: CwpCbmcVisitor,
) -> str:
    # The CWP's start state is never made active in the C, so it has no cover.
    # The initial values put the CWP in the state after it, so covers go
    # straight after the init as well as after each pass.
    cwp_states = [s.name for s in cwp_visitor.states if not s.init_state]
    main = StringManager()
    main.write_str("int main(void) {", NL_SINGLE, IndentAction.INC)
    main.write_str(
        "// The CWP starts in the state the initial values put it in", NL_SINGLE
    )
    main.write_str(f"{INIT_FUNC}();", NL_SINGLE)
    main.write_str(f"#ifdef {REACHABILITY_MACRO}", NL_SINGLE)
    for name in cwp_states:
        main.write_str(
            f"__CPROVER_cover({CURRENT_STATE} == {STATE_PREFIX}{name}); /* cwp state {name} */",
            NL_SINGLE,
        )
    main.write_str("#endif", NL_SINGLE)
    main.write_str(
        f"for (unsigned int {STEP_VAR} = 0; {STEP_VAR} < {BOUND_MACRO}; {STEP_VAR}++) {{",
        NL_SINGLE,
        IndentAction.INC,
    )
    main.write_str(f"if ({bpmn_visitor.all_ended}) break;", NL_SINGLE)
    main.write_str(bpmn_visitor.pass_code, NL_SINGLE)
    main.write_str(f"#ifdef {REACHABILITY_MACRO}", NL_SINGLE)
    for name in cwp_states:
        main.write_str(
            f"__CPROVER_cover({CURRENT_STATE} == {STATE_PREFIX}{name}); /* cwp state {name} */",
            NL_SINGLE,
        )
    for cover in end_covers:
        main.write_str(cover, NL_SINGLE)
    main.write_str("#endif", NL_SINGLE)
    main.write_str("}", NL_SINGLE, IndentAction.DEC)
    main.write_str("return 0;", NL_SINGLE)
    main.write_str("}", NL_SINGLE, IndentAction.DEC)
    return str(main)


def _generate_cbmc(state: State, cwp: Cwp, bpmn: Bpmn) -> Result[CbmcProgram, Error]:
    if not bpmn.processes:
        return Failure(CbmcBuildError("the BPMN has no processes"))

    cwp_visitor = CwpCbmcVisitor()
    cwp.accept(cwp_visitor)

    bpmn_visitor = CbmcBpmnGenVisitor()
    bpmn.accept(bpmn_visitor)
    result: Result[CbmcBpmnGenVisitor, Error] = bpmn_visitor.result()
    if isinstance(result, Failure):
        return result

    bound = compute_bound(bpmn)
    code = (
        "#include <assert.h>\n\n"
        f"#define {BOUND_MACRO} {bound}\n\n"
        f"{_generate_state_c(state)}"
        f"{cwp_visitor}"
        f"{bpmn_visitor}\n"
        f"{_generate_main(bpmn_visitor, bound, _end_event_covers(bpmn, bpmn_visitor), cwp_visitor)}"
    )
    return Success(CbmcProgram(code, bound))


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

    def build(self) -> Result[CbmcProgram, Error]:
        result: Result[CbmcProgram, Error] = self.state.bind(  # pyright: ignore[reportUnknownMemberType]
            lambda state: self.cwp.bind(  # pyright: ignore[reportUnknownMemberType]
                lambda cwp: self.bpmn.bind(  # pyright: ignore[reportUnknownMemberType]
                    lambda bpmn: _generate_cbmc(state, cwp, bpmn)
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
