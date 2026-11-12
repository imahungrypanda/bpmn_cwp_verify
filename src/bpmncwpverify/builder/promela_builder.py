from returns.result import Failure, Result, Success

from bpmncwpverify.core.bpmn import Bpmn
from bpmncwpverify.core.cwp import Cwp
from bpmncwpverify.core.error import Error, NotInitializedError
from bpmncwpverify.core.state import State
from bpmncwpverify.util.stringmanager import NL_SINGLE, IndentAction, StringManager
from bpmncwpverify.visitors.bpmn_promela_visitor import PromelaGenVisitor
from bpmncwpverify.visitors.cwp_promela_visitor import CwpPromelaVisitor


def _generate_bpmn_promela(bpmn: Bpmn) -> str:
    promela_visitor = PromelaGenVisitor()
    bpmn.accept(promela_visitor)
    return str(promela_visitor)


def _generate_cwp_promela(cwp: Cwp, state: State) -> str:
    ltl_visitor = CwpPromelaVisitor()
    cwp.accept(ltl_visitor)
    return str(ltl_visitor)


def _generate_logger(state: State, cwp: Cwp) -> str:
    var_names = _get_variable_names(state)
    loggerFunction = StringManager()

    loggerFunction.write_str("inline stateLogger(){", NL_SINGLE, IndentAction.INC)
    loggerFunction.write_str('printf("Changed Vars: \\n")', NL_SINGLE)
    for name in var_names:
        loggerFunction.write_str("if", NL_SINGLE, IndentAction.INC)
        loggerFunction.write_str(
            f":: {name} != old_{name} ->", NL_SINGLE, IndentAction.INC
        )
        loggerFunction.write_str(
            f'printf("{name} = {_get_print_type(name)}\\n", {name})', NL_SINGLE
        )
        loggerFunction.write_str(f"old_{name} = {name}", NL_SINGLE)
        loggerFunction.write_str(":: else", NL_SINGLE, IndentAction.DEC)
        loggerFunction.write_str("fi;", NL_SINGLE, IndentAction.DEC)

    for cwp_state in cwp.states.values():
        loggerFunction.write_str("if", NL_SINGLE, IndentAction.INC)
        loggerFunction.write_str(
            f":: {cwp_state.name} == true ->", NL_SINGLE, IndentAction.INC
        )
        loggerFunction.write_str(
            f'printf("Current state: {cwp_state.name}\\n")', NL_SINGLE
        )
        loggerFunction.write_str(":: else", NL_SINGLE, IndentAction.DEC)
        loggerFunction.write_str("fi;", NL_SINGLE, IndentAction.DEC)
    loggerFunction.write_str("}", NL_SINGLE, IndentAction.DEC)
    return str(loggerFunction)


def _generate_state_dump(state: State) -> str:
    state_dump = StringManager()
    state_dump.write_str("inline stateDump(){", NL_SINGLE, IndentAction.INC)

    for var in state.vars:
        state_dump.write_str(
            f'printf("{var.id} = {_get_print_type(var.type_)}\\n", {var.id})', NL_SINGLE
        )

    state_dump.write_str("}", NL_SINGLE, IndentAction.DEC)
    return str(state_dump)


def _generate_promela(state: State, cwp: Cwp, bpmn: Bpmn) -> Result[str, Error]:
    cwp_pml = _generate_cwp_promela(cwp, state)
    vars_pml = _generate_state_promela(state)
    logger_pml = _generate_logger(state, cwp)
    state_dump_pml = _generate_state_dump(state)
    bpmn_pml = _generate_bpmn_promela(bpmn)
    pml = f"{vars_pml}{cwp_pml}{logger_pml}{state_dump_pml}{bpmn_pml}"
    return Success(pml)


def _generate_state_promela(state: State) -> str:
    str_builder: list[str] = []
    str_builder.append("//**********VARIABLE DECLARATION************//")
    for const_decl in state.consts:
        str_builder.append(f"#define {const_decl.id} {const_decl.init.value}")
    for enum_decl in state.enums:
        str_builder.append(
            f"mtype:{enum_decl.id} = {{{' '.join(sorted([value.value for value in enum_decl.values]))}}}"
        )
    for var_decl in state.vars:
        if var_decl.type_ in {enum.id for enum in state.enums}:
            str_builder.append(
                f"mtype:{var_decl.type_} {var_decl.id} = {var_decl.init.value}"
            )
            str_builder.append(
                f"mtype:{var_decl.type_} old_{var_decl.id} = {var_decl.id}"
            )
        else:
            str_builder.append(
                f"{var_decl.type_} {var_decl.id} = {var_decl.init.value}"
            )
            str_builder.append(f"{var_decl.type_} old_{var_decl.id} = {var_decl.id}")
    return "\n".join(str_builder) + "\n\n"


def _get_variable_names(state: State) -> list[str]:
    variableNames: list[str] = []
    for var in state.vars:
        variableNames.append(var.id)
    return variableNames


def _get_print_type(type: str) -> str:
    match type:
        case "bit":
            return "%u"
        case "bool":
            return "%d"
        case "byte":
            return "%u"
        case "int":
            return "%d"
        case "short":
            return "%hd"
        case _:
            return "%e"


class PromelaBuilder:
    __slots__ = [
        "bpmn",
        "cwp",
        "state",
    ]

    def __init__(self) -> None:
        self.bpmn: Result[Bpmn, Error] = Failure(
            NotInitializedError("PromelaBulider.bpmn")
        )
        self.cwp: Result[Cwp, Error] = Failure(
            NotInitializedError("PromelaBulider.cwp")
        )
        self.state: Result[State, Error] = Failure(
            NotInitializedError("PromelaBulider.state")
        )

    def build(self) -> Result[str, Error]:
        result: Result[str, Error] = self.state.bind(  # pyright: ignore[reportUnknownMemberType]
            lambda state: self.cwp.bind(  # pyright: ignore[reportUnknownMemberType]
                lambda cwp: self.bpmn.bind(  # pyright: ignore[reportUnknownMemberType]
                    lambda bpmn: _generate_promela(state, cwp, bpmn)
                )
            )
        )
        return result

    def with_bpmn(self, bpmn: Bpmn) -> "PromelaBuilder":
        self.bpmn = Success(bpmn)
        return self

    def with_cwp(self, cwp: Cwp) -> "PromelaBuilder":
        self.cwp = Success(cwp)
        return self

    def with_state(self, state: State) -> "PromelaBuilder":
        self.state = Success(state)
        return self


class Outputs:
    __slots__ = ["promela"]

    def __init__(self, promela: str) -> None:
        self.promela = promela
