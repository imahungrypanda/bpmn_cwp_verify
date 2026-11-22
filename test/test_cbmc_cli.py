# type: ignore
import sys

import pytest
from returns.pipeline import is_successful
from returns.unsafe import unsafe_perform_io

from bpmncwpverify import cli
from bpmncwpverify.cli import cli_verify, cli_verify_with_cbmc, verify
from bpmncwpverify.core import cbmc
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
from bpmncwpverify.core.spin import SpinVerificationReport

RESOURCES = "./test/resources"
FACE2FACE = f"{RESOURCES}/face2face"
SIMPLE = f"{RESOURCES}/simple_example"

C_TEMPLATE = """
void main(void) {{
    int x = 1;
    for (unsigned int pass = 0; pass < 2u; pass++) {{
        {body}
#ifdef REACHABILITY
        __CPROVER_cover(x == 1); /* cover: reachable thing */
        __CPROVER_cover(x == 2); /* cover: unreachable thing */
#endif
    }}
}}
"""


def _failure(result):
    assert not is_successful(result)
    return unsafe_perform_io(result.failure())


@pytest.mark.parametrize("bpmn", ["workflow.bpmn", "face2face_open.bpmn"])
def test_given_face2face_when_cbmc_then_verifies(bpmn):
    result = cli_verify_with_cbmc(
        f"{FACE2FACE}/state.txt", f"{FACE2FACE}/cwp.xml", f"{FACE2FACE}/{bpmn}"
    )

    assert is_successful(result)
    report = unsafe_perform_io(result.unwrap())
    assert isinstance(report, CbmcVerificationReport)
    assert "VERIFICATION SUCCESSFUL" in report.cbmc_report
    assert "coverage results" in report.cbmc_report


def test_given_unreachable_end_when_cbmc_then_unreachable_error():
    # The bound can't cover a loop that depends on the variable's value
    result = cli_verify_with_cbmc(
        f"{SIMPLE}/state.txt", f"{SIMPLE}/test_cwp.xml", f"{SIMPLE}/simple_open.bpmn"
    )

    error = _failure(result)
    assert isinstance(error, CbmcUnreachableError)
    assert "CWP state End" in error.unreachable
    assert "end event event_JS1LAA" in error.unreachable


def test_given_bad_state_file_when_cbmc_then_io_error():
    result = cli_verify_with_cbmc(
        "missing.txt", f"{SIMPLE}/test_cwp.xml", f"{SIMPLE}/simple_open.bpmn"
    )

    assert not is_successful(result)


def test_given_failed_assertion_when_verify_then_assertion_error(tmp_path):
    c = C_TEMPLATE.format(body='__CPROVER_assert(x == 2, "x is two");')

    error = _failure(_verify(c, str(tmp_path / "a.c"), 3))

    assert isinstance(error, CbmcAssertionError)
    assert any(f["description"] == "x is two" for f in error.failures)


def test_given_loop_past_bound_when_verify_then_assertion_error(tmp_path):
    c = "void main(void) { unsigned n = 0; while (n < 100u) n++; }"

    error = _failure(_verify(c, str(tmp_path / "a.c"), 3))

    assert isinstance(error, CbmcAssertionError)
    assert any("unwinding" in f["description"] for f in error.failures)


def test_given_unreachable_cover_when_verify_then_names_it(tmp_path):
    c = C_TEMPLATE.format(body="")

    error = _failure(_verify(c, str(tmp_path / "a.c"), 3))

    assert isinstance(error, CbmcUnreachableError)
    assert error.unreachable == ["unreachable thing"]


def test_given_everything_holds_when_verify_then_report(tmp_path):
    c = C_TEMPLATE.format(body="x = 3 - x;").replace("x == 2", "x == 1")

    result = _verify(c, str(tmp_path / "a.c"), 3)

    report = unsafe_perform_io(result.unwrap())
    assert report.unwind == 3
    assert report.c == c


def test_given_cbmc_missing_when_verify_then_run_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))

    error = _failure(_verify("int main(void){return 0;}", str(tmp_path / "a.c"), 1))

    assert isinstance(error, CbmcRunError)


def test_given_c_syntax_error_when_verify_then_run_error(tmp_path):
    error = _failure(_verify("int main(void) {", str(tmp_path / "a.c"), 1))

    assert isinstance(error, CbmcRunError)


def test_given_unparsable_output_then_run_error():
    assert isinstance(_failure_of(_check_assertions("garbage")), CbmcRunError)
    assert isinstance(_failure_of(_check_reachability("garbage", "")), CbmcRunError)


def _failure_of(result):
    return result.failure()


def test_given_unmarked_cover_then_named_by_line():
    report = "[main.coverage.1] file a.c line 2 function main condition 'x': FAILED\n"

    error = _failure_of(_check_reachability(report, "a\nb\n"))

    assert error.unreachable == ["line 2"]


def test_given_cbmc_flag_when_verify_then_prints_cbmc_report(capsys):
    sys.argv = [
        "verify",
        "--cbmc",
        f"{SIMPLE}/state.txt",
        f"{SIMPLE}/test_cwp.xml",
        f"{SIMPLE}/simple_open.bpmn",
    ]

    verify()

    assert "The workflow can never reach: CWP state End" in capsys.readouterr().out


def test_given_cbmc_and_cloud_when_verify_then_usage_error():
    sys.argv = ["verify", "--cbmc", "--cloud", "s", "c", "b"]

    with pytest.raises(SystemExit):
        verify()


def test_given_no_cbmc_flag_when_verify_then_still_runs_spin(capsys):
    sys.argv = [
        "verify",
        f"{SIMPLE}/state.txt",
        f"{SIMPLE}/test_cwp.xml",
        f"{SIMPLE}/simple_open.bpmn",
    ]
    result = cli_verify(sys.argv[1], sys.argv[2], sys.argv[3])

    verify()

    assert isinstance(unsafe_perform_io(result.unwrap()), SpinVerificationReport)
    assert "pan:" in capsys.readouterr().out


def test_cli_module_exposes_cbmc_runner():
    assert cli.verify_with_cbmc is cbmc.verify_with_cbmc
