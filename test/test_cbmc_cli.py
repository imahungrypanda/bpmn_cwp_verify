import shutil
import sys

import pytest
from returns.pipeline import is_successful
from returns.unsafe import unsafe_perform_io

from bpmncwpverify.cli import verify
from bpmncwpverify.core.accessmethods import bpmnmethods
from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.cbmc import (
    CbmcVerificationReport,
    verify_with_cbmc,
)
from bpmncwpverify.core.error import (
    CbmcAssertionError,
    CbmcRunError,
    CbmcUnreachableError,
)
from bpmncwpverify.core.state import State
from bpmncwpverify.util.file import element_tree_from_string

pytestmark = pytest.mark.skipif(
    shutil.which("cbmc") is None, reason="CBMC is not installed"
)

RESOURCES = "./test/resources"
FACE2FACE = f"{RESOURCES}/face2face"
SIMPLE = f"{RESOURCES}/simple_example"


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


def _verify(state: str, cwp: str, bpmn: str):
    state_obj = State.from_str(state).unwrap()
    cwp_xml = unsafe_perform_io(element_tree_from_string(cwp).unwrap())
    bpmn_xml = unsafe_perform_io(element_tree_from_string(bpmn).unwrap())
    cwp_obj = CwpXmlParser.from_xml(cwp_xml, state_obj).unwrap()
    bpmn_obj = bpmnmethods.from_xml(bpmn_xml, state_obj).unwrap()
    return verify_with_cbmc(state_obj, cwp_obj, bpmn_obj)


def _run_cli(capsys, *args: str) -> str:
    sys.argv = ["verify", *args]
    verify()
    return capsys.readouterr().out


@pytest.mark.parametrize("bpmn", ["workflow.bpmn", "face2face_open.bpmn"])
def test_given_face2face_when_verify_with_cbmc_then_success(bpmn):
    result = _verify(
        _read(f"{FACE2FACE}/state.txt"),
        _read(f"{FACE2FACE}/cwp.xml"),
        _read(f"{FACE2FACE}/{bpmn}"),
    )

    assert is_successful(result)
    report = unsafe_perform_io(result.unwrap())
    assert isinstance(report, CbmcVerificationReport)
    assert "VERIFICATION SUCCESSFUL" in report.cbmc_report
    assert "7 of 7 covered" in report.cbmc_report


@pytest.mark.parametrize("bpmn", ["workflow.bpmn", "face2face_open.bpmn"])
def test_given_face2face_when_cli_cbmc_then_verified(capsys, bpmn):
    out = _run_cli(
        capsys,
        f"{FACE2FACE}/state.txt",
        f"{FACE2FACE}/cwp.xml",
        f"{FACE2FACE}/{bpmn}",
        "--cbmc",
    )

    assert "VERIFICATION SUCCESSFUL" in out
    assert "CBMC ERROR" not in out


def test_given_invalid_cwp_move_when_verify_with_cbmc_then_assertion_error():
    # The CWP only leaves Increment_x once x > 7, but x goes from 5 to 6
    cwp = _read(f"{SIMPLE}/test_cwp.xml").replace("x &amp;gt; 5", "x &amp;gt; 7")

    state = _read(f"{SIMPLE}/state.txt").replace("= 0", "= 5")

    result = _verify(state, cwp, _read(f"{SIMPLE}/simple_open.bpmn"))

    assert not is_successful(result)
    error = unsafe_perform_io(result.failure())
    assert isinstance(error, CbmcAssertionError)
    assert any("CWP" in f["description"] for f in error.failures)


def test_given_state_never_reached_when_verify_with_cbmc_then_unreachable_error():
    # The loop needs more passes than the unwinding bound allows, so the end
    # event and the CWP's last state are out of reach
    result = _verify(
        _read(f"{SIMPLE}/state.txt"),
        _read(f"{SIMPLE}/test_cwp.xml"),
        _read(f"{SIMPLE}/simple_open.bpmn"),
    )

    assert not is_successful(result)
    error = unsafe_perform_io(result.failure())
    assert isinstance(error, CbmcUnreachableError)
    assert "cwp state End" in error.unreached
    assert "cwp state Start" not in error.unreached


def test_given_no_cbmc_when_verify_with_cbmc_then_run_error(monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")

    result = _verify(
        _read(f"{FACE2FACE}/state.txt"),
        _read(f"{FACE2FACE}/cwp.xml"),
        _read(f"{FACE2FACE}/workflow.bpmn"),
    )

    assert not is_successful(result)
    assert isinstance(unsafe_perform_io(result.failure()), CbmcRunError)


def test_given_unreachable_state_when_cli_cbmc_then_message_printed(capsys):
    out = _run_cli(
        capsys,
        f"{SIMPLE}/state.txt",
        f"{SIMPLE}/test_cwp.xml",
        f"{SIMPLE}/simple_open.bpmn",
        "--cbmc",
    )

    assert "the workflow never reaches" in out
    assert "cwp state End" in out


def test_given_cbmc_and_cloud_when_cli_then_exit():
    sys.argv = ["verify", "a", "b", "c", "--cbmc", "--cloud"]
    with pytest.raises(SystemExit):
        verify()


@pytest.mark.skipif(shutil.which("spin") is None, reason="SPIN is not installed")
def test_given_no_cbmc_option_when_cli_then_spin_runs(capsys):
    out = _run_cli(
        capsys,
        f"{FACE2FACE}/state.txt",
        f"{FACE2FACE}/cwp.xml",
        f"{FACE2FACE}/workflow.bpmn",
    )

    assert "State-vector" in out
    assert "CBMC" not in out
