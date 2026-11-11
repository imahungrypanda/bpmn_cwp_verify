from returns.result import Failure, Result, Success

from bpmncwpverify.builder.cbmc_bound import compute_unwinding_bound
from bpmncwpverify.core.bpmn import Bpmn
from bpmncwpverify.core.cwp import Cwp
from bpmncwpverify.core.error import CbmcBuildError, Error, NotInitializedError
from bpmncwpverify.core.state import State
from bpmncwpverify.util.stringmanager import NL_SINGLE, IndentAction, StringManager
from bpmncwpverify.visitors.bpmn_cbmc_visitor import (
    HELPER_DEFS_STR,
    CbmcBpmnGenVisitor,
)
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    INIT_FUNC,
    UPDATE_FUNC,
    CwpCbmcVisitor,
)

STEP_VAR = "bpmn_step"
_C_TYPES = {
    "bit": "unsigned char",
    "bool": "bool",
    "byte": "unsigned char",
    "int": "int",
    "short": "short",
}


def _generate_state_c(state: State) -> Result[str, Error]:
    enum_ids = {enum.id for enum in state.enums}
    lines = ["//**********VARIABLE DECLARATION************//"]
    for const_decl in state.consts:
        lines.append(f"#define {const_decl.id} {const_decl.init.value}")
    for enum_decl in state.enums:
        values = ", ".join(sorted(value.value for value in enum_decl.values))
        lines.append(f"typedef enum {{ {values} }} {enum_decl.id};")
    for var_decl in state.vars:
        if var_decl.type_ in enum_ids:
            c_type = var_decl.type_
        elif var_decl.type_ in _C_TYPES:
            c_type = _C_TYPES[var_decl.type_]
        else:
            return Failure(
                CbmcBuildError(
                    f"variable '{var_decl.id}' has type '{var_decl.type_}' with no C equivalent"
                )
            )
        lines.append(f"{c_type} {var_decl.id} = {var_decl.init.value};")
    return Success("\n".join(lines) + "\n\n")


def _generate_main(bpmn_visitor: CbmcBpmnGenVisitor, bound: int) -> str:
    out = StringManager()
    out.write_str("int main(void) {", NL_SINGLE, IndentAction.INC)
    # Like the Promela init block: the CWP starts in the state the initial
    # variable values put it in, before any process runs
    out.write_str(f"{INIT_FUNC}();", NL_SINGLE)
    out.write_str(
        f"for (unsigned int {STEP_VAR} = 0; {STEP_VAR} < {bound}u; {STEP_VAR}++) {{",
        NL_SINGLE,
        IndentAction.INC,
    )
    out.write_str(f"if ({bpmn_visitor.all_ended_expr()}) break;", NL_SINGLE)
    out.write_str(bpmn_visitor.gen_pass(), NL_SINGLE)
    out.write_str(f"{UPDATE_FUNC}();", NL_SINGLE)
    out.write_str("}", NL_SINGLE, IndentAction.DEC)
    out.write_str("return 0;", NL_SINGLE)
    out.write_str("}", NL_SINGLE, IndentAction.DEC)
    return str(out)


def _generate_c(state: State, cwp: Cwp, bpmn: Bpmn) -> Result[str, Error]:
    state_c = _generate_state_c(state)
    if isinstance(state_c, Failure):
        return state_c
    cwp_visitor = CwpCbmcVisitor()
    cwp.accept(cwp_visitor)
    bpmn_visitor = CbmcBpmnGenVisitor()
    bpmn.accept(bpmn_visitor)
    checked = bpmn_visitor.get_result()
    if isinstance(checked, Failure):
        return checked
    bound = compute_unwinding_bound(bpmn)
    return Success(
        f"{HELPER_DEFS_STR}\n{state_c.unwrap()}{cwp_visitor}\n"
        f"{bpmn_visitor.gen_defs()}\n{_generate_main(bpmn_visitor, bound)}"
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
        """
        The number of passes main()'s loop makes at most. Pass `bound + 1` to
        CBMC as `--unwind`.
        """
        return self.bpmn.map(compute_unwinding_bound)  # pyright: ignore[reportUnknownMemberType]

    def with_bpmn(self, bpmn: Bpmn) -> "CbmcBuilder":
        self.bpmn = Success(bpmn)
        return self

    def with_cwp(self, cwp: Cwp) -> "CbmcBuilder":
        self.cwp = Success(cwp)
        return self

    def with_state(self, state: State) -> "CbmcBuilder":
        self.state = Success(state)
        return self
