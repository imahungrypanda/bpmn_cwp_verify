import re

from returns.result import Failure, Result, Success

from bpmncwpverify.builder.cbmc_bound import compute_unwind_bound
from bpmncwpverify.core.bpmn import Bpmn
from bpmncwpverify.core.cwp import Cwp
from bpmncwpverify.core.error import CbmcBuildError, Error, NotInitializedError
from bpmncwpverify.core.state import State
from bpmncwpverify.util.stringmanager import NL_SINGLE, IndentAction, StringManager
from bpmncwpverify.visitors.bpmn_cbmc_visitor import CbmcBpmnGenVisitor
from bpmncwpverify.visitors.cwp_cbmc_visitor import CwpCbmcVisitor

UNWIND_MACRO = "UNWIND_BOUND"

_C_TYPES = {
    "bit": "unsigned char",
    "bool": "bool",
    "byte": "unsigned char",
    "short": "short",
    "int": "int",
}


def _c_type(state: State, type_: str) -> str:
    if type_ in {enum.id for enum in state.enums}:
        return f"enum {type_}"
    return _C_TYPES.get(type_, type_)


def _generate_state_c(state: State) -> str:
    str_builder: list[str] = ["//**********VARIABLE DECLARATION************//"]
    for const_decl in state.consts:
        str_builder.append(f"#define {const_decl.id} {const_decl.init.value}")
    for enum_decl in state.enums:
        values = ", ".join(value.value for value in enum_decl.values)
        str_builder.append(f"enum {enum_decl.id} {{ {values} }};")
    for var_decl in state.vars:
        str_builder.append(
            f"{_c_type(state, var_decl.type_)} {var_decl.id} = {var_decl.init.value};"
        )
    return "\n".join(str_builder) + "\n\n"


def _generate_main(process_ids: list[str]) -> str:
    """
    A run initialises every process, then repeatedly lets one process, chosen
    nondeterministically, take a step, until nothing can move or the bound is
    reached. Nothing here loops over the processes, so `--unwind` only has to
    cover the outer loop.
    """
    main = StringManager()
    count = len(process_ids)
    main.write_str("static bool step_any_process(void) {", NL_SINGLE, IndentAction.INC)
    main.write_str(f"switch (nondet_uint() % {count}u) {{", NL_SINGLE)
    for first in range(count):
        order = process_ids[first:] + process_ids[:first]
        calls = " || ".join(f"{pid}_step()" for pid in order)
        main.write_str(f"case {first}u: return {calls};", NL_SINGLE)
    main.write_str("default: return false;", NL_SINGLE)
    main.write_str("}", NL_SINGLE)
    main.write_str("}", NL_SINGLE, IndentAction.DEC)
    main.write_str("", NL_SINGLE)
    main.write_str("int main(void) {", NL_SINGLE, IndentAction.INC)
    for pid in process_ids:
        main.write_str(f"{pid}_init();", NL_SINGLE)
    main.write_str(
        f"for (unsigned int i = 0; i + 1 < {UNWIND_MACRO}; i++) {{",
        NL_SINGLE,
        IndentAction.INC,
    )
    main.write_str("if (!step_any_process()) break;", NL_SINGLE)
    main.write_str("}", NL_SINGLE, IndentAction.DEC)
    main.write_str("return 0;", NL_SINGLE)
    main.write_str("}", NL_SINGLE, IndentAction.DEC)
    return str(main)


_STATE_ASSIGN = re.compile(r"^(\t+)(\w+) = \2_prime;$", re.MULTILINE)


def _add_state_coverage(cwp_c: str) -> str:
    """
    Marks every point where `updateState` makes a CWP state active with a
    `__CPROVER_cover`, so a run with `--cover cover` shows which states are
    never entered.
    """
    return _STATE_ASSIGN.sub(r"\g<0>\n\1__CPROVER_cover(\2);", cwp_c)


def _generate_c(
    state: State, cwp: Cwp, bpmn: Bpmn, state_coverage: bool = False
) -> Result[str, Error]:
    if not bpmn.processes:
        return Failure(CbmcBuildError("the BPMN has no processes"))

    bpmn_visitor = CbmcBpmnGenVisitor()
    bpmn.accept(bpmn_visitor)
    bpmn_c: Result[str, Error] = bpmn_visitor.result()
    if isinstance(bpmn_c, Failure):
        return bpmn_c

    cwp_visitor = CwpCbmcVisitor()
    cwp.accept(cwp_visitor)
    cwp_c = str(cwp_visitor)
    if state_coverage:
        cwp_c = _add_state_coverage(cwp_c)

    bound = compute_unwind_bound(bpmn)
    header = f"#include <assert.h>\n#include <stdbool.h>\n\n#define {UNWIND_MACRO} {bound}\n\n"
    return Success(
        f"{header}{_generate_state_c(state)}{cwp_c}{bpmn_c.unwrap()}"
        f"{_generate_main(bpmn_visitor.process_ids)}"
    )


class CbmcBuilder:
    __slots__ = [
        "bpmn",
        "cwp",
        "state",
        "state_coverage",
    ]

    def __init__(self) -> None:
        self.bpmn: Result[Bpmn, Error] = Failure(
            NotInitializedError("CbmcBuilder.bpmn")
        )
        self.cwp: Result[Cwp, Error] = Failure(NotInitializedError("CbmcBuilder.cwp"))
        self.state: Result[State, Error] = Failure(
            NotInitializedError("CbmcBuilder.state")
        )
        self.state_coverage: bool = False

    def build(self) -> Result[str, Error]:
        result: Result[str, Error] = self.state.bind(  # pyright: ignore[reportUnknownMemberType]
            lambda state: self.cwp.bind(  # pyright: ignore[reportUnknownMemberType]
                lambda cwp: self.bpmn.bind(  # pyright: ignore[reportUnknownMemberType]
                    lambda bpmn: _generate_c(state, cwp, bpmn, self.state_coverage)
                )
            )
        )
        return result

    def unwind_bound(self) -> Result[int, Error]:
        """
        The `--unwind` value to pass to CBMC for the program `build()` makes.
        It is also defined in that program as `UNWIND_BOUND`.
        """
        result: Result[int, Error] = self.bpmn.map(compute_unwind_bound)
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

    def with_state_coverage(self, state_coverage: bool) -> "CbmcBuilder":
        self.state_coverage = state_coverage
        return self
