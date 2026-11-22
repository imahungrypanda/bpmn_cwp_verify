from returns.result import Failure, Result, Success

from bpmncwpverify.builder.cbmc_bound import compute_bound
from bpmncwpverify.core.bpmn import Bpmn, BpmnVisitor, EndEvent
from bpmncwpverify.core.cwp import Cwp, CwpState, CwpVisitor
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
    place_name,
)
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    CALCULATE_FUNC,
    STATE_VAR,
    UPDATE_FUNC,
    CwpCbmcVisitor,
)

BOUND_MACRO = "BPMN_BOUND"
REACHABILITY_MACRO = "REACHABILITY"
COVER_FUNC = "check_reachability"

_C_TYPES = {
    "bit": "unsigned char",
    "bool": "bool",
    "byte": "unsigned char",
    "short": "short",
    "int": "int",
}


def _generate_state_c(state: State) -> Result[str, Error]:
    enum_ids = {enum.id for enum in state.enums}
    out = StringManager()
    out.write_str("#include <stdbool.h>", NL_SINGLE)
    out.write_str("//**********VARIABLE DECLARATION************//", NL_SINGLE)
    for const_decl in state.consts:
        out.write_str(f"#define {const_decl.id} {const_decl.init.value}", NL_SINGLE)
    for enum_decl in state.enums:
        values = ", ".join(value.value for value in enum_decl.values)
        out.write_str(f"typedef enum {{ {values} }} {enum_decl.id};", NL_SINGLE)
    for var_decl in state.vars:
        if var_decl.type_ in enum_ids:
            c_type = var_decl.type_
        elif var_decl.type_ in _C_TYPES:
            c_type = _C_TYPES[var_decl.type_]
        else:
            return Failure(
                CbmcBuildError(
                    f"variable '{var_decl.id}' has type '{var_decl.type_}', "
                    "which has no C equivalent"
                )
            )
        out.write_str(f"{c_type} {var_decl.id} = {var_decl.init.value};", NL_SINGLE)
    out.write_str("", NL_SINGLE)
    return Success(str(out))


def _generate_cwp_c(cwp: Cwp) -> str:
    visitor = CwpCbmcVisitor()
    cwp.accept(visitor)
    return str(visitor)


def _generate_bpmn_c(bpmn: Bpmn) -> Result[str, Error]:
    visitor = BpmnCbmcVisitor()
    bpmn.accept(visitor)
    return visitor.get_result()


class _CwpStateCollector(CwpVisitor):
    def __init__(self) -> None:
        self.states: list[CwpState] = []

    def visit_state(self, state: CwpState) -> bool:
        self.states.append(state)
        return True


class _EndEventCollector(BpmnVisitor):
    def __init__(self) -> None:
        self.events: list[EndEvent] = []

    def visit_end_event(self, event: EndEvent) -> bool:
        self.events.append(event)
        return True


def _generate_cover(cwp: Cwp, bpmn: Bpmn) -> str:
    """
    One `__CPROVER_cover` per end event and per CWP state, behind `REACHABILITY`
    so that only the reachability run sees them. The CWP's start state is left
    out: the initial values put the CWP into the state after it.
    """
    states = _CwpStateCollector()
    cwp.accept(states)
    ends = _EndEventCollector()
    bpmn.accept(ends)

    out = StringManager()
    out.write_str(f"#ifdef {REACHABILITY_MACRO}", NL_SINGLE)
    out.write_str(f"static void {COVER_FUNC}(void) {{", NL_SINGLE, IndentAction.INC)
    for event in ends.events:
        parts = [place_name(msg.id) for msg in event.in_msgs]
        if event.in_flows:
            flows = " || ".join(place_name(flow.id) for flow in event.in_flows)
            parts.insert(0, f"({flows})")
        enable = " && ".join(parts) or "0"
        out.write_str(
            f'__CPROVER_cover({enable}); // end event "{event.id}"', NL_SINGLE
        )
    for state in states.states:
        if state is not cwp.start_state:
            out.write_str(
                f'__CPROVER_cover({STATE_VAR} == CWP_STATE_{state.name}); // CWP state "{state.name}"',
                NL_SINGLE,
            )
    out.write_str("}", NL_SINGLE, IndentAction.DEC)
    out.write_str("#else", NL_SINGLE)
    out.write_str(f"#define {COVER_FUNC}() ((void)0)", NL_SINGLE)
    out.write_str("#endif", NL_DOUBLE)
    return str(out)


def _generate_main(bound: int) -> str:
    main = StringManager()
    main.write_str(f"#define {BOUND_MACRO} {bound}", NL_SINGLE)
    main.write_str("", NL_SINGLE)
    main.write_str("int main(void) {", NL_SINGLE, IndentAction.INC)
    main.write_str(f"{CALCULATE_FUNC}();", NL_SINGLE)
    main.write_str(f"{COVER_FUNC}();", NL_SINGLE)
    main.write_str("unsigned int passes = 0;", NL_SINGLE)
    main.write_str(
        f"while (!{ALL_DONE_FUNC}() && passes < {BOUND_MACRO}) {{",
        NL_SINGLE,
        IndentAction.INC,
    )
    main.write_str("passes++;", NL_SINGLE)
    main.write_str(f"{STEP_FUNC}();", NL_SINGLE)
    main.write_str(f"{UPDATE_FUNC}();", NL_SINGLE)
    main.write_str(f"{COVER_FUNC}();", NL_SINGLE)
    main.write_str("}", NL_SINGLE, IndentAction.DEC)
    main.write_str("return 0;", NL_SINGLE)
    main.write_str("}", NL_SINGLE, IndentAction.DEC)
    return str(main)


def _generate_c(state: State, cwp: Cwp, bpmn: Bpmn) -> Result[str, Error]:
    state_c = _generate_state_c(state)
    if isinstance(state_c, Failure):
        return state_c
    bpmn_c = _generate_bpmn_c(bpmn)
    if isinstance(bpmn_c, Failure):
        return bpmn_c
    cwp_c = _generate_cwp_c(cwp)
    main_c = _generate_main(compute_bound(bpmn))
    cover_c = _generate_cover(cwp, bpmn)
    return Success(f"{state_c.unwrap()}{cwp_c}\n{bpmn_c.unwrap()}\n{cover_c}{main_c}")


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
        The number of passes of the main loop. CBMC needs `--unwind` set to this
        plus one, so that it can check the loop stops within the bound.
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
