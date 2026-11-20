# type: ignore
import sys

import defusedxml.ElementTree as ET
import pytest
from returns.pipeline import is_successful
from returns.unsafe import unsafe_perform_io

from bpmncwpverify import cli
from bpmncwpverify.core import cbmc
from bpmncwpverify.core.accessmethods import bpmnmethods
from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.cbmc import (
    check_assertions,
    check_reachability,
    verify_with_cbmc,
)
from bpmncwpverify.core.error import (
    CbmcAssertionError,
    CbmcRunError,
    CbmcUnreachableError,
)
from bpmncwpverify.core.state import State

RES = "./test/resources/"
SIMPLE = RES + "simple_example/"
FACE2FACE = RES + "face2face/"


def _read(path):
    with open(path) as f:
        return f.read()


def _verify(directory, cwp_file, bpmn_file, tmp_path, cwp_edit=None, bpmn_edit=None):
    state = State.from_str(_read(directory + "state.txt")).unwrap()
    cwp_xml = _read(directory + cwp_file)
    bpmn_xml = _read(directory + bpmn_file)
    if cwp_edit:
        cwp_xml = cwp_xml.replace(*cwp_edit)
    if bpmn_edit:
        bpmn_xml = bpmn_xml.replace(*bpmn_edit)
    cwp = CwpXmlParser.from_xml(ET.fromstring(cwp_xml), state).unwrap()
    bpmn = bpmnmethods.from_xml(ET.fromstring(bpmn_xml), state).unwrap()
    return verify_with_cbmc(state, cwp, bpmn, str(tmp_path / "verification.c"))


@pytest.mark.parametrize("bpmn_file", ["workflow.bpmn", "face2face_open.bpmn"])
def test_face2face_verifies_with_cbmc(bpmn_file, tmp_path):
    result = _verify(FACE2FACE, "cwp.xml", bpmn_file, tmp_path)

    assert is_successful(result)
    report = unsafe_perform_io(result.unwrap())
    assert "VERIFICATION SUCCESSFUL" in report.cbmc_report
    assert "SATISFIED" in report.cbmc_report
    assert (tmp_path / "verification.c").read_text() == report.c_code


def test_failed_assertion_is_reported(tmp_path):
    # With End needing x > 7, x = 6 is in no CWP state at all
    result = _verify(
        SIMPLE,
        "test_cwp.xml",
        "simple_open.bpmn",
        tmp_path,
        cwp_edit=("x &amp;gt; 5", "x &amp;gt; 7"),
        bpmn_edit=("x = x + 1", "x = x + 3"),
    )

    error = unsafe_perform_io(result.failure())
    assert isinstance(error, CbmcAssertionError)
    assert any("sum_of_active_states" in f["description"] for f in error.failures)


def test_unreachable_state_is_reported(tmp_path):
    # x never changes, so the CWP never gets to End and the end event is never reached
    result = _verify(
        SIMPLE,
        "test_cwp.xml",
        "simple_open.bpmn",
        tmp_path,
        bpmn_edit=("x = x + 1", "x = x"),
    )

    error = unsafe_perform_io(result.failure())
    assert isinstance(error, CbmcUnreachableError)
    assert "cwp state End" in error.unreachable
    assert "cwp state Increment_x" not in error.unreachable
    assert any(name.startswith("end event") for name in error.unreachable)


def test_cbmc_that_cannot_run_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))

    result = _verify(SIMPLE, "test_cwp.xml", "simple_open.bpmn", tmp_path)

    assert isinstance(unsafe_perform_io(result.failure()), CbmcRunError)


def test_unwritable_c_file_is_reported(tmp_path):
    state = State.from_str(_read(SIMPLE + "state.txt")).unwrap()
    cwp = CwpXmlParser.from_xml(
        ET.fromstring(_read(SIMPLE + "test_cwp.xml")), state
    ).unwrap()
    bpmn = bpmnmethods.from_xml(
        ET.fromstring(_read(SIMPLE + "simple_open.bpmn")), state
    ).unwrap()

    result = verify_with_cbmc(state, cwp, bpmn, str(tmp_path / "missing" / "v.c"))

    assert not is_successful(result)


def test_check_assertions_reads_failures():
    report = (
        "[main.assertion.1] line 7 token placed: FAILURE\n[a.b.2] line 8 ok: SUCCESS\n"
    )

    error = check_assertions(report).failure()

    assert error.failures == [
        {"id": "main.assertion.1", "line": "7", "description": "token placed"}
    ]
    assert is_successful(check_assertions("[a.b.2] line 8 ok: SUCCESS\n"))


def test_check_reachability_needs_all_covers_of_a_name_to_fail():
    c_code = "\n".join(
        [
            "cover(a); /* cwp state A */",
            "cover(a); /* cwp state A */",
            "cover(b); /* cwp state B */",
        ]
    )
    report = (
        "[main.coverage.1] file v.c line 1 function main condition 'a': FAILED\n"
        "[main.coverage.2] file v.c line 2 function main condition 'a': SATISFIED\n"
        "[main.coverage.3] file v.c line 3 function main condition 'b': FAILED\n"
    )

    error = check_reachability(report, c_code).failure()

    assert error.unreachable == ["cwp state B"]


def test_cli_option_cbmc_runs_cbmc(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cbmc, "OUTPUT_FILE", str(tmp_path / "v.c"))
    monkeypatch.setattr(
        sys,
        "argv",
        ["verify", FACE2FACE + "state.txt", FACE2FACE + "cwp.xml"]
        + [FACE2FACE + "workflow.bpmn", "--cbmc"],
    )

    cli.verify()

    assert "VERIFICATION SUCCESSFUL" in capsys.readouterr().out


def test_cli_option_cbmc_prints_errors(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["verify", "missing.txt", FACE2FACE + "cwp.xml"]
        + [FACE2FACE + "workflow.bpmn", "--cbmc"],
    )

    cli.verify()

    assert "missing.txt" in capsys.readouterr().out


def test_cli_without_cbmc_still_runs_spin(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["verify", FACE2FACE + "state.txt", FACE2FACE + "cwp.xml"]
        + [FACE2FACE + "workflow.bpmn"],
    )

    cli.verify()

    assert "pan:" in capsys.readouterr().out
