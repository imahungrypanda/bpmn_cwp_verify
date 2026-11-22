# type: ignore
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from returns.pipeline import is_successful
from returns.unsafe import unsafe_perform_io

from bpmncwpverify.cli import cli_verify, cli_verify_with_cbmc, verify
from bpmncwpverify.core import cbmc
from bpmncwpverify.core.cbmc import (
    CbmcVerificationReport,
    check_assertions,
    check_reachability,
)
from bpmncwpverify.core.error import (
    CbmcAssertionError,
    CbmcRunError,
    CbmcUnreachableError,
    SubProcessRunError,
    get_error_message,
)

RESOURCES = Path(__file__).parent / "resources"
FACE2FACE = RESOURCES / "face2face"
SIMPLE = RESOURCES / "simple_example"


def failure_of(result):
    assert not is_successful(result)
    return unsafe_perform_io(result.failure())


def run_cbmc(state, cwp, bpmn):
    return cli_verify_with_cbmc(str(state), str(cwp), str(bpmn))


@pytest.mark.parametrize("bpmn", ["workflow.bpmn", "face2face_open.bpmn"])
def test_face2face_verifies_with_cbmc_within_a_minute(bpmn):
    start = time.monotonic()
    result = run_cbmc(FACE2FACE / "state.txt", FACE2FACE / "cwp.xml", FACE2FACE / bpmn)
    assert time.monotonic() - start < 60
    assert is_successful(result), failure_of(result)
    report = unsafe_perform_io(result.unwrap())
    assert isinstance(report, CbmcVerificationReport)
    assert "__CPROVER_cover" in report.c_program
    assert "VERIFICATION SUCCESSFUL" in report.assertion_report
    assert "satisfied" in report.reachability_report
    assert "successful" in report.summary()


def test_failed_assertion_is_reported(tmp_path):
    bpmn = (SIMPLE / "simple_open.bpmn").read_text()
    bpmn = bpmn.replace("x = x + 1", "x = x + 1; assert(x == 100)")
    bpmn_file = tmp_path / "failing.bpmn"
    bpmn_file.write_text(bpmn)
    result = run_cbmc(SIMPLE / "state.txt", SIMPLE / "test_cwp.xml", bpmn_file)
    error = failure_of(result)
    assert isinstance(error, CbmcAssertionError)
    assert any("behavior assertion" in f["description"] for f in error.failures)
    assert "Assertion failed" in get_error_message(error)


def test_unreachable_state_is_reported():
    # The loop needs more passes than the bound allows, so the end is never reached
    result = run_cbmc(
        SIMPLE / "state.txt", SIMPLE / "test_cwp.xml", SIMPLE / "simple_open.bpmn"
    )
    error = failure_of(result)
    assert isinstance(error, CbmcUnreachableError)
    names = [u["description"] for u in error.unreachable]
    assert 'CWP state "End"' in names
    assert any(name.startswith("end event") for name in names)
    assert 'CWP state "Start"' not in names
    assert "never reaches" in get_error_message(error)


def test_unreached_goals_are_the_only_ones_reported():
    c_program = 'a\n__CPROVER_cover(x); // end event "E"\nb\n'
    output = json.dumps(
        [
            {
                "goals": [
                    {"status": "satisfied", "sourceLocation": {"line": "1"}},
                    {
                        "status": "failed",
                        "description": "condition",
                        "sourceLocation": {"line": "2"},
                    },
                ]
            }
        ]
    )
    error = check_reachability(output, c_program).failure()
    assert [u["description"] for u in error.unreachable] == ['end event "E"']


def test_all_properties_succeeding_passes():
    results = json.dumps(
        [{"result": [{"status": "SUCCESS"}]}, {"cProverStatus": "success"}]
    )
    goals = json.dumps([{"goals": [{"status": "satisfied"}]}])
    assert check_assertions(results).unwrap() is None
    assert check_reachability(goals).unwrap() is None


def test_unreadable_output_is_a_run_error():
    assert isinstance(check_assertions("not json").failure(), CbmcRunError)
    assert isinstance(check_assertions("[]").failure(), CbmcRunError)
    assert isinstance(check_reachability("[]").failure(), CbmcRunError)


def test_cbmc_failing_to_parse_is_a_run_error(mocker):
    mocker.patch.object(
        cbmc.CbmcBuilder,
        "build",
        return_value=cbmc.Success("int main(void) { x }"),
    )
    result = run_cbmc(
        SIMPLE / "state.txt", SIMPLE / "test_cwp.xml", SIMPLE / "simple_open.bpmn"
    )
    error = failure_of(result)
    assert isinstance(error, CbmcRunError)
    assert "could not be run" in get_error_message(error)


def test_missing_cbmc_executable_is_a_subprocess_error(mocker):
    mocker.patch.object(cbmc.subprocess, "run", side_effect=FileNotFoundError("cbmc"))
    result = run_cbmc(
        SIMPLE / "state.txt", SIMPLE / "test_cwp.xml", SIMPLE / "simple_open.bpmn"
    )
    assert isinstance(failure_of(result), SubProcessRunError)


def test_bad_input_file_is_an_error_before_cbmc_runs():
    result = run_cbmc(SIMPLE / "nope.txt", SIMPLE / "test_cwp.xml", SIMPLE / "x.bpmn")
    assert not is_successful(result)


def test_verify_cbmc_option_prints_summary(capsys):
    sys.argv = [
        "verify",
        "--cbmc",
        str(FACE2FACE / "state.txt"),
        str(FACE2FACE / "cwp.xml"),
        str(FACE2FACE / "workflow.bpmn"),
    ]
    verify()
    assert "CBMC verification successful" in capsys.readouterr().out


def test_verify_cbmc_option_prints_error(capsys):
    sys.argv = [
        "verify",
        "--cbmc",
        str(SIMPLE / "state.txt"),
        str(SIMPLE / "test_cwp.xml"),
        str(SIMPLE / "simple_open.bpmn"),
    ]
    verify()
    assert "CBMC ERROR" in capsys.readouterr().out


def test_cbmc_and_cloud_cannot_be_combined():
    sys.argv = ["verify", "--cbmc", "--cloud", "s", "c", "b"]
    with pytest.raises(SystemExit):
        verify()


def test_spin_path_is_unchanged_without_the_option(capsys):
    sys.argv = [
        "verify",
        str(SIMPLE / "state.txt"),
        str(SIMPLE / "test_cwp.xml"),
        str(SIMPLE / "simple_open.bpmn"),
    ]
    verify()
    out = capsys.readouterr().out
    assert "CBMC" not in out
    assert "pan:" in out or "State-vector" in out
    assert is_successful(
        cli_verify(
            str(SIMPLE / "state.txt"),
            str(SIMPLE / "test_cwp.xml"),
            str(SIMPLE / "simple_open.bpmn"),
        )
    )


def test_cbmc_is_installed():
    assert (
        subprocess.run(
            ["cbmc", "--version"], capture_output=True, check=False
        ).returncode
        == 0
    )
