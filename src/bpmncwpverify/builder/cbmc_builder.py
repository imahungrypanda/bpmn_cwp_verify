from returns.result import Failure, Result, Success

from bpmncwpverify.builder.cbmc_bound import compute_cbmc_bound
from bpmncwpverify.core.bpmn import Bpmn
from bpmncwpverify.core.cwp import Cwp
from bpmncwpverify.core.error import CbmcBuildError, Error, NotInitializedError
from bpmncwpverify.core.state import State
from bpmncwpverify.util.stringmanager import NL_SINGLE, IndentAction, StringManager
from bpmncwpverify.visitors.bpmn_cbmc_visitor import STEP_FUNC_NAME, CbmcBpmnVisitor
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    CALCULATE_FUNC,
    CwpCbmcVisitor,
)

HEADERS = "#include <stdbool.h>\n\n"
BOUND_MACRO = "BPMN_BOUND"

_C_TYPES = {
    "bit": "_Bool",
    "bool": "_Bool",
    "byte": "unsigned char",
    "short": "short",
    "int": "int",
}


class CbmcProgram:
    """
    The generated C and the number of passes of its main loop. CBMC should be
    run with `--unwind` set to `unwind`.
    """

    __slots__ = ["c_code", "bound"]

    def __init__(self, c_code: str, bound: int) -> None:
        self.c_code = c_code
        self.bound = bound

    @property
    def unwind(self) -> int:
        return self.bound + 1


def _generate_state_c(state: State) -> str:
    lines: list[str] = ["//**********VARIABLE DECLARATION************//"]
    for const_decl in state.consts:
        lines.append(f"#define {const_decl.id} {const_decl.init.value}")
    enum_ids = {enum.id for enum in state.enums}
    for enum_decl in state.enums:
        values = ", ".join(sorted(value.value for value in enum_decl.values))
        lines.append(f"enum {enum_decl.id} {{ {values} }};")
    for var_decl in state.vars:
        if var_decl.type_ in enum_ids:
            c_type = f"enum {var_decl.type_}"
        else:
            c_type = _C_TYPES.get(var_decl.type_, var_decl.type_)
        lines.append(f"{c_type} {var_decl.id} = {var_decl.init.value};")
    return "\n".join(lines) + "\n\n"


def _generate_cwp_c(cwp: Cwp) -> str:
    visitor = CwpCbmcVisitor()
    cwp.accept(visitor)
    return str(visitor)


def _generate_main(bound: int, all_ended: str) -> str:
    sm = StringManager()
    sm.write_str(f"#define {BOUND_MACRO} {bound}u", NL_SINGLE)
    sm.write_str("int main(void) {", NL_SINGLE, IndentAction.INC)
    sm.write_str(f"{CALCULATE_FUNC}();", NL_SINGLE)
    sm.write_str(
        f"for (unsigned int pass = 0; pass < {BOUND_MACRO} && !({all_ended}); pass++) {{",
        NL_SINGLE,
        IndentAction.INC,
    )
    sm.write_str(f"{STEP_FUNC_NAME}();", NL_SINGLE, IndentAction.DEC)
    sm.write_str("}", NL_SINGLE)
    sm.write_str("return 0;", NL_SINGLE, IndentAction.DEC)
    sm.write_str("}", NL_SINGLE)
    return str(sm)


def _generate_c(state: State, cwp: Cwp, bpmn: Bpmn) -> Result[CbmcProgram, Error]:
    if not bpmn.processes:
        return Failure(CbmcBuildError("the BPMN has no processes"))
    bpmn_visitor = CbmcBpmnVisitor()
    bpmn.accept(bpmn_visitor)
    if bpmn_visitor.errors:
        return Failure(bpmn_visitor.errors[0])
    cwp_c = _generate_cwp_c(cwp)
    bound = compute_cbmc_bound(bpmn)
    main_c = _generate_main(bound, bpmn_visitor.all_ended)
    c_code = f"{HEADERS}{_generate_state_c(state)}{cwp_c}{bpmn_visitor!r}{main_c}"
    return Success(CbmcProgram(c_code, bound))


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
        return self.build_program().map(lambda program: program.c_code)

    def with_bpmn(self, bpmn: Bpmn) -> "CbmcBuilder":
        self.bpmn = Success(bpmn)
        return self

    def with_cwp(self, cwp: Cwp) -> "CbmcBuilder":
        self.cwp = Success(cwp)
        return self

    def with_state(self, state: State) -> "CbmcBuilder":
        self.state = Success(state)
        return self
