# type: ignore
import json
import os
import sys
from types import SimpleNamespace

import pytest
from requests.exceptions import HTTPError
from returns.functions import not_
from returns.io import IOSuccess
from returns.pipeline import is_successful
from returns.unsafe import unsafe_perform_io

from bpmncwpverify.cli import _trigger_lambda, cli_verify, verify, web_verify
from bpmncwpverify.core.error import (
    BpmnNoSwimLaneNameError,
    Error,
    FileReadFileError,
    HttpError,
    LambdaVerificationError,
    StateSyntaxError,
)
from bpmncwpverify.core.spin import SpinVerificationReport


def test_givin_bad_state_file_path_when_verify_then_io_error(capsys):
    # given
    test_args = [
        "verify",
        "state.txt",
        "./test/resources/simple_example/test_cwp.xml",
        "./test/resources/simple_example/test_bpmn.bpmn",
    ]
    sys.argv = test_args

    # when
    result = cli_verify(test_args[1], test_args[2], test_args[3])

    # then
    assert not_(is_successful)(result)
    error: Error = unsafe_perform_io(result.failure())
    assert isinstance(error, FileReadFileError)


def test_givin_bad_cwp_file_path_when_verify_then_io_error(capsys):
    # given
    test_args = [
        "verify",
        "./test/resources/simple_example/state.txt",
        "test_cwp.xml",
        "./test/resources/simple_example/test_bpmn.bpmn",
    ]
    sys.argv = test_args

    # when
    result = cli_verify(test_args[1], test_args[2], test_args[3])

    # then
    assert not_(is_successful)(result)
    error: Error = unsafe_perform_io(result.failure())
    assert isinstance(error, FileReadFileError)


def test_givin_bad_bpmn_file_path_when_verify_then_io_error(capsys):
    # given
    test_args = [
        "verify",
        "./test/resources/simple_example/state.txt",
        "./test/resources/simple_example/test_cwp.xml",
        "test_bpmn.bpmn",
    ]
    sys.argv = test_args

    # when
    result = cli_verify(test_args[1], test_args[2], test_args[3])

    # then
    assert not_(is_successful)(result)
    error: Error = unsafe_perform_io(result.failure())
    assert isinstance(error, FileReadFileError)


def test_givin_bad_state_file_when_verify_then_state_errror(capsys):
    # given
    test_args = [
        "verify",
        "./test/resources/simple_example/bad_state.txt",
        "./test/resources/simple_example/test_cwp.xml",
        "./test/resources/simple_example/test_bpmn.bpmn",
    ]
    sys.argv = test_args

    # when
    result = cli_verify(test_args[1], test_args[2], test_args[3])

    # then
    assert not_(is_successful)(result)
    error: Error = unsafe_perform_io(result.failure())
    assert isinstance(error, StateSyntaxError)


@pytest.mark.skipif(os.getenv("CI") == "true", reason="No SPIN on GitHub CI/CD")
def test_givin_bad_files_when_verify_then_faliure(capsys):
    # given
    test_args = [
        "verify",
        "./test/resources/simple_example/state.txt",
        "./test/resources/simple_example/test_cwp.xml",
        "./test/resources/simple_example/test_bpmn.bpmn",
    ]
    sys.argv = test_args

    # when
    result = cli_verify(test_args[1], test_args[2], test_args[3])

    # then
    assert not_(is_successful(result))
    error = unsafe_perform_io(result.failure())
    assert isinstance(error, BpmnNoSwimLaneNameError)


@pytest.mark.skipif(os.getenv("CI") == "true", reason="No SPIN on GitHub CI/CD")
def test_givin_good_files_when_verify_then_success(capsys):
    # given
    test_args = [
        "verify",
        "./test/resources/face2face/state.txt",
        "./test/resources/face2face/cwp.xml",
        "./test/resources/face2face/workflow.bpmn",
    ]
    sys.argv = test_args

    # when
    result = cli_verify(test_args[1], test_args[2], test_args[3])

    # then
    assert is_successful(result)
    outputs = result.unwrap()
    assert outputs is not None
    assert outputs != ""


@pytest.mark.skipif(os.getenv("CI") == "true", reason="No SPIN on GitHub CI/CD")
def test_given_bad_input_when_webverify_then_faliure():
    # given
    bpmn = ""
    with open("./test/resources/simple_example/test_bpmn.bpmn") as bpmn_file:
        for line in bpmn_file:
            bpmn += line

    cwp = ""
    with open("./test/resources/simple_example/test_cwp.xml") as cwp_file:
        for line in cwp_file:
            cwp += line

    state = ""
    with open("./test/resources/simple_example/state.txt") as state_file:
        for line in state_file:
            state += line

    # when
    result = web_verify(state, cwp, bpmn)

    # then
    assert not_(is_successful(result))
    error = unsafe_perform_io(result.failure())
    assert isinstance(error, BpmnNoSwimLaneNameError)


@pytest.mark.skipif(os.getenv("CI") == "true", reason="No SPIN on GitHub CI/CD")
def test_given_good_input_when_webverify_then_success():
    # given
    bpmn = ""
    with open("./test/resources/face2face/workflow.bpmn") as bpmn_file:
        for line in bpmn_file:
            bpmn += line

    cwp = ""
    with open("./test/resources/face2face/cwp.xml") as cwp_file:
        for line in cwp_file:
            cwp += line

    state = ""
    with open("./test/resources/face2face/state.txt") as state_file:
        for line in state_file:
            state += line

    # when
    result = web_verify(state, cwp, bpmn)

    # then
    assert is_successful(result)


def test_given_bad_input_when_webverify_then_failure():
    # given
    bpmn = ""
    with open("./test/resources/simple_example/test_bpmn.bpmn") as bpmn_file:
        for line in bpmn_file:
            bpmn += line

    cwp = ""
    with open("./test/resources/simple_example/test_cwp.xml") as cwp_file:
        for line in cwp_file:
            cwp += line

    state = ""
    with open("./test/resources/simple_example/bad_state.txt") as state_file:
        for line in state_file:
            state += line
    # when
    result = web_verify(state, cwp, bpmn)

    # then
    assert not_(is_successful)(result)
    error = unsafe_perform_io(result.failure())
    assert isinstance(error, StateSyntaxError)


def test_triggers_lambda_when_given_cloud_flag(mocker):
    mock_trigger_lambda = mocker.patch(
        "bpmncwpverify.cli._trigger_lambda",
        return_value=IOSuccess(
            json.load(
                open("./test/resources/simple_example/lambda_output.json"),
                object_hook=lambda obj: SpinVerificationReport(**obj),
            )
        ),
    )
    test_args = [
        "verify",
        "--cloud",
        "./test/resources/simple_example/state.txt",
        "./test/resources/simple_example/test_cwp.xml",
        "./test/resources/simple_example/test_bpmn.bpmn",
    ]
    sys.argv = test_args
    verify()

    mock_trigger_lambda.assert_called_once()


def test_assert_success_when_lambda_returns_success(mocker):
    mock_response = SimpleNamespace()
    mock_response.raise_for_status = lambda: None
    mock_response.json = lambda **kwargs: json.load(
        open("./test/resources/simple_example/lambda_output.json"),
        object_hook=lambda obj: SpinVerificationReport(**obj),
    )

    mocker.patch("requests.post", return_value=mock_response)

    bpmn = ""
    with open("./test/resources/simple_example/test_bpmn.bpmn") as bpmn_file:
        for line in bpmn_file:
            bpmn += line

    cwp = ""
    with open("./test/resources/simple_example/test_cwp.xml") as cwp_file:
        for line in cwp_file:
            cwp += line

    state = ""
    with open("./test/resources/simple_example/state.txt") as state_file:
        for line in state_file:
            state += line

    result = _trigger_lambda(state, cwp, bpmn)

    assert is_successful(result)


def test_assert_failure_when_lambda_verification_fails(mocker):
    mock_response = SimpleNamespace()
    mock_response.status_code = 400
    mock_response.text = "Error text"

    def throw_http_error():
        raise HTTPError(response=mock_response)

    mock_response.raise_for_status = throw_http_error

    mocker.patch("requests.post", return_value=mock_response)

    bpmn = ""
    with open("./test/resources/simple_example/test_bpmn.bpmn") as bpmn_file:
        for line in bpmn_file:
            bpmn += line

    cwp = ""
    with open("./test/resources/simple_example/test_cwp.xml") as cwp_file:
        for line in cwp_file:
            cwp += line

    state = ""
    with open("./test/resources/simple_example/state.txt") as state_file:
        for line in state_file:
            state += line

    result = _trigger_lambda(state, cwp, bpmn)

    assert not_(is_successful)(result)
    error = unsafe_perform_io(result.failure())
    assert isinstance(error, LambdaVerificationError)


def test_assert_failure_when_lambda_returns_internal_server_error(mocker):
    mock_response = SimpleNamespace()
    mock_response.status_code = 500
    mock_response.reason = "Internal Server Error"
    mock_response.text = "Error text"

    def throw_http_error():
        raise HTTPError(response=mock_response)

    mock_response.raise_for_status = throw_http_error

    mocker.patch("requests.post", return_value=mock_response)

    bpmn = ""
    with open("./test/resources/simple_example/test_bpmn.bpmn") as bpmn_file:
        for line in bpmn_file:
            bpmn += line

    cwp = ""
    with open("./test/resources/simple_example/test_cwp.xml") as cwp_file:
        for line in cwp_file:
            cwp += line

    state = ""
    with open("./test/resources/simple_example/state.txt") as state_file:
        for line in state_file:
            state += line

    result = _trigger_lambda(state, cwp, bpmn)

    assert not_(is_successful)(result)
    error = unsafe_perform_io(result.failure())
    assert isinstance(error, HttpError)
