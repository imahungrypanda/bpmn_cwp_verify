# type: ignore
import re
import shutil
import sys

import pytest
from returns.io import IOSuccess
from returns.pipeline import is_successful
from returns.unsafe import unsafe_perform_io

from bpmncwpverify.builder.cbmc_builder import CbmcBuilder
from bpmncwpverify.cli import cli_verify_cbmc, verify
from bpmncwpverify.core import cbmc
from bpmncwpverify.core.accessmethods import bpmnmethods
from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.cbmc import (
    CbmcVerificationReport,
    _check_assertions,
    _check_coverage,
    _run_cbmc,
    verify_with_cbmc,
)
from bpmncwpverify.core.error import (
    CbmcAssertionError,
    CbmcRunError,
    CbmcUnreachableStateError,
    get_error_message,
)
from bpmncwpverify.core.state import State
from bpmncwpverify.util.file import element_tree_from_string

FACE2FACE = "./test/resources/face2face/"
STATE = FACE2FACE + "state.txt"
CWP = FACE2FACE + "cwp.xml"
BPMN = FACE2FACE + "workflow.bpmn"

needs_cbmc = pytest.mark.skipif(shutil.which("cbmc") is None, reason="No CBMC")

CLEAN_ASSERT_REPORT = "** 0 of 29 failed (1 iterations)\nVERIFICATION SUCCESSFUL\n"
CLEAN_COVER_REPORT = "** 6 of 6 covered (100.0%)\n"


def _read(path):
    with open(path) as f:
        return f.read()


def _parse(state_path, cwp_path, bpmn_text):
    state = State.from_str(_read(state_path)).unwrap()
    cwp_xml = unsafe_perform_io(element_tree_from_string(_read(cwp_path)).unwrap())
    bpmn_xml = unsafe_perform_io(element_tree_from_string(bpmn_text).unwrap())
    return (
        state,
        CwpXmlParser.from_xml(cwp_xml, state).unwrap(),
        bpmnmethods.from_xml(bpmn_xml, state).unwrap(),
    )


def _with_update_state(tmp_path):
    """face2face's workflow, with every behavior ending in updateState()."""
    text = _read(BPMN).replace(
        "</bpmn:documentation>", "\nupdateState()</bpmn:documentation>"
    )
    path = tmp_path / "workflow.bpmn"
    path.write_text(text)
    return str(path)


@pytest.fixture
def outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(cbmc, "OUTPUT_FILE", str(tmp_path / "verification.c"))
    monkeypatch.setattr(cbmc, "COVERAGE_OUTPUT_FILE", str(tmp_path / "cover.c"))
    return tmp_path


def test_builder_state_coverage_marks_every_state():
    state, cwp, bpmn = _parse(STATE, CWP, _read(BPMN))
    builder = CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn)

    plain = builder.build().unwrap()
    covered = builder.with_state_coverage(True).build().unwrap()

    assert "__CPROVER_cover" not in plain
    assert len(re.findall(r"__CPROVER_cover\(\w+\);", covered)) == len(cwp.states)
    assert "__CPROVER_cover(Negotiations);" in covered


def test_check_assertions_passes_on_clean_report():
    assert is_successful(_check_assertions(CLEAN_ASSERT_REPORT))


def test_check_assertions_reports_failures():
    report = (
        '[updateState.assertion.1] line 48 assertion validTransition && "Not a valid CWP transition": FAILURE\n'
        "[main.unwind.0] line 9 unwinding assertion loop 0: FAILURE\n"
        "[f.assertion.2] line 7 assertion x == 1: SUCCESS\n"
    )

    result = _check_assertions(report)

    error = result.failure()
    assert isinstance(error, CbmcAssertionError)
    assert [(f["function"], f["line"], f["assertion"]) for f in error.failures] == [
        ("updateState", "48", "Not a valid CWP transition"),
        ("main", "9", "unwinding assertion loop 0"),
    ]


def test_check_coverage_ignores_start_state_and_reports_the_rest():
    _, cwp, _ = _parse(STATE, CWP, _read(BPMN))
    report = (
        "[updateState.coverage.1] file fc.c line 50 function updateState condition 'Start != FALSE': FAILED\n"
        "[updateState.coverage.2] file fc.c line 52 function updateState condition 'Negotiations != FALSE': FAILED\n"
        "[updateState.coverage.3] file fc.c line 54 function updateState condition 'Purchase_Failed != FALSE': SATISFIED\n"
    )

    error = _check_coverage(report, cwp).failure()

    assert isinstance(error, CbmcUnreachableStateError)
    assert error.states == ["Negotiations"]
    assert is_successful(_check_coverage(CLEAN_COVER_REPORT, cwp))


def test_run_cbmc_fails_when_cbmc_cannot_run(mocker):
    mocker.patch.object(cbmc.subprocess, "run", side_effect=FileNotFoundError("cbmc"))

    result = _run_cbmc("x.c", [])

    assert isinstance(unsafe_perform_io(result.failure()), CbmcRunError)


def test_run_cbmc_fails_on_cbmc_error_exit_code(tmp_path):
    bad = tmp_path / "bad.c"
    bad.write_text("this is not C")

    result = _run_cbmc(str(bad), [])

    error = unsafe_perform_io(result.failure())
    assert isinstance(error, CbmcRunError)
    assert "exit code" in get_error_message(error)


def test_verify_with_cbmc_passes_when_both_runs_are_clean(mocker, outputs):
    run = mocker.patch.object(
        cbmc,
        "_run_cbmc",
        side_effect=[IOSuccess(CLEAN_ASSERT_REPORT), IOSuccess(CLEAN_COVER_REPORT)],
    )
    state, cwp, bpmn = _parse(STATE, CWP, _read(BPMN))

    result = verify_with_cbmc(state, cwp, bpmn)

    report = unsafe_perform_io(result.unwrap())
    assert isinstance(report, CbmcVerificationReport)
    assert "VERIFICATION SUCCESSFUL" in report.cbmc_report
    assert report.file_path == cbmc.OUTPUT_FILE
    assert "int main(void)" in report.c_code
    assert "--unwinding-assertions" in run.call_args_list[0].args[1]
    assert run.call_args_list[1].args[1][-2:] == ["--cover", "cover"]
    assert "__CPROVER_cover" in _read(cbmc.COVERAGE_OUTPUT_FILE)
    assert "__CPROVER_cover" not in _read(cbmc.OUTPUT_FILE)


def test_verify_with_cbmc_stops_at_assertion_failure(mocker, outputs):
    failing = "[f.assertion.1] line 3 assertion x == 1: FAILURE\n"
    run = mocker.patch.object(cbmc, "_run_cbmc", return_value=IOSuccess(failing))
    state, cwp, bpmn = _parse(STATE, CWP, _read(BPMN))

    result = verify_with_cbmc(state, cwp, bpmn)

    assert isinstance(unsafe_perform_io(result.failure()), CbmcAssertionError)
    assert run.call_count == 1


def test_verify_with_cbmc_reports_unreachable_state(mocker, outputs):
    cover = "[u.coverage.1] file c.c line 5 function u condition 'Negotiations != FALSE': FAILED\n"
    mocker.patch.object(
        cbmc,
        "_run_cbmc",
        side_effect=[IOSuccess(CLEAN_ASSERT_REPORT), IOSuccess(cover)],
    )
    state, cwp, bpmn = _parse(STATE, CWP, _read(BPMN))

    result = verify_with_cbmc(state, cwp, bpmn)

    error = unsafe_perform_io(result.failure())
    assert isinstance(error, CbmcUnreachableStateError)
    assert error.states == ["Negotiations"]


@needs_cbmc
def test_cbmc_end_to_end_reports_unreachable_states(outputs):
    result = cli_verify_cbmc(STATE, CWP, BPMN)

    error = unsafe_perform_io(result.failure())
    assert isinstance(error, CbmcUnreachableStateError)
    assert "Negotiations" in error.states
    assert "Start" not in error.states


@needs_cbmc
def test_cbmc_end_to_end_reports_assertion_failure(outputs):
    result = cli_verify_cbmc(STATE, CWP, _with_update_state(outputs))

    error = unsafe_perform_io(result.failure())
    assert isinstance(error, CbmcAssertionError)
    assert any(f["assertion"] == "Not a valid CWP transition" for f in error.failures)


def test_cli_verify_cbmc_bad_file_is_io_error():
    result = cli_verify_cbmc("missing.txt", CWP, BPMN)

    assert not is_successful(result)


def test_verify_with_cbmc_flag_prints_report(mocker, capsys):
    report = CbmcVerificationReport("f.c", "code", [], "THE REPORT")
    cli = mocker.patch(
        "bpmncwpverify.cli.cli_verify_cbmc", return_value=IOSuccess(report)
    )
    spin = mocker.patch("bpmncwpverify.cli.cli_verify")
    sys.argv = ["verify", "--cbmc", STATE, CWP, BPMN]

    verify()

    cli.assert_called_once_with(STATE, CWP, BPMN)
    spin.assert_not_called()
    assert "THE REPORT" in capsys.readouterr().out


def test_verify_with_cbmc_flag_prints_error_message(capsys):
    sys.argv = ["verify", "--cbmc", "missing.txt", CWP, BPMN]

    verify()

    assert capsys.readouterr().out.strip() != ""


def test_cbmc_and_cloud_flags_are_exclusive():
    sys.argv = ["verify", "--cbmc", "--cloud", STATE, CWP, BPMN]

    with pytest.raises(SystemExit):
        verify()
