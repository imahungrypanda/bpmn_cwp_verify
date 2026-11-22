import re

from returns.result import Failure, Result, Success

from bpmncwpverify.builder.cbmc_bound import compute_bound
from bpmncwpverify.core.bpmn import Bpmn
from bpmncwpverify.core.cwp import Cwp
from bpmncwpverify.core.error import CbmcBuildError, Error, NotInitializedError
from bpmncwpverify.core.state import State
from bpmncwpverify.util.stringmanager import NL_SINGLE, IndentAction, StringManager
from bpmncwpverify.visitors.bpmn_cbmc_visitor import OCCUPIED_MSG, CbmcBpmnGenVisitor
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    CALCULATE_FUNC,
    STATE_PREFIX,
    STATE_VAR,
    UPDATE_FUNC,
    CwpCbmcVisitor,
)

_C_TYPES = {
    "bit": "unsigned char",
    "bool": "bool",
    "byte": "unsigned char",
    "int": "int",
    "short": "short",
}


COVER_FUNC = "cover_cwp_states"
COVER_MARK = "cover:"


def _generate_cwp_c(cwp: Cwp) -> tuple[str, list[str]]:
    """The CWP's C and the names of the states that start out unreached"""
    visitor = CwpCbmcVisitor()
    cwp.accept(visitor)
    # The start state is never made the active state in C: the initial values
    # put the CWP straight into the state after it, so only the others are covered
    start = cwp.start_state.name
    names = [state.name for state in visitor.states if state.name != start]
    return str(visitor), names


def _generate_cover_func(state_names: list[str]) -> str:
    # One function, so each state has a single cover however often it is called
    lines = [f"static void {COVER_FUNC}(void) {{", "#ifdef REACHABILITY"]
    for name in state_names:
        lines.append(
            f"\t__CPROVER_cover({STATE_VAR} == {STATE_PREFIX}{name}); /* {COVER_MARK} CWP state {name} */"
        )
    lines += ["#endif", "}", "", ""]
    return "\n".join(lines)


def _generate_state_c(state: State) -> str:
    enums = {enum.id for enum in state.enums}

    def c_type(type_: str) -> str:
        return f"enum {type_}" if type_ in enums else _C_TYPES.get(type_, type_)

    lines = ["//**********VARIABLE DECLARATION************//"]
    for const_decl in state.consts:
        lines.append(f"#define {const_decl.id} {const_decl.init.value}")
    for enum_decl in state.enums:
        values = ", ".join(sorted(value.value for value in enum_decl.values))
        lines.append(f"enum {enum_decl.id} {{ {values} }};")
    for var_decl in state.vars:
        type_ = c_type(var_decl.type_)
        lines.append(f"static {type_} {var_decl.id} = {var_decl.init.value};")
        lines.append(f"static {type_} old_{var_decl.id} = {var_decl.id};")
    return "\n".join(lines) + "\n\n"


_OCCUPIED_ASSERT = re.compile(
    r'__CPROVER_assert\(!\((?P<places>.*)\), "' + re.escape(OCCUPIED_MSG) + r'"\);'
)
OCCUPIED_VAR = "occupied"


def _hoist_occupied_checks(step: list[str]) -> tuple[list[str], bool]:
    """
    The visitor asserts in every transition that its outgoing places are free.
    CBMC checks each of those on every pass, so instead each transition records
    whether it hit an occupied place and the pass asserts that once, after the
    transition ran.
    """
    hoisted = False
    lines: list[str] = []
    for line in step:
        match = _OCCUPIED_ASSERT.search(line)
        if match:
            hoisted = True
            line = _OCCUPIED_ASSERT.sub(
                lambda m: f"{OCCUPIED_VAR} = ({m['places']});", line
            )
        lines.append(line)
    return lines, hoisted


def _generate_main(state: State, visitor: CbmcBpmnGenVisitor, bound: int) -> str:
    main = StringManager()
    main.write_str("int main(void) {", NL_SINGLE, IndentAction.INC)
    for stmt in str(visitor.init).splitlines():
        main.write_str(stmt, NL_SINGLE)
    # Like the SPIN init block: the CWP starts in the state the initial values give
    main.write_str(f"{CALCULATE_FUNC}();", NL_SINGLE)
    main.write_str(f"{COVER_FUNC}();", NL_SINGLE)
    main.write_str(
        f"for (unsigned int pass = 0; pass < {bound}u && !({visitor.all_ended}); pass++) {{",
        NL_SINGLE,
        IndentAction.INC,
    )
    step, hoisted = _hoist_occupied_checks(str(visitor.step).splitlines())
    if hoisted:
        main.write_str(f"bool {OCCUPIED_VAR} = false;", NL_SINGLE)
    for stmt in step:
        main.write_str(stmt, NL_SINGLE)
    if hoisted:
        main.write_str(
            f'__CPROVER_assert(!{OCCUPIED_VAR}, "{OCCUPIED_MSG}");', NL_SINGLE
        )
    main.write_str("#ifdef REACHABILITY", NL_SINGLE)
    for index, transition in enumerate(visitor.transitions):
        if transition.label.startswith("end event "):
            name = transition.label.removeprefix("end event ")
            main.write_str(
                f"__CPROVER_cover(transition == {index}u); /* {COVER_MARK} end event {name} */",
                NL_SINGLE,
            )
    main.write_str("#endif", NL_SINGLE)
    changed = " || ".join(f"{var.id} != old_{var.id}" for var in state.vars)
    if changed:
        main.write_str(f"if ({changed}) {{", NL_SINGLE, IndentAction.INC)
        main.write_str(f"{UPDATE_FUNC}();", NL_SINGLE)
        for var in state.vars:
            main.write_str(f"old_{var.id} = {var.id};", NL_SINGLE)
        main.write_str("}", NL_SINGLE, IndentAction.DEC)
    main.write_str(f"{COVER_FUNC}();", NL_SINGLE)
    main.write_str("}", NL_SINGLE, IndentAction.DEC)
    main.write_str("return 0;", NL_SINGLE)
    main.write_str("}", NL_SINGLE, IndentAction.DEC)
    return str(main)


def _generate_c(state: State, cwp: Cwp, bpmn: Bpmn) -> Result[str, Error]:
    try:
        bpmn_visitor = CbmcBpmnGenVisitor()
        bpmn.accept(bpmn_visitor)
        cwp_c, state_names = _generate_cwp_c(cwp)
    except Exception as e:
        if e.args and isinstance(e.args[0], Error):
            return Failure(e.args[0])
        return Failure(CbmcBuildError(str(e)))
    bound = compute_bound(bpmn)
    return Success(
        "#include <stdbool.h>\n\n"
        f"{_generate_state_c(state)}{cwp_c}{_generate_cover_func(state_names)}{bpmn_visitor.defs}\n"
        f"// cbmc --unwind {bound + 1}\n"
        f"{_generate_main(state, bpmn_visitor, bound)}"
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

    def unwind(self) -> Result[int, Error]:
        """
        The value to give CBMC's --unwind: the bound plus one, so CBMC checks
        the loop really stops at the bound
        """
        return self.bound().map(lambda bound: bound + 1)

    def bound(self) -> Result[int, Error]:
        """
        The number of passes of the main loop
        """
        return self.bpmn.map(compute_bound)

    def with_bpmn(self, bpmn: Bpmn) -> "CbmcBuilder":
        self.bpmn = Success(bpmn)
        return self

    def with_cwp(self, cwp: Cwp) -> "CbmcBuilder":
        self.cwp = Success(cwp)
        return self

    def with_state(self, state: State) -> "CbmcBuilder":
        self.state = Success(state)
        return self
