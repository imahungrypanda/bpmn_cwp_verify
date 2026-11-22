# type: ignore
import sys

import pytest
from returns.pipeline import is_successful
from returns.unsafe import unsafe_perform_io

from bpmncwpverify.builder.cbmc_builder import CbmcProgram
from bpmncwpverify.cli import cli_verify, verify
from bpmncwpverify.core.cbmc import (
    CbmcVerificationReport,
    _check_assertions,
    _check_reachability,
    _verify,
)
from bpmncwpverify.core.error import (
    CbmcAssertionError,
    CbmcRunError,
    CbmcUnreachableError,
)

F2F = "./test/resources/face2face/"
SIMPLE = "./test/resources/simple_example/"


def _run_cli(capsys, *args):
    sys.argv = ["verify", *args]
    verify()
    return capsys.readouterr().out


def _program(body: str) -> CbmcProgram:
    return CbmcProgram(f"int main(void) {{\n{body}\n}}\n", 1)


@pytest.mark.parametrize("bpmn", ["workflow.bpmn", "face2face_open.bpmn"])
def test_given_face2face_when_verify_with_cbmc_then_verified(capsys, bpmn):
    out = _run_cli(capsys, F2F + "state.txt", F2F + "cwp.xml", F2F + bpmn, "--cbmc")

    assert "VERIFICATION SUCCESSFUL" in out
    assert "coverage results" in out
    assert "FAILED" not in out
    assert "error" not in out.lower()


def test_given_unreachable_end_when_verify_with_cbmc_then_unreachable_error(capsys):
    out = _run_cli(
        capsys,
        SIMPLE + "state.txt",
        SIMPLE + "test_cwp.xml",
        SIMPLE + "simple_open.bpmn",
        "--cbmc",
    )

    assert "CBMC reachability error" in out
    assert "BPMN end event End" in out
    assert "CWP state End" in out


def test_given_no_cbmc_option_when_verify_then_spin_runs(capsys):
    out = _run_cli(
        capsys,
        SIMPLE + "state.txt",
        SIMPLE + "test_cwp.xml",
        SIMPLE + "simple_open.bpmn",
    )

    assert "pan:" in out
    assert "CBMC" not in out


def test_given_bad_file_when_verify_with_cbmc_then_error(capsys):
    out = _run_cli(
        capsys,
        "nope.txt",
        SIMPLE + "test_cwp.xml",
        SIMPLE + "simple_open.bpmn",
        "--cbmc",
    )

    assert "nope.txt" in out


def test_given_passing_c_when_verify_then_report(tmp_path):
    program = _program('__CPROVER_assert(1, "fine");')

    result = _verify(program, str(tmp_path / "v.c"))

    assert is_successful(result)
    report = unsafe_perform_io(result.unwrap())
    assert isinstance(report, CbmcVerificationReport)
    assert report.bound == 1
    assert "VERIFICATION SUCCESSFUL" in report.cbmc_report


def test_given_failing_assertion_when_verify_then_assertion_error(tmp_path):
    program = _program('int x = 1;\n__CPROVER_assert(x == 2, "x is two");')

    result = _verify(program, str(tmp_path / "v.c"))

    error = unsafe_perform_io(result.failure())
    assert isinstance(error, CbmcAssertionError)
    assert [f["description"] for f in error.failures] == ["x is two"]


def test_given_unreachable_cover_when_verify_then_unreachable_error(tmp_path):
    program = _program(
        "int x = 1;\n"
        "#ifdef REACHABILITY\n"
        "__CPROVER_cover(x == 1); /* reached */\n"
        "__CPROVER_cover(x == 2); /* never */\n"
        "#endif"
    )

    result = _verify(program, str(tmp_path / "v.c"))

    error = unsafe_perform_io(result.failure())
    assert isinstance(error, CbmcUnreachableError)
    assert error.unreachable == ["never"]


def test_given_invalid_c_when_verify_then_run_error(tmp_path):
    program = CbmcProgram("int main(void) { this is not C }", 1)

    result = _verify(program, str(tmp_path / "v.c"))

    assert isinstance(unsafe_perform_io(result.failure()), CbmcRunError)


def test_given_unwritable_path_when_verify_then_error(tmp_path):
    result = _verify(_program(""), str(tmp_path / "missing" / "v.c"))

    assert not is_successful(result)


def test_given_report_without_failures_when_checked_then_success():
    assert is_successful(_check_assertions("[a] line 1 ok: SUCCESS"))
    assert is_successful(_check_reachability("[a] file f line 1 x: SATISFIED", ""))


def test_given_spin_cli_verify_unchanged(capsys):
    result = cli_verify(
        SIMPLE + "state.txt", SIMPLE + "test_cwp.xml", SIMPLE + "simple_open.bpmn"
    )

    assert is_successful(result)
