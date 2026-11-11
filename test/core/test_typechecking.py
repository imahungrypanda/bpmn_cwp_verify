# type: ignore
import pytest
from returns.result import Failure, Success

from bpmncwpverify.core import typechecking
from bpmncwpverify.core.error import TypingAssignCompatabilityError, TypingNoTypeError
from bpmncwpverify.core.typechecking import (
    BIT,
    BOOL,
    BYTE,
    INT,
    SHORT,
    get_type_assign,
    get_type_literal,
)


class Test_get_type_assign:
    @pytest.mark.parametrize(
        "ltype, rtype, expected_type",
        [
            ("a", "a", "a"),
            (BIT, BIT, BIT),
            (BOOL, BOOL, BOOL),
            (BYTE, BIT, BYTE),
            (SHORT, BYTE, SHORT),
            (INT, SHORT, INT),
            (INT, BYTE, INT),
        ],
    )
    def test_given_good_assign_then_success(
        self, ltype: str, rtype: str, expected_type: str
    ):
        # givin
        # ltype, rtype

        # when
        result = get_type_assign(ltype, rtype)

        # then
        expected = Success(expected_type)
        assert expected == result

    @pytest.mark.parametrize(
        "ltype, rtype",
        [
            ("a", "b"),
            (BIT, BYTE),
            (SHORT, INT),
            (BOOL, BIT),
            (BIT, BOOL),
        ],
    )
    def test_given_bad_assign_then_failure(self, ltype: str, rtype: str):
        # givin
        # ltype, rtype

        # when
        result = get_type_assign(ltype, rtype)

        # then
        expected = Failure(TypingAssignCompatabilityError(ltype, rtype))
        assert expected == result


class Test_get_type_literal:
    @pytest.mark.parametrize(
        "literal, expected_type",
        [
            ("00", BIT),
            ("1", BIT),
            ("false", BOOL),
            ("true", BOOL),
            ("2", BYTE),
            ("255", BYTE),
            ("256", SHORT),
            ("-32769", INT),
            ("32768", INT),
            ("-2147483648", INT),
            ("2147483647", INT),
        ],
    )
    def test_given_good_literal_then_success(self, literal: str, expected_type: str):
        # givin
        # literal

        # when
        result = get_type_literal(literal)

        # then
        expected = Success(expected_type)
        assert expected == result

    @pytest.mark.parametrize(
        "literal",
        [
            ("False"),
            ("True"),
            ("-2147483649"),
            ("2147483648"),
        ],
    )
    def test_given_bad_literal_then_failure(self, literal: str):
        # givin
        literal = literal

        # when
        result = get_type_literal(literal)

        # then
        expected = Failure(TypingNoTypeError(literal))
        assert expected == result


class TestFeelRules:
    @pytest.mark.parametrize(
        "ltype, rtype, expected",
        [
            ("bit", "bit", "byte"),
            ("byte", "bit", "byte"),
            ("byte", "short", "short"),
            ("int", "byte", "int"),
        ],
    )
    def test_arithmetic_numeric(self, ltype, rtype, expected):
        assert typechecking.get_feel_arithmetic_type_result(ltype, rtype) == Success(
            expected
        )

    @pytest.mark.parametrize("ltype, rtype", [("bool", "byte"), ("Door", "Door")])
    def test_arithmetic_non_numeric_fails(self, ltype, rtype):
        assert isinstance(
            typechecking.get_feel_arithmetic_type_result(ltype, rtype), Failure
        )

    def test_negate(self):
        assert typechecking.get_feel_negate_type_result("byte") == Success("short")
        assert typechecking.get_feel_negate_type_result("int") == Success("int")
        assert isinstance(typechecking.get_feel_negate_type_result("bool"), Failure)

    def test_comparison(self):
        f = typechecking.get_feel_comparison_type_result
        assert f("byte", "int", True) == Success("bool")
        assert f("bool", "bool", False) == Success("bool")
        assert f("Door", "Door", False) == Success("bool")
        assert isinstance(f("bool", "bool", True), Failure)
        assert isinstance(f("Door", "Light", False), Failure)
        assert isinstance(f("bool", "byte", False), Failure)

    def test_unified(self):
        f = typechecking.get_feel_unified_type_result
        assert f("bit", "short") == Success("short")
        assert f("Door", "Door") == Success("Door")
        assert isinstance(f("Door", "bool"), Failure)
