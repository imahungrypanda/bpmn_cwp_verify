from collections.abc import Callable
from typing import Final

from returns.result import Failure, Result, Success

from bpmncwpverify.core.error import (
    Error,
    TypingAssignCompatabilityError,
    TypingNegateBoolError,
    TypingNoTypeError,
)

# from bpmncwpverify.typing import BIT

BIT: Final[str] = "bit"
BOOL: Final[str] = "bool"
BYTE: Final[str] = "byte"
ENUM: Final[str] = "enum"
SHORT: Final[str] = "short"
INT: Final[str] = "int"

BYTEMIN: Final[int] = 0
BYTEMAX: Final[int] = 255
SHORTMIN: Final[int] = -32768
SHORTMAX: Final[int] = 32767
INTMIN: Final[int] = -2147483648
INTMAX: Final[int] = 2147483647


def get_and_or_type_result(
    ltype: str,
    rtype: str,
    error: Callable[[str, str], Error] = TypingAssignCompatabilityError,
) -> Result[str, Error]:
    if ltype == BOOL and rtype == BOOL:
        return Success(BOOL)
    return Failure(error(ltype, rtype))


def get_computation_type_result(
    ltype: str,
    rtype: str,
    error: Callable[[str, str], Error] = TypingAssignCompatabilityError,
) -> Result[str, Error]:
    if ltype in {BIT, BOOL} or rtype in {BIT, BOOL}:
        return Failure(error(ltype, rtype))
    elif ltype == rtype:
        return Success(ltype)
    elif "int" in [ltype, rtype]:
        return Success("int")
    elif "short" in [ltype, rtype]:
        return Success("short")
    return Failure(error(ltype, rtype))


def get_relational_type_result(
    ltype: str,
    rtype: str,
    error: Callable[[str, str], Error] = TypingAssignCompatabilityError,
) -> Result[str, Error]:
    similar_mapping = {
        "bit": "number",
        "byte": "number",
        "short": "number",
        "int": "number",
        "bool": "boolean",
    }

    if ltype == rtype or similar_mapping[ltype] == similar_mapping[rtype]:
        return Success(BOOL)

    return Failure(error(ltype, rtype))


def get_type_assign(ltype: str, rtype: str) -> Result[str, Error]:
    if ltype == rtype:
        return Success(ltype)
    if ltype == BYTE and (rtype == BIT):
        return Success(ltype)
    if ltype == SHORT and (rtype == BIT or rtype == BYTE):
        return Success(ltype)
    if ltype == INT and (rtype == BIT or rtype == BYTE or rtype == SHORT):
        return Success(ltype)
    return Failure(TypingAssignCompatabilityError(ltype, rtype))


def get_type_literal(literal: str) -> Result[str, TypingNoTypeError]:
    if literal == "false" or literal == "true":
        return Success(BOOL)

    try:
        value: int = int(literal)
        if value == 0 or value == 1:
            return Success(BIT)
        if BYTEMIN <= value and value <= BYTEMAX:
            return Success(BYTE)
        if SHORTMIN <= value and value <= SHORTMAX:
            return Success(SHORT)
        if INTMIN <= value and value <= INTMAX:
            return Success(INT)
        return Failure(TypingNoTypeError(literal))
    except Exception:
        return Failure(TypingNoTypeError(literal))


# FEEL type rules. Numeric types are ordered from narrowest to widest.
NUMERIC_TYPES: Final[tuple[str, ...]] = (BIT, BYTE, SHORT, INT)


def is_numeric(type_: str) -> bool:
    return type_ in NUMERIC_TYPES


def _wider(ltype: str, rtype: str) -> str:
    return max(ltype, rtype, key=NUMERIC_TYPES.index)


def get_feel_arithmetic_type_result(
    ltype: str,
    rtype: str,
    error: Callable[[str, str], Error] = TypingAssignCompatabilityError,
) -> Result[str, Error]:
    """
    The type of `ltype op rtype` for + - * /. Unlike get_computation_type_result
    it accepts bit, since the literals 0 and 1 are bits. The result is at least
    a byte because the result of an operation on bits is not a bit.
    """
    if is_numeric(ltype) and is_numeric(rtype):
        return Success(_wider(_wider(ltype, rtype), BYTE))
    return Failure(error(ltype, rtype))


def get_feel_negate_type_result(
    type_: str, error: Callable[[str], Error] = TypingNegateBoolError
) -> Result[str, Error]:
    """The type of `-x`: negatives need a signed type, so at least a short."""
    if is_numeric(type_):
        return Success(_wider(type_, SHORT))
    return Failure(error(type_))


def get_feel_comparison_type_result(
    ltype: str,
    rtype: str,
    ordered: bool,
    error: Callable[[str, str], Error] = TypingAssignCompatabilityError,
) -> Result[str, Error]:
    """
    The type of a comparison. Ordering (< > <= >=) needs numbers; equality
    also accepts two bools or two values of the same enum.
    """
    if is_numeric(ltype) and is_numeric(rtype):
        return Success(BOOL)
    if not ordered and ltype == rtype and ltype != ENUM:
        return Success(BOOL)
    return Failure(error(ltype, rtype))


def get_feel_unified_type_result(
    ltype: str,
    rtype: str,
    error: Callable[[str, str], Error] = TypingAssignCompatabilityError,
) -> Result[str, Error]:
    """The one type that two alternatives (if branches, choices) share."""
    if ltype == rtype:
        return Success(ltype)
    if is_numeric(ltype) and is_numeric(rtype):
        return Success(_wider(ltype, rtype))
    return Failure(error(ltype, rtype))
