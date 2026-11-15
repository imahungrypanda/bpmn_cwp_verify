# type: ignore
import shutil
import sys
import time
from unittest import mock

import pytest
from returns.functions import not_
from returns.pipeline import is_successful
from returns.unsafe import unsafe_perform_io

from bpmncwpverify.cli import cli_verify, cli_verify_cbmc, verify
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

RES = "./test/resources/"
FACE2FACE = RES + "face2face/"
SIMPLE = RES + "simple_example/"

pytestmark = pytest.mark.skipif(
    shutil.which("cbmc") is None, reason="cbmc is not installed"
)


def _simple_with_behavior(tmp_path, behavior: str) -> str:
    with open(SIMPLE + "simple_open.bpmn") as f:
        text = f.read()
    assert "x = x + 1" in text
    path = tmp_path / "workflow.bpmn"
    path.write_text(text.replace("x = x + 1", behavior))
    return str(path)


def _simple(bpmn: str):
    return cli_verify_cbmc(SIMPLE + "state.txt", SIMPLE + "test_cwp.xml", bpmn)


def _failure(result):
    assert not_(is_successful)(result)
    return unsafe_perform_io(result.failure())


@pytest.mark.parametrize("bpmn", ["workflow.bpmn", "face2face_open.bpmn"])
def test_given_face2face_when_verify_cbmc_then_verified_in_under_a_minute(bpmn):
    start = time.time()

    result = cli_verify_cbmc(
        FACE2FACE + "state.txt", FACE2FACE + "cwp.xml", FACE2FACE + bpmn
    )

    assert is_successful(result), _failure(result) if not is_successful(result) else ""
    assert time.time() - start < 60
    report = unsafe_perform_io(result.unwrap())
    assert isinstance(report, CbmcVerificationReport)
    assert "VERIFICATION SUCCESSFUL" in report.cbmc_report
    assert "REACHABILITY" not in report.cbmc_cli_args[0]
    assert "-DREACHABILITY" in report.cbmc_cli_args[1]
    assert report.cbmc_cli_args[0][:2] == ["--unwind", report.cbmc_cli_args[1][1]]


def test_given_workflow_that_reaches_end_when_verify_cbmc_then_success(tmp_path):
    result = _simple(_simple_with_behavior(tmp_path, "x = x + 6"))

    assert is_successful(result)


def test_given_failing_assertion_when_verify_cbmc_then_assertion_error(tmp_path):
    result = _simple(_simple_with_behavior(tmp_path, "x = x + 6; assert(x < 3)"))

    error = _failure(result)
    assert isinstance(error, CbmcAssertionError)
    assert any("x < 3" in f["description"] for f in error.failures)


def test_given_workflow_that_never_ends_when_verify_cbmc_then_unreachable_error(
    tmp_path,
):
    result = _simple(_simple_with_behavior(tmp_path, "x = x + 0"))

    error = _failure(result)
    assert isinstance(error, CbmcUnreachableError)
    names = {(u["kind"], u["name"]) for u in error.unreachable}
    assert ("CWP state", "End") in names
    assert any(kind == "end event" for kind, _ in names)
    # The start state is not something the workflow has to reach
    assert ("CWP state", "Start") not in names


def test_given_cbmc_cannot_run_when_verify_cbmc_then_run_error(tmp_path):
    with mock.patch.object(cbmc.subprocess, "run", side_effect=FileNotFoundError("x")):
        result = _simple(_simple_with_behavior(tmp_path, "x = x + 6"))

    assert isinstance(_failure(result), CbmcRunError)


def test_given_cbmc_exits_with_error_when_verify_cbmc_then_run_error(tmp_path):
    failed = mock.Mock(returncode=6, stdout="CONVERSION ERROR", stderr="")
    with mock.patch.object(cbmc.subprocess, "run", return_value=failed):
        result = _simple(_simple_with_behavior(tmp_path, "x = x + 6"))

    error = _failure(result)
    assert isinstance(error, CbmcRunError)
    assert "CONVERSION ERROR" in error.msg


def test_given_unsupported_bpmn_when_verify_cbmc_then_build_error(tmp_path):
    result = _simple(_simple_with_behavior(tmp_path, "printf(1)"))

    assert not_(is_successful)(result)


def test_given_missing_file_when_verify_cbmc_then_io_error():
    result = cli_verify_cbmc("nope.txt", SIMPLE + "test_cwp.xml", SIMPLE + "x.bpmn")

    assert not_(is_successful)(result)


def test_check_assertions_ignores_successes():
    report = "[main.assertion.1] line 3 x == 1: SUCCESS\n"

    assert is_successful(check_assertions(report))


def test_check_assertions_collects_failures():
    report = (
        "[main.assertion.1] line 3 x == 1: FAILURE\n"
        "[main.unwind.0] line 9 unwinding assertion loop 0: FAILURE\n"
    )

    error = check_assertions(report).failure()

    assert [f["line"] for f in error.failures] == ["3", "9"]


def test_check_reachability_names_unsatisfied_covers():
    c = "a\n__CPROVER_cover(1); /* end event E1 */\n"
    report = (
        "[f.coverage.1] file x.c line 2 function f condition '1 != 0': FAILED\n"
        "[f.coverage.2] file x.c line 1 function f condition '1 != 0': SATISFIED\n"
    )

    error = check_reachability(report, c).failure()

    assert error.unreachable == [{"kind": "end event", "name": "E1", "line": "2"}]


def test_given_cbmc_option_when_verify_then_prints_report(tmp_path, capsys):
    bpmn = _simple_with_behavior(tmp_path, "x = x + 6")
    sys.argv = [
        "verify",
        SIMPLE + "state.txt",
        SIMPLE + "test_cwp.xml",
        bpmn,
        "--cbmc",
    ]

    verify()

    assert "VERIFICATION SUCCESSFUL" in capsys.readouterr().out


def test_given_cbmc_option_and_failure_when_verify_then_prints_error(tmp_path, capsys):
    bpmn = _simple_with_behavior(tmp_path, "x = x + 6; assert(x < 3)")
    sys.argv = [
        "verify",
        SIMPLE + "state.txt",
        SIMPLE + "test_cwp.xml",
        bpmn,
        "--cbmc",
    ]

    verify()

    assert "CBMC ERROR: assertion failed" in capsys.readouterr().out


def test_given_no_cbmc_option_when_verify_then_spin_runs(capsys):
    sys.argv = [
        "verify",
        SIMPLE + "state.txt",
        SIMPLE + "test_cwp.xml",
        SIMPLE + "simple_open.bpmn",
    ]

    verify()

    assert "pan:" in capsys.readouterr().out
    assert is_successful(
        cli_verify(
            SIMPLE + "state.txt", SIMPLE + "test_cwp.xml", SIMPLE + "simple_open.bpmn"
        )
    )
