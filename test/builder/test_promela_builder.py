# type: ignore
import pytest

from bpmncwpverify.builder.promela_builder import (
    _generate_logger,
    _generate_state_dump,
    _generate_state_promela,
    _get_variable_names,
)
from bpmncwpverify.core.state import State
from bpmncwpverify.util.stringmanager import NL_SINGLE, IndentAction


def test_logger_generator(mocker):
    # mocker.patch.object(
    #     PromelaBuilder, "variable_name_extractor", return_value=["test_string"]
    # )

    mocker.patch(
        "bpmncwpverify.builder.promela_builder._get_variable_names",
        return_value=["test_string"],
    )

    mock_write_str = mocker.patch(
        "bpmncwpverify.builder.promela_builder.StringManager.write_str"
    )

    state = mocker.Mock()

    mock_val1 = mocker.Mock()
    mock_val1.name = "test_val1"
    mock_val2 = mocker.Mock()
    mock_val2.name = "test_val2"

    cwp = mocker.Mock(states={"_0": mock_val1, "_1": mock_val2})
    _generate_logger(state, cwp)

    calls = [
        mocker.call("inline stateLogger(){", NL_SINGLE, IndentAction.INC),
        mocker.call('printf("Changed Vars: \\n")', NL_SINGLE),
        mocker.call("if", NL_SINGLE, IndentAction.INC),
        mocker.call(
            ":: test_string != old_test_string ->", NL_SINGLE, IndentAction.INC
        ),
        mocker.call('printf("test_string = %e\\n", test_string)', NL_SINGLE),
        mocker.call("old_test_string = test_string", NL_SINGLE),
        mocker.call(":: else", NL_SINGLE, IndentAction.DEC),
        mocker.call("fi;", NL_SINGLE, IndentAction.DEC),
        mocker.call("if", NL_SINGLE, IndentAction.INC),
        mocker.call(":: test_val1 == true ->", NL_SINGLE, IndentAction.INC),
        mocker.call('printf("Current state: test_val1\\n")', NL_SINGLE),
        mocker.call(":: else", NL_SINGLE, IndentAction.DEC),
        mocker.call("fi;", NL_SINGLE, IndentAction.DEC),
        mocker.call("if", NL_SINGLE, IndentAction.INC),
        mocker.call(":: test_val2 == true ->", NL_SINGLE, IndentAction.INC),
        mocker.call('printf("Current state: test_val2\\n")', NL_SINGLE),
        mocker.call(":: else", NL_SINGLE, IndentAction.DEC),
        mocker.call("fi;", NL_SINGLE, IndentAction.DEC),
        mocker.call("}", NL_SINGLE, IndentAction.DEC),
    ]
    mock_write_str.assert_has_calls(calls)


def test_variable_name_extractor(mocker):
    vars = [mocker.Mock(id=1), mocker.Mock(id=2)]

    state = mocker.Mock()
    state.vars = vars

    result = _get_variable_names(state)

    assert result == [1, 2]


def test_state_dump_int(mocker):
    vars = [
        mocker.Mock(id="v1", type_="int", init="1"),
        mocker.Mock(id="v2", type_="int", init="2"),
    ]

    state = mocker.Mock()
    state.vars = vars

    result = _generate_state_dump(state)

    assert (
        result
        == 'inline stateDump(){\n\tprintf("v1 = %d\\n", v1)\n\tprintf("v2 = %d\\n", v2)\n}\n'
    )


def test_state_dump_bool(mocker):
    vars = [
        mocker.Mock(id="v1", type_="bool", init="true"),
        mocker.Mock(id="v2", type_="bool", init="true"),
    ]

    state = mocker.Mock()
    state.vars = vars

    result = _generate_state_dump(state)

    assert (
        result
        == 'inline stateDump(){\n\tprintf("v1 = %d\\n", v1)\n\tprintf("v2 = %d\\n", v2)\n}\n'
    )


def test_state_dump_enum(mocker):
    vars = [
        mocker.Mock(id="v1", type_="BinDecision", init="yes"),
        mocker.Mock(id="v2", type_="BinDecision", init="no"),
    ]

    state = mocker.Mock()
    state.vars = vars

    result = _generate_state_dump(state)

    assert (
        result
        == 'inline stateDump(){\n\tprintf("v1 = %e\\n", v1)\n\tprintf("v2 = %e\\n", v2)\n}\n'
    )


def test_generate_promela(mocker):
    const = mocker.Mock(id="const_id", init=mocker.Mock(value="const_init_val"))
    enum = mocker.Mock(
        id="enum_id",
        values=[mocker.Mock(value="init_val"), mocker.Mock(value="other_val")],
    )
    var1 = mocker.Mock(id="var1_id", type_="int", init=mocker.Mock(value="0"))
    var2 = mocker.Mock(
        id="var2_id", type_="enum_id", init=mocker.Mock(value="init_val")
    )

    _consts = [const]
    _vars = [var1, var2]
    _enums = [enum]

    state = State(_consts, _enums, _vars)

    result = _generate_state_promela(state)

    expected = (
        "//**********VARIABLE DECLARATION************//\n"
        "#define const_id const_init_val\n"
        "mtype:enum_id = {init_val other_val}\n"
        "int var1_id = 0\n"
        "int old_var1_id = var1_id\n"
        "mtype:enum_id var2_id = init_val\n"
        "mtype:enum_id old_var2_id = var2_id\n\n"
    )
    assert result == expected


@pytest.fixture
def mock_state(mocker):
    """Fixture to create a mock State object."""
    state = mocker.MagicMock()
    state._consts = []
    state._enums = []
    state._vars = []
    return state


def test_generate_promela_with_full_state(mocker, mock_state):
    """Test generate_promela with a state containing constants, enums, and variables."""

    mock_const = mocker.MagicMock()
    mock_const.id = "MAX_COUNT"
    mock_const.init.value = "10"

    mock_enum = mocker.MagicMock()
    mock_enum.id = "TestEnum"
    mock_enum.values = [mocker.MagicMock(value="START"), mocker.MagicMock(value="STOP")]

    mock_var_enum = mocker.MagicMock()
    mock_var_enum.type_ = "int"
    mock_var_enum.id = "state_var"
    mock_var_enum.init.value = "START"

    mock_var_int = mocker.MagicMock()
    mock_var_int.type_ = "int"
    mock_var_int.id = "counter"
    mock_var_int.init.value = "0"

    mock_state.consts = [mock_const]
    mock_state.enums = [mock_enum]
    mock_state.vars = [mock_var_enum, mock_var_int]

    result = _generate_state_promela(mock_state)

    expected_output = (
        "//**********VARIABLE DECLARATION************//\n"
        "#define MAX_COUNT 10\n"
        "mtype:TestEnum = {START STOP}\n"
        "int state_var = START\n"
        "int old_state_var = state_var\n"
        "int counter = 0\n"
        "int old_counter = counter\n\n"
    )

    assert result == expected_output


def test_generate_promela_with_only_constants(mocker, mock_state):
    """Test generate_promela with only constants."""

    mock_const = mocker.MagicMock()
    mock_const.id = "BUFFER_SIZE"
    mock_const.init.value = "256"

    mock_state.consts = [mock_const]

    result = _generate_state_promela(mock_state)

    expected_output = (
        "//**********VARIABLE DECLARATION************//\n#define BUFFER_SIZE 256\n\n"
    )

    assert result == expected_output


def test_generate_promela_with_only_enums(mocker, mock_state):
    """Test generate_promela with only enums."""

    mock_enum = mocker.MagicMock()
    mock_enum.id = "TestEnum"
    mock_enum.values = [
        mocker.MagicMock(value="IDLE"),
        mocker.MagicMock(value="RUNNING"),
    ]

    mock_state.enums = [mock_enum]

    result = _generate_state_promela(mock_state)

    expected_output = (
        "//**********VARIABLE DECLARATION************//\n"
        "mtype:TestEnum = {IDLE RUNNING}\n\n"
    )

    assert result == expected_output


def test_generate_promela_with_empty_state(mock_state):
    """Test generate_promela with an empty state."""

    result = _generate_state_promela(mock_state)

    expected_output = "//**********VARIABLE DECLARATION************//\n\n"

    assert result == expected_output
