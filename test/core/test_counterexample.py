# type: ignore
import pytest

from bpmncwpverify.core.bpmn import Bpmn
from bpmncwpverify.core.counterexample import NL_SINGLE, CounterExample
from bpmncwpverify.core.error import Error


@pytest.fixture
def get_mock_write_str(mocker):
    return mocker.patch("bpmncwpverify.util.stringmanager.StringManager.write_str")


def test_generate_counter_example(mocker):
    spin_output = mocker.Mock()
    spin_output.stdout = "test_str"
    mocker.patch(
        "bpmncwpverify.core.counterexample.subprocess.run", return_value=spin_output
    )
    mock_filter_spin_trace = mocker.patch(
        "bpmncwpverify.core.counterexample.CounterExample.filter_spin_trace"
    )

    CounterExample.generate_counterexample(
        mocker.Mock(), mocker.MagicMock(__name__="test"), mocker.MagicMock()
    )

    mock_filter_spin_trace.assert_called_once_with("test_str")


def test_filter_spin_trace(get_mock_write_str, mocker):
    mock_write_str = get_mock_write_str

    spin_trace_string = mocker.Mock()
    spin_trace_string.splitlines.return_value = [
        "test string",
        "with random words and",
        "spin:",
        "this text is pointless",
    ]

    CounterExample.filter_spin_trace(spin_trace_string)

    calls = [
        mocker.call("test string", NL_SINGLE),
        mocker.call("with random words and", NL_SINGLE),
    ]

    mock_write_str.assert_has_calls(calls)


def test_counterexample_constructor(mocker):
    class SubError(Error):
        pass

    error_trace = mocker.Mock()

    ce = CounterExample([error_trace], SubError)

    assert ce.trace_steps == [error_trace]
    assert ce.error == "SubError"


def test_counterexample_extract_steps(mocker):
    test_string = """ID: Event_1\nChanged Vars:\ntest_var1\ntest_var2\nCurrent state: test_state1"""
    bpmn = Bpmn()
    mock_element = mocker.MagicMock()
    mock_element.id = "Event_1"
    mock_element.name = "start"

    bpmn.id_to_element[mock_element.id] = mock_element

    steps, issue = CounterExample.extract_steps_v_two(test_string, bpmn)

    assert issue == ""
    assert len(steps) == 1
    assert steps[0].id == "start"
    assert steps[0].changed_vars == ["test_var1", "test_var2"]
    assert steps[0].cur_cwp_state == "test_state1"
