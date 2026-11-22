# type: ignore
import shutil
import sys
import time
from pathlib import Path

import pytest
from returns.pipeline import is_successful
from returns.unsafe import unsafe_perform_io

from bpmncwpverify.cli import cli_verify_cbmc, verify
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
    FileReadFileError,
    get_error_message,
)

RES = Path(__file__).parent / "resources"
HAS_CBMC = shutil.which("cbmc") is not None
needs_cbmc = pytest.mark.skipif(not HAS_CBMC, reason="cbmc is not installed")


def _files(folder: str, bpmn: str, cwp: str = "cwp.xml"):
    return (
        str(RES / folder / "state.txt"),
        str(RES / folder / cwp),
        str(RES / folder / bpmn),
    )


def _failure(result):
    assert not is_successful(result)
    return unsafe_perform_io(result.failure())


@needs_cbmc
@pytest.mark.parametrize("bpmn", ["workflow.bpmn", "face2face_open.bpmn"])
def test_face2face_verifies_with_cbmc(bpmn):
    start = time.time()
    result = cli_verify_cbmc(*_files("face2face", bpmn))
    assert time.time() - start < 60
    assert is_successful(result)
    report = unsafe_perform_io(result.unwrap())
    assert isinstance(report, CbmcVerificationReport)
    assert "VERIFICATION SUCCESSFUL" in report.cbmc_report
    assert "covered (100.0%)" in report.reachability_report


@needs_cbmc
def test_failed_assertion_is_reported(tmp_path, monkeypatch):
    # an assertion that can never hold: break the CWP transition check
    orig = cbmc.CbmcBuilder.build

    def build(self):
        program = orig(self)
        bad = program.unwrap()
        bad.source = bad.source.replace(
            '__CPROVER_assert(cwp_valid_move, "Not a valid CWP transition");',
            '__CPROVER_assert(0, "forced failure");',
        )
        return program

    monkeypatch.setattr(cbmc.CbmcBuilder, "build", build)
    error = _failure(cli_verify_cbmc(*_files("face2face", "workflow.bpmn")))
    assert isinstance(error, CbmcAssertionError)
    assert any(f["description"] == "forced failure" for f in error.failures)
    assert "forced failure" in get_error_message(error)


@needs_cbmc
def test_unreachable_state_is_reported(monkeypatch):
    orig = cbmc.CbmcBuilder.build

    def build(self):
        program = orig(self)
        bad = program.unwrap()
        # a state that can never be the active one
        bad.source = bad.source.replace(
            "__CPROVER_cover(cwp_state == CWP_STATE_Purchase_Failed);",
            "__CPROVER_cover(cwp_state == 99);",
        )
        return program

    monkeypatch.setattr(cbmc.CbmcBuilder, "build", build)
    error = _failure(cli_verify_cbmc(*_files("face2face", "workflow.bpmn")))
    assert isinstance(error, CbmcUnreachableError)
    assert error.unreachable == ["CWP state Purchase_Failed"]


@needs_cbmc
def test_cbmc_that_cannot_run_is_reported(monkeypatch):
    monkeypatch.setenv("PATH", "")
    error = _failure(cli_verify_cbmc(*_files("face2face", "workflow.bpmn")))
    assert isinstance(error, CbmcRunError)


@needs_cbmc
def test_c_that_does_not_compile_is_a_run_error(tmp_path):
    path = tmp_path / "bad.c"
    result = cbmc._verify("int main(void) { return x; }", 2, str(path))
    assert isinstance(_failure(result), CbmcRunError)


def test_check_assertions_ignores_successes():
    report = "[main.assertion.1] line 3 ok: SUCCESS\n[main.assertion.2] line 4 bad one: FAILURE\n"
    error = check_assertions("f.c", report).failure()
    assert error.failures == [
        {
            "id": "main.assertion.2",
            "line": "4",
            "description": "bad one",
            "status": "FAILURE",
        }
    ]
    assert is_successful(check_assertions("f.c", "[a.assertion.1] line 3 ok: SUCCESS"))


def test_check_reachability_names_the_unreached():
    source = "a\nb // end event E1\nc // CWP state S\n"
    report = (
        "[f.coverage.1] file m.c line 2 condition 'x': FAILED\n"
        "[f.coverage.2] file m.c line 3 condition 'y': SATISFIED\n"
        "[f.coverage.3] file m.c line 1 condition 'z': FAILED\n"
    )
    assert check_reachability(source, report).failure().unreachable == [
        "end event E1",
        "line 1",
    ]


def test_missing_file_is_a_read_error():
    error = _failure(cli_verify_cbmc("nope.txt", "nope.xml", "nope.bpmn"))
    assert isinstance(error, FileReadFileError)


@needs_cbmc
def test_cli_cbmc_option_prints_report(capsys):
    sys.argv = ["verify", *_files("face2face", "workflow.bpmn"), "--cbmc"]
    verify()
    out = capsys.readouterr().out
    assert "VERIFICATION SUCCESSFUL" in out
    assert "covered (100.0%)" in out


def test_cli_cbmc_with_cloud_is_rejected():
    sys.argv = ["verify", *_files("face2face", "workflow.bpmn"), "--cbmc", "--cloud"]
    with pytest.raises(SystemExit):
        verify()


def test_cli_without_cbmc_still_uses_spin(capsys):
    sys.argv = ["verify", *_files("face2face", "workflow.bpmn")]
    verify()
    assert "State-vector" in capsys.readouterr().out
