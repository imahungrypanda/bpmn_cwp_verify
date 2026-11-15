from returns.result import Failure, Result, Success

from bpmncwpverify.builder.cbmc_bound import get_unwinding_bound
from bpmncwpverify.core.bpmn import Bpmn
from bpmncwpverify.core.cwp import Cwp
from bpmncwpverify.core.error import CbmcBuildError, Error, NotInitializedError
from bpmncwpverify.core.state import State
from bpmncwpverify.util.stringmanager import NL_SINGLE, IndentAction, StringManager
from bpmncwpverify.visitors.bpmn_cbmc_visitor import (
    CHOICE_VAR,
    CbmcGenVisitor,
)
from bpmncwpverify.visitors.cwp_cbmc_visitor import CwpCbmcVisitor

PRELUDE_STR = (
    "#include <assert.h>\n#include <stdbool.h>\n\nunsigned int nondet_uint(void);\n"
)
STEP_VAR = "step"

_C_TYPES = {
    "bit": "bool",
    "bool": "bool",
    "byte": "unsigned char",
    "short": "short",
    "int": "int",
}


class CbmcProgram:
    """The C program, and the bound CBMC needs to check it."""

    __slots__ = ["source", "bound"]

    def __init__(self, source: str, bound: int) -> None:
        self.source = source
        self.bound = bound

    @property
    def unwind(self) -> int:
        """The value for CBMC's --unwind: one more than the passes of the loop."""
        return self.bound + 1


def _generate_state_c(state: State) -> str:
    enum_ids = {enum.id for enum in state.enums}
    lines = ["//**********VARIABLE DECLARATION************//"]
    for const_decl in state.consts:
        lines.append(f"#define {const_decl.id} {const_decl.init.value}")
    for enum_decl in state.enums:
        values = ", ".join(sorted(value.value for value in enum_decl.values))
        lines.append(f"enum {enum_decl.id} {{ {values} }};")
    for var_decl in state.vars:
        c_type = (
            f"enum {var_decl.type_}"
            if var_decl.type_ in enum_ids
            else _C_TYPES.get(var_decl.type_, var_decl.type_)
        )
        lines.append(f"{c_type} {var_decl.id} = {var_decl.init.value};")
    return "\n".join(lines) + "\n\n"


def _cwp_covers(cwp_visitor: CwpCbmcVisitor) -> list[str]:
    # The start state is never made the active state: the initial values put the
    # CWP straight into the state after it, so it starts out reached
    return [
        f"__CPROVER_cover(cwp_state == {cwp_visitor._enum_name(state)});"  # pyright: ignore[reportPrivateUsage]
        for state in cwp_visitor.tracked_states
        if state is not cwp_visitor.start_state
    ]


def _cwp_cover_function(cwp_visitor: CwpCbmcVisitor) -> str:
    # One function, so each state has one cover however many places call it
    lines = ["static void cwp_cover(void) {", *_cwp_covers(cwp_visitor), "}"]
    return "\n".join(_ifdef_reachability(lines)) + "\n\n"


def _end_event_covers(bpmn_visitor: CbmcGenVisitor) -> list[str]:
    return [
        f"__CPROVER_cover({CHOICE_VAR} == {index}u); /* {t.element_id} */"
        for index, t in enumerate(bpmn_visitor.transitions)
        if _ends_process(t.body)
    ]


def _ends_process(body: list[str]) -> bool:
    return any(line.startswith("ended_") and line.endswith(" = 1;") for line in body)


def _ifdef_reachability(lines: list[str]) -> list[str]:
    if not lines:
        return []
    return ["#ifdef REACHABILITY", *lines, "#endif"]


def _generate_main(
    bpmn_visitor: CbmcGenVisitor, cwp_visitor: CwpCbmcVisitor, bound: int
) -> str:
    main = StringManager()
    main.write_str("int main(void) {", NL_SINGLE, IndentAction.INC)
    # The CWP starts in the state the initial variable values put it in
    main.write_str("cwp_calculate_state();", NL_SINGLE)
    for line in _ifdef_reachability(["cwp_cover();"]):
        main.write_str(line, NL_SINGLE)
    main.write_str(
        f"for (unsigned int {STEP_VAR} = 0; {STEP_VAR} < {bound}u; {STEP_VAR}++) {{",
        NL_SINGLE,
        IndentAction.INC,
    )
    main.write_str(f"if ({bpmn_visitor.all_ended_expr()}) break;", NL_SINGLE)
    for line in bpmn_visitor.pass_code().splitlines():
        main.write_str(line, NL_SINGLE)
    main.write_str("cwp_update_state();", NL_SINGLE)
    for line in _ifdef_reachability(["cwp_cover();", *_end_event_covers(bpmn_visitor)]):
        main.write_str(line, NL_SINGLE)
    main.write_str("}", NL_SINGLE, IndentAction.DEC)
    main.write_str("return 0;", NL_SINGLE)
    main.write_str("}", NL_SINGLE, IndentAction.DEC)
    return repr(main)


def _generate_c(state: State, cwp: Cwp, bpmn: Bpmn) -> Result[CbmcProgram, Error]:
    if getattr(cwp, "start_state", None) is None:
        return Failure(CbmcBuildError("the CWP has no start state"))
    cwp_visitor = CwpCbmcVisitor()
    cwp.accept(cwp_visitor)
    bpmn_visitor = CbmcGenVisitor()
    bpmn.accept(bpmn_visitor)
    bound = get_unwinding_bound(bpmn)

    def program(visitor: CbmcGenVisitor) -> CbmcProgram:
        source = (
            f"{PRELUDE_STR}\n{_generate_state_c(state)}{cwp_visitor}"
            f"{_cwp_cover_function(cwp_visitor)}"
            f"{visitor.declarations()}\n{_generate_main(visitor, cwp_visitor, bound)}"
        )
        return CbmcProgram(source, bound)

    return bpmn_visitor.result().map(program)


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

    def build_program(self) -> Result[CbmcProgram, Error]:
        result: Result[CbmcProgram, Error] = self.state.bind(  # pyright: ignore[reportUnknownMemberType]
            lambda state: self.cwp.bind(  # pyright: ignore[reportUnknownMemberType]
                lambda cwp: self.bpmn.bind(  # pyright: ignore[reportUnknownMemberType]
                    lambda bpmn: _generate_c(state, cwp, bpmn)
                )
            )
        )
        return result

    def build(self) -> Result[str, Error]:
        return self.build_program().map(lambda program: program.source)

    def with_bpmn(self, bpmn: Bpmn) -> "CbmcBuilder":
        self.bpmn = Success(bpmn)
        return self

    def with_cwp(self, cwp: Cwp) -> "CbmcBuilder":
        self.cwp = Success(cwp)
        return self

    def with_state(self, state: State) -> "CbmcBuilder":
        self.state = Success(state)
        return self
