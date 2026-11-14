# type: ignore
import sys
import time

import pytest
from returns.pipeline import is_successful
from returns.unsafe import unsafe_perform_io

from bpmncwpverify.builder.cbmc_builder import REACHABILITY_MACRO, CbmcBuilder
from bpmncwpverify.cli import (
    cli_verify,
    cli_verify_with_cbmc,
    verify,
)
from bpmncwpverify.core.cbmc import (
    CbmcVerificationReport,
    _cbmc_args,
    _goal_name,
    _run_cbmc_on_file,
    verify_with_cbmc,
)
from bpmncwpverify.core.error import (
    CbmcAssertionError,
    CbmcRunError,
    CbmcUnreachableError,
    FileReadFileError,
    get_error_message,
)

SIMPLE = "test/resources/simple_example/"
FACE2FACE = "test/resources/face2face/"
PHWARE = "test/resources/phware/"
INCREMENT = "<![CDATA[x = x + 1]]>"


def _failure(result):
    assert not is_successful(result)
    return unsafe_perform_io(result.failure())


def _report(result):
    assert is_successful(result), get_error_message(_failure(result))
    return unsafe_perform_io(result.unwrap())


def _simple_with_behavior(tmp_path, behavior):
    with open(SIMPLE + "simple_open.bpmn") as f:
        bpmn = f.read().replace(INCREMENT, f"<![CDATA[{behavior}]]>")
    assert behavior in bpmn
    path = tmp_path / "workflow.bpmn"
    path.write_text(bpmn)
    return str(path)


@pytest.mark.parametrize("bpmn", ["workflow.bpmn", "face2face_open.bpmn"])
def test_given_face2face_when_cbmc_then_verified_in_under_a_minute(bpmn):
    start = time.monotonic()

    result = cli_verify_with_cbmc(
        FACE2FACE + "state.txt", FACE2FACE + "cwp.xml", FACE2FACE + bpmn
    )

    report = _report(result)
    assert isinstance(report, CbmcVerificationReport)
    assert time.monotonic() - start < 60
    assert "no assertion fails" in report.summary()


def test_given_failing_behavior_assert_when_cbmc_then_assertion_error(tmp_path):
    bpmn = _simple_with_behavior(tmp_path, "x = x + 1; assert(x == 0)")

    result = cli_verify_with_cbmc(SIMPLE + "state.txt", SIMPLE + "test_cwp.xml", bpmn)

    error = _failure(result)
    assert isinstance(error, CbmcAssertionError)
    assert any("Assert: behavior of" in f["description"] for f in error.failures)
    assert "assertion(s) failed" in get_error_message(error)


def test_given_unreachable_end_when_cbmc_then_unreachable_error(tmp_path):
    # x never grows, so the gateway never lets the workflow reach its end
    bpmn = _simple_with_behavior(tmp_path, "x = x + 0")

    result = cli_verify_with_cbmc(SIMPLE + "state.txt", SIMPLE + "test_cwp.xml", bpmn)

    error = _failure(result)
    assert isinstance(error, CbmcUnreachableError)
    descriptions = [goal["description"] for goal in error.unreached]
    assert any(d.startswith("end event") for d in descriptions)
    assert "CWP state End" in descriptions
    assert "can never be reached" in get_error_message(error)


def test_given_reachable_workflow_when_cbmc_then_start_state_is_not_a_goal(tmp_path):
    from bpmncwpverify.core.accessmethods import bpmnmethods
    from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
    from bpmncwpverify.core.state import State
    from bpmncwpverify.util.file import element_tree_from_string

    with open(SIMPLE + "state.txt") as f:
        state = State.from_str(f.read()).unwrap()
    with open(SIMPLE + "test_cwp.xml") as f:
        cwp = CwpXmlParser.from_xml(
            unsafe_perform_io(element_tree_from_string(f.read()).unwrap()), state
        ).unwrap()
    with open(SIMPLE + "simple_open.bpmn") as f:
        bpmn = bpmnmethods.from_xml(
            unsafe_perform_io(element_tree_from_string(f.read()).unwrap()), state
        ).unwrap()

    c_program = CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn).build()

    goals = [
        line for line in c_program.unwrap().split("\n") if "__CPROVER_cover" in line
    ]
    assert any("CWP state End" in goal for goal in goals)
    assert not any("CWP state Start" in goal for goal in goals)


def test_given_no_cbmc_when_verify_then_run_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))

    result = _run_cbmc_on_file("int main(void) { return 0; }", str(tmp_path / "a.c"), 2)

    assert isinstance(_failure(result), CbmcRunError)


def test_given_bad_c_when_cbmc_then_run_error(tmp_path):
    result = _run_cbmc_on_file("int main(void) { x = ; }", str(tmp_path / "a.c"), 2)

    error = _failure(result)
    assert isinstance(error, CbmcRunError)
    assert "syntax error" in get_error_message(error)


def test_given_unwritable_path_when_cbmc_then_error(tmp_path):
    result = _run_cbmc_on_file(
        "int main(void) { return 0; }", str(tmp_path / "x" / "a.c"), 2
    )

    assert not is_successful(result)


def test_given_c_that_cannot_be_built_when_cbmc_then_build_error():
    from bpmncwpverify.core.accessmethods import bpmnmethods
    from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
    from bpmncwpverify.core.state import State
    from bpmncwpverify.util.file import element_tree_from_string

    with open(PHWARE + "state.txt") as f:
        state = State.from_str(f.read()).unwrap()
    with open(PHWARE + "cwp.xml") as f:
        cwp = CwpXmlParser.from_xml(
            unsafe_perform_io(element_tree_from_string(f.read()).unwrap()), state
        ).unwrap()
    with open(PHWARE + "workflow_good.bpmn") as f:
        bpmn = bpmnmethods.from_xml(
            unsafe_perform_io(element_tree_from_string(f.read()).unwrap()), state
        ).unwrap()

    result = verify_with_cbmc(state, cwp, bpmn)

    assert not is_successful(result)


def test_given_missing_state_file_when_cbmc_then_read_error():
    result = cli_verify_with_cbmc(
        "nope.txt", SIMPLE + "test_cwp.xml", SIMPLE + "simple_open.bpmn"
    )

    assert isinstance(_failure(result), FileReadFileError)


def test_cbmc_args_differ_only_in_the_reachability_run():
    assertions = _cbmc_args("a.c", 9, False)
    reachability = _cbmc_args("a.c", 9, True)

    assert ["--unwind", "9"] == assertions[2:4]
    assert f"-D{REACHABILITY_MACRO}" in reachability
    assert "--cover" in reachability
    assert f"-D{REACHABILITY_MACRO}" not in assertions
    assert "--cover" not in assertions


def test_goal_name_falls_back_to_description():
    lines = ["x; /* end event e */", "y;"]

    assert _goal_name(lines, "1", "d") == "end event e"
    assert _goal_name(lines, "2", "d") == "d"
    assert _goal_name(lines, "?", "d") == "d"
    assert _goal_name(lines, "9", "d") == "d"


def test_given_cbmc_option_when_verify_then_prints_cbmc_answer(capsys):
    sys.argv = [
        "verify",
        FACE2FACE + "state.txt",
        FACE2FACE + "cwp.xml",
        FACE2FACE + "workflow.bpmn",
        "--cbmc",
    ]

    verify()

    assert "CBMC verified" in capsys.readouterr().out


def test_given_cbmc_option_and_bad_input_when_verify_then_prints_error(capsys):
    sys.argv = [
        "verify",
        "nope.txt",
        SIMPLE + "test_cwp.xml",
        SIMPLE + "simple_open.bpmn",
        "--cbmc",
    ]

    verify()

    assert capsys.readouterr().out.strip()


def test_given_no_cbmc_option_when_verify_then_spin_runs(capsys):
    sys.argv = [
        "verify",
        SIMPLE + "state.txt",
        SIMPLE + "test_cwp.xml",
        SIMPLE + "simple_open.bpmn",
    ]

    verify()

    out = capsys.readouterr().out
    assert "errors: 0" in out
    assert "CBMC" not in out


def test_given_simple_when_cli_verify_then_spin_still_succeeds():
    result = cli_verify(
        SIMPLE + "state.txt", SIMPLE + "test_cwp.xml", SIMPLE + "simple_open.bpmn"
    )

    assert is_successful(result)
