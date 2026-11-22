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
from bpmncwpverify.visitors.bpmn_cbmc_visitor import (
    STEP_FUNC,
    BpmnCbmcVisitor,
)
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    CALCULATE_STATE_FUNC,
    CwpCbmcVisitor,
)

_C_TYPES = {
    "bit": "_Bool",
    "bool": "_Bool",
    "byte": "unsigned char",
    "short": "short",
    "int": "int",
}


class CbmcProgram:
    """The C program, and the bound CBMC has to be run with."""

    __slots__ = ["bound", "source"]

    def __init__(self, source: str, bound: int) -> None:
        self.source = source
        self.bound = bound

    @property
    def unwind(self) -> int:
        """Value for CBMC's `--unwind`: one more than the bound, so CBMC can check the loop stops."""
        return self.bound + 1


def _generate_state_c(state: State) -> Result[str, Error]:
    enum_ids = {enum.id for enum in state.enums}
    lines = ["//**********VARIABLE DECLARATION************//"]
    for const_decl in state.consts:
        lines.append(f"#define {const_decl.id} {const_decl.init.value}")
    for enum_decl in state.enums:
        values = ", ".join(sorted(value.value for value in enum_decl.values))
        lines.append(f"enum {{ {values} }};")
    for var_decl in state.vars:
        if var_decl.type_ in enum_ids:
            c_type = "int"
        elif var_decl.type_ in _C_TYPES:
            c_type = _C_TYPES[var_decl.type_]
        else:
            return Failure(
                CbmcBuildError(
                    f"Variable '{var_decl.id}' has type '{var_decl.type_}', which has no C type."
                )
            )
        lines.append(f"{c_type} {var_decl.id} = {var_decl.init.value};")
    return Success("\n".join(lines) + "\n\n")


def _generate_main(bound: int, done_expr: str) -> str:
    sm = StringManager()
    sm.write_str(f"#define BOUND {bound}u", NL_DOUBLE)
    sm.write_str("int main(void) {", NL_SINGLE, IndentAction.INC)
    sm.write_str(f"{CALCULATE_STATE_FUNC}();", NL_SINGLE)
    sm.write_str(
        "for (unsigned int pass = 0; pass < BOUND; pass++) {",
        NL_SINGLE,
        IndentAction.INC,
    )
    sm.write_str(f"if ({done_expr}) break;", NL_SINGLE)
    sm.write_str(f"{STEP_FUNC}();", NL_SINGLE)
    sm.write_str("}", NL_SINGLE, IndentAction.DEC)
    sm.write_str("return 0;", NL_SINGLE)
    sm.write_str("}", NL_SINGLE, IndentAction.DEC)
    return str(sm)


def _generate_c(state: State, cwp: Cwp, bpmn: Bpmn) -> Result[CbmcProgram, Error]:
    vars_c = _generate_state_c(state)
    if isinstance(vars_c, Failure):
        return vars_c
    cwp_visitor = CwpCbmcVisitor()
    cwp.accept(cwp_visitor)
    bpmn_visitor = BpmnCbmcVisitor()
    bpmn.accept(bpmn_visitor)
    bpmn_c = bpmn_visitor.get_result()
    if isinstance(bpmn_c, Failure):
        return bpmn_c
    bound = compute_bound(bpmn)
    main_c = _generate_main(bound, bpmn_visitor.done_expr)
    source = f"{vars_c.unwrap()}{cwp_visitor}{bpmn_c.unwrap()}{main_c}"
    return Success(CbmcProgram(source, bound))


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
