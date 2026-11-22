# type: ignore
import subprocess
import sys
import time
from pathlib import Path

import pytest
from returns.pipeline import is_successful
from returns.unsafe import unsafe_perform_io

from bpmncwpverify.cli import cli_verify, cli_verify_cbmc, verify
from bpmncwpverify.core import cbmc
from bpmncwpverify.core.cbmc import (
    CbmcVerificationReport,
    parse_assertion_failures,
    parse_unreached,
)
from bpmncwpverify.core.error import (
    CbmcAssertionError,
    CbmcRunError,
    CbmcUnreachableError,
    FileReadFileError,
    get_error_message,
)
from bpmncwpverify.core.spin import SpinVerificationReport

FACE2FACE = Path("test/resources/face2face")
STATE = str(FACE2FACE / "state.txt")
CWP = str(FACE2FACE / "cwp.xml")
WORKFLOW = FACE2FACE / "workflow.bpmn"
OPEN_WORKFLOW = FACE2FACE / "face2face_open.bpmn"


def mutated_workflow(tmp_path, old, new):
    text = WORKFLOW.read_text()
    assert old in text
    path = tmp_path / "mutated.bpmn"
    path.write_text(text.replace(old, new, 1))
    return str(path)


def failure_of(result):
    return unsafe_perform_io(result.failure())


@pytest.mark.parametrize("bpmn", [WORKFLOW, OPEN_WORKFLOW], ids=lambda p: p.name)
def test_given_face2face_when_verify_with_cbmc_then_verified_in_under_a_minute(bpmn):
    start = time.monotonic()

    result = cli_verify_cbmc(STATE, CWP, str(bpmn))

    assert is_successful(result), get_error_message(failure_of(result))
    assert time.monotonic() - start < 60
    report = unsafe_perform_io(result.unwrap())
    assert isinstance(report, CbmcVerificationReport)
    assert "VERIFICATION SUCCESSFUL" in report.assertion_report
    assert "covered (100.0%)" in report.reachability_report
    assert Path(report.file_path).read_text() == report.c_code


def test_given_invalid_cwp_transition_when_verify_with_cbmc_then_assertion_error(
    tmp_path,
):
    bpmn = mutated_workflow(
        tmp_path,
        ":: true -&gt; terms = failed",
        ":: true -&gt; terms = failed\n:: true -&gt; terms = noRetry",
    )

    result = cli_verify_cbmc(STATE, CWP, bpmn)

    error = failure_of(result)
    assert isinstance(error, CbmcAssertionError)
    assert any("next ==" in f["description"] for f in error.failures)
    assert get_error_message(error).startswith("Assertion Error:")


def test_given_unreachable_cwp_state_when_verify_with_cbmc_then_unreachable_error(
    tmp_path,
):
    # Nothing sets paymentOwner, so Ownerships_Switched can never be reached
    bpmn = mutated_workflow(
        tmp_path,
        "<bpmn:documentation>paymentOwner = sellerName</bpmn:documentation>",
        "<bpmn:documentation>paymentOwner = buyerName</bpmn:documentation>",
    )

    result = cli_verify_cbmc(STATE, CWP, bpmn)

    error = failure_of(result)
    assert isinstance(error, CbmcUnreachableError)
    assert [u["description"] for u in error.unreached] == [
        "cwp_state == CWP_Ownerships_Switched"
    ]
    assert "can never be reached" in get_error_message(error)


def test_given_missing_state_file_when_verify_with_cbmc_then_read_error():
    result = cli_verify_cbmc("nope.txt", CWP, str(WORKFLOW))

    assert isinstance(failure_of(result), FileReadFileError)


def test_given_cbmc_cannot_start_when_verify_with_cbmc_then_run_error(monkeypatch):
    def fail(*args, **kwargs):
        raise FileNotFoundError("cbmc")

    monkeypatch.setattr(cbmc.subprocess, "run", fail)

    result = cli_verify_cbmc(STATE, CWP, str(WORKFLOW))

    error = failure_of(result)
    assert isinstance(error, CbmcRunError)
    assert "cbmc" in get_error_message(error)


def test_given_cbmc_exits_with_error_when_verify_with_cbmc_then_run_error(
    monkeypatch,
):
    def bad_exit(args, **kwargs):
        return subprocess.CompletedProcess(args, 6, "", "PARSING ERROR")

    monkeypatch.setattr(cbmc.subprocess, "run", bad_exit)

    result = cli_verify_cbmc(STATE, CWP, str(WORKFLOW))

    error = failure_of(result)
    assert isinstance(error, CbmcRunError)
    assert "PARSING ERROR" in error.reason


def test_given_cbmc_output_when_parsed_then_failures_and_unreached_found():
    report = (
        "[main.assertion.1] line 9 assertion x == 1: SUCCESS\n"
        "[main.assertion.2] line 10 assertion x == 2: FAILURE\n"
        "[main.unwind.0] line 20 unwinding assertion loop 0: FAILURE\n"
    )
    failures = parse_assertion_failures(report).failure().failures
    assert [f["property"] for f in failures] == ["main.assertion.2", "main.unwind.0"]
    assert (
        parse_assertion_failures("[a] line 1 assertion 1: SUCCESS\n").unwrap() is None
    )

    c_code = "int x;\n__CPROVER_cover(x == 1);\n__CPROVER_cover(x == 2);\n"
    cover = (
        "[f.coverage.1] file a.c line 2 function f condition 'x': SATISFIED\n"
        "[f.coverage.2] file a.c line 3 function f condition 'x': FAILED\n"
    )
    unreached = parse_unreached(c_code, cover).failure().unreached
    assert [(u["line"], u["description"]) for u in unreached] == [("3", "x == 2")]
    assert (
        parse_unreached(c_code, cover.replace("FAILED", "SATISFIED")).unwrap() is None
    )


def test_given_cbmc_flag_when_verify_then_prints_cbmc_report(monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv", ["verify", "--cbmc", STATE, CWP, str(OPEN_WORKFLOW)]
    )

    verify()

    out = capsys.readouterr().out
    assert "VERIFICATION SUCCESSFUL" in out
    assert "covered (100.0%)" in out


def test_given_cbmc_failure_when_verify_then_prints_error(
    monkeypatch, capsys, tmp_path
):
    bpmn = mutated_workflow(
        tmp_path,
        "<bpmn:documentation>paymentOwner = sellerName</bpmn:documentation>",
        "<bpmn:documentation>paymentOwner = buyerName</bpmn:documentation>",
    )
    monkeypatch.setattr(sys, "argv", ["verify", "--cbmc", STATE, CWP, bpmn])

    verify()

    assert "Unreachable Error:" in capsys.readouterr().out


def test_given_cbmc_and_cloud_when_verify_then_argument_error(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["verify", "--cbmc", "--cloud", STATE, CWP, str(WORKFLOW)]
    )

    with pytest.raises(SystemExit):
        verify()


def test_given_no_cbmc_flag_when_verify_then_still_uses_spin(monkeypatch, capsys):
    result = cli_verify(STATE, CWP, str(WORKFLOW))
    assert isinstance(unsafe_perform_io(result.unwrap()), SpinVerificationReport)

    monkeypatch.setattr(sys, "argv", ["verify", STATE, CWP, str(WORKFLOW)])
    verify()

    assert "Spin Version" in capsys.readouterr().out
