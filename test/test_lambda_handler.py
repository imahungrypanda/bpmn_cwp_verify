# type: ignore

import json

from returns.io import IOSuccess

from bpmncwpverify.core.spin import SpinVerificationReport
from lambda_function import lambda_handler


def test_lambda_handler_correctly_handles_good_input(mocker):
    mocker.patch(
        "lambda_function.web_verify",
        return_value=IOSuccess(
            json.load(
                open("./test/resources/simple_example/lambda_output.json"),
                object_hook=lambda obj: SpinVerificationReport(**obj),
            )
        ),
    )

    input = {
        "body": json.dumps(
            {
                "bpmn": open("test/resources/simple_example/test_bpmn.bpmn").read(),
                "cwp": open("test/resources/simple_example/test_cwp.xml").read(),
                "state": open("test/resources/simple_example/state.txt").read(),
            }
        )
    }

    expected = open("test/resources/simple_example/lambda_output.json").read().strip()

    response = lambda_handler(input, {})

    assert 200 == response["statusCode"]
    assert expected == response["body"]


def test_lambda_handler_returns_bad_request_on_bad_input():
    input = {
        "body": json.dumps(
            {
                "bpmn": open("test/resources/simple_example/test_bpmn.bpmn").read(),
                "bad_input": True,
            }
        )
    }

    response = lambda_handler(input, {})

    assert 400 == response["statusCode"]
