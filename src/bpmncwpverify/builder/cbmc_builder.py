from returns.result import Failure, Result, Success

from bpmncwpverify.builder.cbmc_bound import DEFAULT_RETRIES, compute_unwinding_bound
from bpmncwpverify.core.bpmn import Bpmn
from bpmncwpverify.core.cwp import Cwp
from bpmncwpverify.core.error import CbmcBuildError, Error, NotInitializedError
from bpmncwpverify.core.state import State
from bpmncwpverify.util.stringmanager import NL_SINGLE, IndentAction, StringManager
from bpmncwpverify.visitors.bpmn_cbmc_visitor import (
    STEP_FUNC_NAME,
    CbmcGenVisitor,
)
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    INIT_FUNC,
    UPDATE_FUNC,
    CwpCbmcVisitor,
)

BOUND_MACRO = "MAX_PASSES"
PASS_VAR = "pass_count"
C_TYPES = {
    "bit": "unsigned char",
    "bool": "bool",
    "byte": "unsigned char",
    "int": "int",
    "short": "short",
}


class CbmcOutputs:
    """
    The C program, and the bound it needs: pass `unwind` to `cbmc --unwind`.
    """

    __slots__ = ["c", "bound"]

    def __init__(self, c: str, bound: int) -> None:
        self.c = c
        self.bound = bound

    @property
    def unwind(self) -> int:
        return self.bound + 1


def _c_type(state: State, type_: str) -> Result[str, Error]:
    if type_ in C_TYPES:
        return Success(C_TYPES[type_])
    if type_ in {enum.id for enum in state.enums}:
        return Success(f"enum {type_}")
    return Failure(CbmcBuildError(f"variable type '{type_}' has no C equivalent"))


def _generate_state_c(state: State) -> Result[str, Error]:
    lines: list[str] = ["//**********VARIABLE DECLARATION************//"]
    for const_decl in state.consts:
        lines.append(f"#define {const_decl.id} {const_decl.init.value}")
    for enum_decl in state.enums:
        values = ", ".join(value.value for value in enum_decl.values)
        lines.append(f"enum {enum_decl.id} {{{values}}};")
    for var_decl in state.vars:
        c_type = _c_type(state, var_decl.type_)
        if not isinstance(c_type, Success):
            return c_type
        lines.append(f"static {c_type.unwrap()} {var_decl.id} = {var_decl.init.value};")
        lines.append(
            f"static {c_type.unwrap()} old_{var_decl.id} = {var_decl.init.value};"
        )
    return Success("\n".join(lines) + "\n\n")


def _generate_main(state: State, bpmn_all_ended: str) -> str:
    changed = " || ".join(f"{v.id} != old_{v.id}" for v in state.vars) or "0"
    sm = StringManager()
    sm.write_str("int main(void) {", NL_SINGLE, IndentAction.INC)
    # The CWP starts in the state the initial variable values put it in
    sm.write_str(f"{INIT_FUNC}();", NL_SINGLE)
    sm.write_str(
        f"for (unsigned int {PASS_VAR} = 0; "
        f"{PASS_VAR} < {BOUND_MACRO} && !({bpmn_all_ended}); {PASS_VAR}++) {{",
        NL_SINGLE,
        IndentAction.INC,
    )
    sm.write_str(f"{STEP_FUNC_NAME}();", NL_SINGLE)
    # The CWP moves once per pass, and only if the task changed a variable
    sm.write_str(f"if ({changed}) {{", NL_SINGLE, IndentAction.INC)
    sm.write_str(f"{UPDATE_FUNC}();", NL_SINGLE)
    for var in state.vars:
        sm.write_str(f"old_{var.id} = {var.id};", NL_SINGLE)
    sm.write_str("}", NL_SINGLE, IndentAction.DEC)
    sm.write_str("}", NL_SINGLE, IndentAction.DEC)
    sm.write_str("return 0;", NL_SINGLE)
    sm.write_str("}", NL_SINGLE, IndentAction.DEC)
    return str(sm)


def _generate_c(
    state: State, cwp: Cwp, bpmn: Bpmn, retries: int
) -> Result[CbmcOutputs, Error]:
    if not cwp.states:
        return Failure(CbmcBuildError("the CWP has no states"))

    cwp_visitor = CwpCbmcVisitor()
    cwp.accept(cwp_visitor)

    bpmn_visitor = CbmcGenVisitor()
    bpmn.accept(bpmn_visitor)

    bound = compute_unwinding_bound(bpmn, retries)

    def assemble(bpmn_c: str, state_c: str) -> CbmcOutputs:
        c = (
            "#include <assert.h>\n#include <stdbool.h>\n\n"
            f"{state_c}"
            f"#define {BOUND_MACRO} {bound}u\n\n"
            f"{cwp_visitor.declarations}\n"
            f"{bpmn_c}\n"
            f"{cwp_visitor.init_function}{cwp_visitor.update_function}"
            f"{_generate_main(state, bpmn_visitor.all_ended)}"
        )
        return CbmcOutputs(c, bound)

    return bpmn_visitor.result().bind(  # pyright: ignore[reportUnknownMemberType]
        lambda bpmn_c: _generate_state_c(state).map(
            lambda state_c: assemble(bpmn_c, state_c)
        )
    )


class CbmcBuilder:
    __slots__ = ["bpmn", "cwp", "state", "retries"]

    def __init__(self) -> None:
        self.bpmn: Result[Bpmn, Error] = Failure(
            NotInitializedError("CbmcBuilder.bpmn")
        )
        self.cwp: Result[Cwp, Error] = Failure(NotInitializedError("CbmcBuilder.cwp"))
        self.state: Result[State, Error] = Failure(
            NotInitializedError("CbmcBuilder.state")
        )
        self.retries = DEFAULT_RETRIES

    def build(self) -> Result[CbmcOutputs, Error]:
        result: Result[CbmcOutputs, Error] = self.state.bind(  # pyright: ignore[reportUnknownMemberType]
            lambda state: self.cwp.bind(  # pyright: ignore[reportUnknownMemberType]
                lambda cwp: self.bpmn.bind(  # pyright: ignore[reportUnknownMemberType]
                    lambda bpmn: _generate_c(state, cwp, bpmn, self.retries)
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

    def with_retries(self, retries: int) -> "CbmcBuilder":
        self.retries = retries
        return self

    def with_state(self, state: State) -> "CbmcBuilder":
        self.state = Success(state)
        return self
