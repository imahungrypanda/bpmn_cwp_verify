from returns.result import Failure, Result, Success

from bpmncwpverify.builder.cbmc_bound import compute_unwind_bound
from bpmncwpverify.core.bpmn import Bpmn, EndEvent, Node
from bpmncwpverify.core.cwp import Cwp
from bpmncwpverify.core.error import (
    CbmcBuildError,
    Error,
    NotInitializedError,
    get_error_message,
)
from bpmncwpverify.core.state import State
from bpmncwpverify.util.stringmanager import (
    NL_DOUBLE,
    NL_SINGLE,
    IndentAction,
    StringManager,
)
from bpmncwpverify.visitors.bpmn_cbmc_visitor import (
    CbmcBpmnVisitor,
    _place,  # pyright: ignore[reportPrivateUsage]
)
from bpmncwpverify.visitors.cwp_cbmc_visitor import (
    CALCULATE_FUNCTION,
    STATE_PREFIX,
    STATE_VAR,
    UPDATE_FUNCTION,
    CwpCbmcVisitor,
)

REACH_FUNCTION = "check_reachability"

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
    sm = StringManager()
    sm.write_str("#include <stdbool.h>", NL_DOUBLE)
    sm.write_str("//**********VARIABLE DECLARATION************//", NL_SINGLE)
    for const_decl in state.consts:
        sm.write_str(f"#define {const_decl.id} {const_decl.init.value}", NL_SINGLE)
    for enum_decl in state.enums:
        values = ", ".join(sorted(value.value for value in enum_decl.values))
        sm.write_str(f"enum {enum_decl.id} {{ {values} }};", NL_SINGLE)
    for var_decl in state.vars:
        c_type = _c_type(state, var_decl.type_)
        sm.write_str(f"{c_type} {var_decl.id} = {var_decl.init.value};", NL_SINGLE)
        sm.write_str(f"{c_type} old_{var_decl.id} = {var_decl.init.value};", NL_SINGLE)
    sm.write_str("", NL_SINGLE)
    return str(sm)


def _end_event_places(event: Node) -> list[str]:
    flows = event.in_flows + event.in_msgs
    return [_place(f.id) for f in flows] or [_place(event.id)]


def _generate_reachability(cwp_visitor: CwpCbmcVisitor, bpmn: Bpmn) -> str:
    """A function with a cover for each end event and each CWP state, seen
    only when compiled with -DREACHABILITY. The CWP's start state is left out:
    the initial values put the CWP in the state after it."""
    sm = StringManager()
    sm.write_str("#ifdef REACHABILITY", NL_SINGLE)
    sm.write_str(f"void {REACH_FUNCTION}(void) {{", NL_SINGLE, IndentAction.INC)
    seen: set[str] = set()
    for process in bpmn.processes.values():
        for node in process.all_items().values():
            if isinstance(node, EndEvent) and node.id not in seen:
                seen.add(node.id)
                places = " || ".join(_end_event_places(node))
                sm.write_str(f"/* end event {node.id} */", NL_SINGLE)
                sm.write_str(f"__CPROVER_cover({places});", NL_SINGLE)
    for cwp_state in cwp_visitor.states:
        if cwp_state is cwp_visitor.start_state:
            continue
        sm.write_str(f"/* cwp state {cwp_state.name} */", NL_SINGLE)
        sm.write_str(
            f"__CPROVER_cover({STATE_VAR} == {STATE_PREFIX}{cwp_state.name});",
            NL_SINGLE,
        )
    sm.write_str("}", NL_SINGLE, IndentAction.DEC)
    sm.write_str("#endif", NL_DOUBLE)
    return str(sm)


def _reach_call() -> str:
    return f"#ifdef REACHABILITY\n{REACH_FUNCTION}();\n#endif\n"


def _without_cwp_updates(step: str) -> str:
    """The visitor ends each task behavior with a CWP update. main() updates
    the CWP once per pass instead, so those calls are dropped: left in, each
    one is another copy of the update in every unrolled pass, and CBMC takes
    minutes on face2face instead of seconds."""
    call = f"{UPDATE_FUNCTION}();"
    return "".join(
        line for line in step.splitlines(keepends=True) if line.strip() != call
    )


def _generate_main(state: State, bpmn_visitor: CbmcBpmnVisitor, bound: int) -> str:
    changed = " || ".join(f"{v.id} != old_{v.id}" for v in state.vars) or "0"
    sm = StringManager()
    sm.write_str("int main(void) {", NL_SINGLE, IndentAction.INC)
    sm.write_str(bpmn_visitor.init)
    # The CWP starts in the state the initial variable values put it in.
    sm.write_str(f"{CALCULATE_FUNCTION}();", NL_SINGLE)
    sm.write_str(_reach_call())
    sm.write_str(
        f"for (unsigned int pass = 0; pass < {bound}; pass++) {{",
        NL_SINGLE,
        IndentAction.INC,
    )
    sm.write_str(f"if ({bpmn_visitor.all_ended}) break;", NL_SINGLE)
    sm.write_str(_without_cwp_updates(str(bpmn_visitor.step)))
    sm.write_str(f"if ({changed}) {{", NL_SINGLE, IndentAction.INC)
    sm.write_str(f"{UPDATE_FUNCTION}();", NL_SINGLE)
    for var in state.vars:
        sm.write_str(f"old_{var.id} = {var.id};", NL_SINGLE)
    sm.write_str("}", NL_SINGLE, IndentAction.DEC)
    sm.write_str(_reach_call())
    sm.write_str("}", NL_SINGLE, IndentAction.DEC)
    sm.write_str("return 0;", NL_SINGLE)
    sm.write_str("}", NL_SINGLE, IndentAction.DEC)
    return str(sm)


def _generate_c(state: State, cwp: Cwp, bpmn: Bpmn) -> Result[str, Error]:
    bpmn_visitor = CbmcBpmnVisitor()
    bpmn.accept(bpmn_visitor)
    if bpmn_visitor.errors:
        reasons = "; ".join(get_error_message(e) for e in bpmn_visitor.errors)
        return Failure(CbmcBuildError(reasons))
    cwp_visitor = CwpCbmcVisitor()
    cwp.accept(cwp_visitor)
    bound = compute_unwind_bound(bpmn)
    return Success(
        _generate_state_c(state)
        + str(cwp_visitor)
        + str(bpmn_visitor.defs)
        + "\n"
        + _generate_reachability(cwp_visitor, bpmn)
        + _generate_main(state, bpmn_visitor, bound)
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
        """The value to pass to `cbmc --unwind`: the loop's bound plus one"""
        result: Result[int, Error] = self.bpmn.map(  # pyright: ignore[reportUnknownMemberType]
            lambda bpmn: compute_unwind_bound(bpmn) + 1
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
