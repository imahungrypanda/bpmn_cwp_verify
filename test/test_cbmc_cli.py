# type: ignore
import subprocess
import sys

import pytest
from returns.pipeline import is_successful
from returns.unsafe import unsafe_perform_io

from bpmncwpverify import cli
from bpmncwpverify.cli import cli_verify, cli_verify_with_cbmc, verify
from bpmncwpverify.core.cbmc import _verify_c
from bpmncwpverify.core.error import (
    CbmcAssertionError,
    CbmcRunError,
    CbmcUnreachableError,
    FileReadFileError,
)

FACE2FACE = "test/resources/face2face/"
SIMPLE = "test/resources/simple_example/"

C_PROGRAM = """
int nondet_int(void);
bool reached_end_E = false;
bool reached_cwp_S = false;
int main(void) {{
    int x = nondet_int();
    __CPROVER_assume(x >= 0 && x < 3);
{body}
#ifdef REACHABILITY
    __CPROVER_cover(reached_end_E);
    __CPROVER_cover(reached_cwp_S);
#endif
    return 0;
}}
"""


def _c(body: str) -> str:
    return "#include <stdbool.h>\n" + C_PROGRAM.format(body=body)


def _result(c_code: str, tmp_path):
    return _verify_c(c_code, str(tmp_path / "t.c"), 3)


@pytest.mark.parametrize("bpmn", ["workflow.bpmn", "face2face_open.bpmn"])
def test_cbmc_verifies_face2face(bpmn):
    result = cli_verify_with_cbmc(
        FACE2FACE + "state.txt", FACE2FACE + "cwp.xml", FACE2FACE + bpmn
    )

    assert is_successful(result)
    report = unsafe_perform_io(result.unwrap())
    assert "VERIFICATION SUCCESSFUL" in report.cbmc_report
    assert "FAILED" not in report.cbmc_report
    assert "#ifdef REACHABILITY" in report.c_code


def test_cbmc_bad_file_is_read_error():
    result = cli_verify_with_cbmc("nope.txt", FACE2FACE + "cwp.xml", "nope.bpmn")

    assert isinstance(unsafe_perform_io(result.failure()), FileReadFileError)


def test_cbmc_passes_when_everything_holds(tmp_path):
    code = _c(
        'reached_end_E = true; reached_cwp_S = true; __CPROVER_assert(x < 3, "ok");'
    )

    assert is_successful(_result(code, tmp_path))


def test_cbmc_reports_failed_assertion(tmp_path):
    code = _c(
        'reached_end_E = true; reached_cwp_S = true; __CPROVER_assert(x < 2, "x too big");'
    )

    error = unsafe_perform_io(_result(code, tmp_path).failure())

    assert isinstance(error, CbmcAssertionError)
    assert any("x too big" in failure for failure in error.failures)


def test_cbmc_reports_unreachable_end_event_and_state(tmp_path):
    error = unsafe_perform_io(_result(_c("x = x;"), tmp_path).failure())

    assert isinstance(error, CbmcUnreachableError)
    assert error.unreached == ["end event E", "CWP state S"]


def test_cbmc_reports_one_unreachable_state(tmp_path):
    error = unsafe_perform_io(_result(_c("reached_end_E = true;"), tmp_path).failure())

    assert isinstance(error, CbmcUnreachableError)
    assert error.unreached == ["CWP state S"]


def test_cbmc_assertion_takes_priority_over_unreachable(tmp_path):
    error = unsafe_perform_io(
        _result(_c('__CPROVER_assert(false, "boom");'), tmp_path).failure()
    )

    assert isinstance(error, CbmcAssertionError)


def test_cbmc_syntax_error_is_run_error(tmp_path):
    error = unsafe_perform_io(_result("int main( {", tmp_path).failure())

    assert isinstance(error, CbmcRunError)


def test_cbmc_missing_binary_is_run_error(tmp_path, monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("cbmc")

    monkeypatch.setattr(subprocess, "run", missing)

    error = unsafe_perform_io(_result(_c(""), tmp_path).failure())

    assert isinstance(error, CbmcRunError)


def test_cbmc_unwind_is_bound_plus_one(tmp_path, monkeypatch):
    calls = []
    real_run = subprocess.run

    def spy(args, **kwargs):
        calls.append(args)
        return real_run(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)
    code = _c("reached_end_E = true; reached_cwp_S = true;")

    assert is_successful(_result(code, tmp_path))
    assert len(calls) == 2
    assert all(args[args.index("--unwind") + 1] == "4" for args in calls)
    assert "-DREACHABILITY" not in calls[0] and "-DREACHABILITY" in calls[1]


def test_verify_cbmc_option_prints_report(capsys, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify",
            "--cbmc",
            FACE2FACE + "state.txt",
            FACE2FACE + "cwp.xml",
            FACE2FACE + "workflow.bpmn",
        ],
    )

    verify()

    assert "VERIFICATION SUCCESSFUL" in capsys.readouterr().out


def test_verify_cbmc_option_prints_error(capsys, monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["verify", "--cbmc", "nope.txt", "nope.xml", "nope.bpmn"]
    )

    verify()

    assert "FILE ERROR" in capsys.readouterr().out


def test_verify_cbmc_with_cloud_is_rejected(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["verify", "--cbmc", "--cloud", "a.txt", "b.xml", "c.bpmn"]
    )

    with pytest.raises(SystemExit):
        verify()


def test_verify_without_cbmc_still_uses_spin(capsys, monkeypatch):
    monkeypatch.setattr(
        cli, "cli_verify_with_cbmc", lambda *_: pytest.fail("CBMC must not run")
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify",
            FACE2FACE + "state.txt",
            FACE2FACE + "cwp.xml",
            FACE2FACE + "workflow.bpmn",
        ],
    )

    verify()

    assert "pan:" in capsys.readouterr().out
    assert is_successful(
        cli_verify(
            FACE2FACE + "state.txt", FACE2FACE + "cwp.xml", FACE2FACE + "workflow.bpmn"
        )
    )
