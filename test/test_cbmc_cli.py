# type: ignore
import shutil
import sys
import time
from pathlib import Path

import pytest
from returns.pipeline import is_successful
from returns.unsafe import unsafe_perform_io

from bpmncwpverify import cli
from bpmncwpverify.cli import cli_verify, verify
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
)
from bpmncwpverify.core.spin import SpinVerificationReport

RESOURCES = Path(__file__).parent / "resources"
FACE2FACE = RESOURCES / "feel" / "face2face"
SIMPLE = RESOURCES / "feel" / "simple_example"

needs_cbmc = pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc missing")


def _files(folder: Path, bpmn: str, cwp: str) -> tuple[str, str, str]:
    return str(folder / "state.txt"), str(folder / cwp), str(folder / bpmn)


def _failure(result):
    assert not is_successful(result)
    return unsafe_perform_io(result.failure())


@needs_cbmc
@pytest.mark.parametrize("bpmn", ["workflow.bpmn", "face2face_open.bpmn"])
def test_given_face2face_when_verify_with_cbmc_then_verified(bpmn):
    start = time.monotonic()
    result = cli_verify(*_files(FACE2FACE, bpmn, "cwp.xml"), cbmc=True)
    assert time.monotonic() - start < 60

    assert is_successful(result), _failure(result) if not is_successful(result) else ""
    report = unsafe_perform_io(result.unwrap())
    assert isinstance(report, CbmcVerificationReport)
    assert "VERIFICATION SUCCESSFUL" in report.cbmc_report
    assert "7 of 7 covered" in report.cbmc_report


@needs_cbmc
def test_given_failing_assertion_when_verify_with_cbmc_then_assertion_error(tmp_path):
    bpmn = (
        (SIMPLE / "simple_open.bpmn")
        .read_text()
        .replace("x = x + 1", "assert(x > 100)")
    )
    (tmp_path / "bad.bpmn").write_text(bpmn)
    state, cwp, _ = _files(SIMPLE, "", "test_cwp.xml")

    error = _failure(cli_verify(state, cwp, str(tmp_path / "bad.bpmn"), cbmc=True))

    assert isinstance(error, CbmcAssertionError)
    assert any("behavior of" in f["description"] for f in error.failures)


@needs_cbmc
def test_given_unreachable_state_when_verify_with_cbmc_then_unreachable_error(
    tmp_path,
):
    # the loop never gets x past 5 when the task adds 0 instead of 1
    bpmn = (SIMPLE / "simple_open.bpmn").read_text().replace("x + 1", "x + 0")
    (tmp_path / "stuck.bpmn").write_text(bpmn)
    state, cwp, _ = _files(SIMPLE, "", "test_cwp.xml")

    error = _failure(cli_verify(state, cwp, str(tmp_path / "stuck.bpmn"), cbmc=True))

    assert isinstance(error, CbmcUnreachableError)
    assert "CWP state: End" in error.unreachable
    assert not any("Start" in item for item in error.unreachable)


def test_given_failure_lines_when_check_assertions_then_assertion_error():
    output = (
        "[main.assertion.1] line 9 token placed on an occupied place: SUCCESS\n"
        "[main.assertion.2] line 12 CWP: not a valid CWP transition: FAILURE\n"
        "[main.unwind.0] line 30 unwinding assertion loop 0: FAILURE\n"
    )

    error = check_assertions(output).failure()

    assert isinstance(error, CbmcAssertionError)
    assert error.failures == [
        {"description": "CWP: not a valid CWP transition", "line": "12"},
        {"description": "unwinding assertion loop 0", "line": "30"},
    ]


def test_given_no_failures_when_check_assertions_then_success():
    assert is_successful(check_assertions("[main.assertion.1] line 9 x: SUCCESS\n"))


def test_given_failed_covers_when_check_reachability_then_unreachable_error():
    c_code = "\n".join(
        [
            "void f(void) {",
            "  __CPROVER_cover(a); /* CWP state: A */",
            "  __CPROVER_cover(1); /* end event: E */",
            "  __CPROVER_cover(b);",
            "}",
        ]
    )
    output = (
        "[f.coverage.1] file x.c line 2 function f condition 'a': FAILED\n"
        "[f.coverage.2] file x.c line 3 function f condition '1': SATISFIED\n"
        "[f.coverage.3] file x.c line 4 function f condition 'b': FAILED\n"
    )

    error = check_reachability(output, c_code).failure()

    assert isinstance(error, CbmcUnreachableError)
    assert error.unreachable == ["CWP state: A", "cover at line 4"]


def test_given_all_covers_satisfied_when_check_reachability_then_success():
    output = "[f.coverage.1] file x.c line 1 function f condition 'a': SATISFIED\n"

    assert is_successful(check_reachability(output, "x"))


def test_given_cbmc_error_exit_when_check_run_then_run_error():
    error = cbmc._check_run(6, "CONVERSION ERROR").failure()

    assert isinstance(error, CbmcRunError)
    assert "CONVERSION ERROR" in error.reason


def test_given_missing_cbmc_when_verify_then_run_error(monkeypatch):
    monkeypatch.setenv("PATH", "")

    error = _failure(
        cli_verify(*_files(SIMPLE, "simple_open.bpmn", "test_cwp.xml"), cbmc=True)
    )

    assert isinstance(error, CbmcRunError)


def test_given_cbmc_option_when_verify_then_prints_cbmc_report(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["verify", *_files(SIMPLE, "simple_open.bpmn", "test_cwp.xml"), "--cbmc"],
    )
    called = []

    def fake(*args):
        called.append(args)
        from returns.io import IOSuccess

        return IOSuccess(CbmcVerificationReport("f.c", "c", [], "CBMC REPORT"))

    monkeypatch.setattr(cli, "verify_with_cbmc", fake)
    # _verify_with_spin picks the back end when it runs
    verify()

    assert called
    assert "CBMC REPORT" in capsys.readouterr().out


@pytest.mark.parametrize("cbmc_flag", [False])
def test_given_no_cbmc_option_when_cli_verify_then_spin_report(cbmc_flag):
    if shutil.which("spin") is None:
        pytest.skip("spin missing")

    result = cli_verify(*_files(FACE2FACE, "workflow.bpmn", "cwp.xml"), cbmc=cbmc_flag)

    assert isinstance(unsafe_perform_io(result.unwrap()), SpinVerificationReport)


def test_given_cbmc_and_cloud_when_verify_then_refuses(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["verify", "a", "b", "c", "--cbmc", "--cloud"])

    verify()

    assert "cannot be combined" in capsys.readouterr().out
