# type: ignore
import re
from collections.abc import Iterable

import pytest
from antlr4.error.ErrorStrategy import ParseCancellationException
from returns.functions import not_
from returns.maybe import Some
from returns.pipeline import is_successful
from returns.result import Result

from bpmncwpverify.antlr.StateParser import StateParser
from bpmncwpverify.core import typechecking
from bpmncwpverify.core.error import (
    Error,
    StateInitNotInValues,
    StateMultipleDefinitionError,
    StateSyntaxError,
    TypingAssignCompatabilityError,
    TypingNoTypeError,
)
from bpmncwpverify.core.state import State, _get_parser, _parse_state


@pytest.fixture(scope="module")
def bad_input() -> Iterable[str]:
    yield "enum MyEnum {a b c d} const MYCONST : foo = 10 var myenum my : MyEnum = a {b c d}"


@pytest.fixture(scope="module")
def good_input() -> Iterable[str]:
    yield "enum MyEnum {a b c d} const MYCONST : byte = 10 var myenum : MyEnum = a {a b c d}"


class Test_get_parser:
    def test_given_bad_input_when_parse_state_then_ParseCancelationException(
        self, bad_input
    ):
        # given
        parser_result = _get_parser(bad_input)
        assert is_successful(parser_result)
        parser = parser_result.unwrap()

        # when
        with pytest.raises(
            ParseCancellationException, match=r".* extraneous .*"
        ) as exception:
            _ = parser.state()

        # then
        assert exception.type is ParseCancellationException
        assert parser.getNumberOfSyntaxErrors() == 1
        assert (
            "line 1:58 extraneous input 'my' expecting ':'" == exception.value.args[0]
        )
        assert "line 1:58 extraneous input 'my' expecting ':'" in str(exception.value)

    def test_given_good_input_when_parse_state_then_tree_not_none(self, good_input):
        # given
        parser_result = _get_parser(good_input)
        assert is_successful(parser_result)
        parser = parser_result.unwrap()

        # when
        try:
            tree = parser.state()
        except Exception as exception:
            pytest.fail(f"ERROR: unexpected {exception}")

        # then
        assert 0 == parser.getNumberOfSyntaxErrors()
        assert tree is not None


class Test_parse_state:
    @pytest.fixture(scope="class")
    def bad_parser(self, bad_input):
        result = _get_parser(bad_input)
        yield result

    @pytest.fixture(scope="class")
    def good_parser(self, good_input):
        result = _get_parser(good_input)
        yield result

    def test_given_bad_parser_when_parse_state_then_failure(
        self, bad_parser: Result[StateParser, Error]
    ):
        # given
        assert is_successful(bad_parser), f"ERROR: unexpected {str(bad_parser)}"

        # when
        result = bad_parser.bind(_parse_state)

        # then
        assert not is_successful(result)
        error = result.failure()
        assert isinstance(error, StateSyntaxError)
        assert "line 1:58 extraneous input 'my' expecting ':'" == error.msg

    def test_given_good_parser_when_parse_state_then_success(
        self, good_parser: Result[StateParser, Error]
    ):
        # given
        assert is_successful(good_parser), f"ERROR: unexpected {str(good_parser)}"

        # when
        result = good_parser.bind_result(_parse_state)

        # then
        assert is_successful(result)


# TODO:
#   * Add tests for failed enum declarations
class Test_SymbolTable_build:
    def test_given_good_input_when_build_then_success(self, good_input: str):
        # given
        # good_input

        # when
        result = State.from_str(good_input)

        # then
        assert is_successful(result)

    def test_given_bad_input_when_build_then_failure(self, bad_input: str):
        # given
        # bad_input

        # when
        result = State.from_str(bad_input)

        # then
        assert not_(is_successful)(result)

    @pytest.mark.parametrize(
        "good_input, expected",
        [
            (
                "enum E {a b} var e : E = a {a b}",
                [("E", typechecking.ENUM), ("a", "E"), ("b", "E")],
            ),
            ("enum A {b} const a: A = b var i : A = b {b}", [("a", "A")]),
            ("const a: bit = 0 var i : bit = 0 {0 1}", [("a", typechecking.BIT)]),
            (
                "const a: bool = false var i : bool = true {true false}",
                [("a", typechecking.BOOL)],
            ),
            ("const a: byte = 0 var i : byte = 0 {0 5 9}", [("a", typechecking.BYTE)]),
            (
                "const a: short = 0 var i : short = 256 {0 1 256}",
                [("a", typechecking.SHORT)],
            ),
            ("const a: int = 0 var i : int = 2", [("a", typechecking.INT)]),
            ("var i : int = 0 {0 1}", [("i", typechecking.INT)]),
        ],
    )
    def test_given_good_state_when_build_then_success(self, good_input, expected):
        # given
        # good, expected

        # when
        result = State.from_str(good_input)

        # then
        assert is_successful(result)
        state: State = result.unwrap()
        assert good_input == re.sub(r"\s+", " ", str(state)).strip()
        for i, expected_type in expected:
            result_type = state.get_type(i)
            assert is_successful(result_type)
            assert expected_type == result_type.unwrap()

    @pytest.mark.parametrize(
        "bad_input, expected",
        [
            # Multiple Defnitionns
            (
                "enum E {e e} var i : E = a {a}",
                StateMultipleDefinitionError("e", Some(1), Some(10), Some(1), Some(8)),
            ),
            (
                "enum E {e} enum E {f} var i : E = a {a}",
                StateMultipleDefinitionError("E", Some(1), Some(16), Some(1), Some(5)),
            ),
            (
                "enum E {e} const e : E = 0 var i : E = a {a}",
                StateMultipleDefinitionError("e", Some(1), Some(17), Some(1), Some(8)),
            ),
            (
                "const e : int = 0 var e : int = 0 {0 1}",
                StateMultipleDefinitionError("e", Some(1), Some(22), Some(1), Some(6)),
            ),
            # Bad const initializer
            (
                "enum E {e} const ECONST : E = a var i : int = 0",
                TypingNoTypeError("a"),
            ),
            (
                "enum E {e} const ECONST : E = true var i : int = 0",
                TypingAssignCompatabilityError("E", typechecking.BOOL),
            ),
            (
                "const C : bool = 0 var i : int = 0",
                TypingAssignCompatabilityError(typechecking.BOOL, typechecking.BIT),
            ),
            (
                "const C : int = true var i : int = 0",
                TypingAssignCompatabilityError(typechecking.INT, typechecking.BOOL),
            ),
            (
                "const C : bit = 2 var i : int = 0",
                TypingAssignCompatabilityError(typechecking.BIT, typechecking.BYTE),
            ),
            # Bad var assigns
            (
                "enum E {e} var c : E = a",
                TypingNoTypeError("a"),
            ),
            (
                "enum E {e} var c : E = e {e 0}",
                TypingAssignCompatabilityError("E", typechecking.BIT),
            ),
            (
                "var i : int = false",
                TypingAssignCompatabilityError(typechecking.INT, typechecking.BOOL),
            ),
            (
                "var i : bit = 2",
                TypingAssignCompatabilityError(typechecking.BIT, typechecking.BYTE),
            ),
            # Var initial value not included in allowed values
            (
                "enum E {e f} var c : E = e {f}",
                StateInitNotInValues("e", Some(1), Some(25), {"f"}),
            ),
        ],
    )
    def test_given_bad_state_when_build_then_failure(self, bad_input, expected):
        # given
        # bad, expected

        # when
        result = State.from_str(bad_input)

        # then
        assert not_(is_successful)(result)
        error: Error = result.failure()
        assert expected == error

    # @staticmethod
    # def generate_promela(state: "State") -> Result[str, Error]:
    #     str_builder: List[str] = []
    #     str_builder.append("//**********VARIABLE DECLARATION************//")
    #     for const_decl in state._consts:
    #         str_builder.append(f"#define {const_decl.id} {const_decl.init.value}")
    #     for enum_decl in state._enums:
    #         str_builder.append(
    #             f"mtype:{enum_decl.id} = {{{' '.join(sorted([value.value for value in enum_decl.values]))}}}"
    #         )
    #     for var_decl in state._vars:
    #         if var_decl.type_ in {enum.id for enum in state._enums}:
    #             str_builder.append(
    #                 f"mtype:{var_decl.type_} {var_decl.id} = {var_decl.init.value}"
    #             )
    #             str_builder.append(
    #                 f"mtype:{var_decl.type_} old_{var_decl.id} = {var_decl.id}"
    #             )
    #         else:
    #             str_builder.append(
    #                 f"{var_decl.type_} {var_decl.id} = {var_decl.init.value}"
    #             )
    #             str_builder.append(
    #                 f"{var_decl.type_} old_{var_decl.id} = {var_decl.id}"
    #             )
    #     return Success("\n".join(str_builder) + "\n\n")
