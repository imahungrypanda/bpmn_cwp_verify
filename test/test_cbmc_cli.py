# type: ignore
import sys
from unittest import mock

import pytest
from returns.pipeline import is_successful
from returns.unsafe import unsafe_perform_io

from bpmncwpverify.builder.cbmc_builder import CbmcProgram
from bpmncwpverify.cli import cli_verify_cbmc, verify
from bpmncwpverify.core import cbmc
from bpmncwpverify.core.cbmc import _run_program
from bpmncwpverify.core.error import (
    CbmcAssertionError,
    CbmcRunError,
    CbmcUnreachableError,
    get_error_message,
)

FACE2FACE = "./test/resources/face2face/"
SIMPLE = "./test/resources/simple_example/"


def _failure(result):
    assert not is_successful(result)
    return unsafe_perform_io(result.failure())


@pytest.mark.parametrize("bpmn", ["workflow.bpmn", "face2face_open.bpmn"])
def test_given_face2face_when_cbmc_then_verified(bpmn):
    result = cli_verify_cbmc(
        FACE2FACE + "state.txt", FACE2FACE + "cwp.xml", FACE2FACE + bpmn
    )

    assert is_successful(result), get_error_message(_failure(result))
    report = unsafe_perform_io(result.unwrap())
    assert "VERIFICATION SUCCESSFUL" in report.cbmc_report
    assert "FAILED" not in report.cover_report
    assert "REACHABILITY" in report.c_source


def test_given_failing_assertion_when_run_then_assertion_error(tmp_path):
    program = CbmcProgram('int main(void) {\n__CPROVER_assert(0, "boom");\n}\n', 1)

    error = _failure(_run_program(program, str(tmp_path / "a.c")))

    assert isinstance(error, CbmcAssertionError)
    assert error.failures[0]["description"] == "boom"


def test_given_unreachable_cover_when_run_then_unreachable_error(tmp_path):
    source = (
        "enum { CWP_STATE_Done = 3 };\nint cwp_state = 0;\nint main(void) {\n"
        "#ifdef REACHABILITY\n__CPROVER_cover(cwp_state == CWP_STATE_Done);\n#endif\n"
        "return 0;\n}\n"
    )

    error = _failure(_run_program(CbmcProgram(source, 1), str(tmp_path / "a.c")))

    assert isinstance(error, CbmcUnreachableError)
    assert error.unreachable == [{"kind": "CWP state", "name": "Done"}]
    assert "CWP state Done" in get_error_message(error)


def test_given_unwritable_path_when_run_then_error(tmp_path):
    error = _failure(_run_program(CbmcProgram("", 1), str(tmp_path / "no" / "a.c")))

    assert not isinstance(error, CbmcAssertionError | CbmcUnreachableError)


def test_given_cbmc_crashes_when_run_then_run_error(tmp_path):
    program = CbmcProgram("int main(void) { syntax error }\n", 1)

    error = _failure(_run_program(program, str(tmp_path / "a.c")))

    assert isinstance(error, CbmcRunError)


def test_given_cbmc_missing_when_run_then_run_error(tmp_path):
    with mock.patch.object(cbmc.subprocess, "run", side_effect=FileNotFoundError("x")):
        error = _failure(
            _run_program(CbmcProgram("int main(void){}", 1), str(tmp_path / "a.c"))
        )

    assert isinstance(error, CbmcRunError)


def test_given_cbmc_option_when_verify_then_prints_report(capsys):
    sys.argv = [
        "verify",
        "--cbmc",
        FACE2FACE + "state.txt",
        FACE2FACE + "cwp.xml",
        FACE2FACE + "workflow.bpmn",
    ]

    verify()

    assert "VERIFICATION SUCCESSFUL" in capsys.readouterr().out


def test_given_cbmc_option_and_bad_file_when_verify_then_prints_error(capsys):
    sys.argv = ["verify", "--cbmc", "nope.txt", "nope.xml", "nope.bpmn"]

    verify()

    assert capsys.readouterr().out.strip() != ""


def test_given_cbmc_and_cloud_when_verify_then_usage_error():
    sys.argv = ["verify", "--cbmc", "--cloud", "a", "b", "c"]

    with pytest.raises(SystemExit):
        verify()


def test_given_no_cbmc_option_when_verify_then_spin_runs(capsys):
    sys.argv = [
        "verify",
        SIMPLE + "state.txt",
        SIMPLE + "test_cwp.xml",
        SIMPLE + "simple_open.bpmn",
    ]

    verify()

    assert "Spin Version" in capsys.readouterr().out
