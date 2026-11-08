# type: ignore
import pytest
from returns.result import Failure, Success

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
