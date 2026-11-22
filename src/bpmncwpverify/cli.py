import argparse
from xml.etree.ElementTree import Element

import requests
from returns.functions import not_
from returns.io import IOFailure, IOResult, IOSuccess
from returns.pipeline import is_successful
from returns.unsafe import unsafe_perform_io

from bpmncwpverify.core.accessmethods import bpmnmethods
from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.error import (
    Error,
    HttpError,
    JsonDecodeError,
    LambdaVerificationError,
    RequestError,
    get_error_message,
)
from bpmncwpverify.core.spin import (
    SpinVerificationReport,
    verify_with_spin,
)
from bpmncwpverify.core.state import State
from bpmncwpverify.util.file import (
    element_tree_from_string,
    read_file_as_string,
)

LAMBDA_URL = "https://iatjgvm4gt75bw4qwbz7l3bihq0irdns.lambda-url.us-east-1.on.aws/"


def _get_argument_parser() -> "argparse.ArgumentParser":
    argument_parser = argparse.ArgumentParser(
        description="Verify the BPMN as a safe substitution for the CWP given the state"
    )

    argument_parser.add_argument(
        "state_file",
        help="State definition text file",
    )
    argument_parser.add_argument(
        "cwp_file",
        help="CWP state machine file in XML",
    )
    argument_parser.add_argument(
        "bpmn_file",
        help="BPMN workflow file in XML",
    )
    argument_parser.add_argument(
        "--cloud",
        action="store_true",
        help="Run verification remotely on AWS Lambda",
    )
    return argument_parser


def _verify_with_spin(
    state_str: str,
    cwp_xml: Element,
    bpmn_xml: Element,
) -> IOResult[SpinVerificationReport, Error]:
    result: IOResult[SpinVerificationReport, Error] = IOResult.from_result(
        State.from_str(state_str)
    ).bind(  # pyright: ignore[reportUnknownMemberType]
        lambda state: IOResult.from_result(CwpXmlParser.from_xml(cwp_xml, state)).bind(  # pyright: ignore[reportUnknownMemberType]
            lambda cwp: IOResult.from_result(
                bpmnmethods.from_xml(bpmn_xml, state)
            ).bind(  # pyright: ignore[reportUnknownMemberType]
                lambda bpmn: verify_with_spin(state, cwp, bpmn)
            )
        )
    )

    return result


def _verify_with_spin_from_files(
    state_file: str, cwp_file: str, bpmn_file: str
) -> IOResult[SpinVerificationReport, Error]:
    result: IOResult[SpinVerificationReport, Error] = read_file_as_string(
        state_file
    ).bind(  # pyright: ignore[reportUnknownMemberType]
        lambda state: read_file_as_string(cwp_file).bind(  # pyright: ignore[reportUnknownMemberType]
            lambda cwp: read_file_as_string(bpmn_file).bind(  # pyright: ignore[reportUnknownMemberType]
                lambda bpmn: web_verify(state, cwp, bpmn)
            )
        )
    )
    return result


def _trigger_lambda(
    state: str, cwp: str, bpmn: str
) -> IOResult[SpinVerificationReport, Error]:
    try:
        response: requests.Response = requests.post(
            url=LAMBDA_URL,
            json={
                "state": state,
                "cwp": cwp,
                "bpmn": bpmn,
            },
        )
        response.raise_for_status()
        report = response.json(object_hook=lambda obj: SpinVerificationReport(**obj))
        return IOSuccess(report)
    except requests.exceptions.HTTPError as err:
        if err.response.status_code == 400:
            return IOFailure(LambdaVerificationError(err.response.text))
        else:
            return IOFailure(
                HttpError(
                    err.response.status_code, err.response.reason, err.response.text
                )
            )
    except requests.exceptions.JSONDecodeError as err:
        return IOFailure(JsonDecodeError(err.response.text if err.response else ""))
    except requests.exceptions.RequestException as err:
        return IOFailure(RequestError(err))


def _verify_on_lambda_from_files(
    state_file: str, cwp_file: str, bpmn_file: str
) -> IOResult[SpinVerificationReport, Error]:
    result: IOResult[SpinVerificationReport, Error] = read_file_as_string(
        state_file
    ).bind(  # pyright: ignore[reportUnknownMemberType]
        lambda state: read_file_as_string(cwp_file).bind(  # pyright: ignore[reportUnknownMemberType]
            lambda cwp: read_file_as_string(bpmn_file).bind(  # pyright: ignore[reportUnknownMemberType]
                lambda bpmn: _trigger_lambda(state, cwp, bpmn)
            )
        )
    )
    return result


def cli_verify(
    state_file: str, cwp_file: str, bpmn_file: str
) -> IOResult[SpinVerificationReport, Error]:
    result: IOResult[SpinVerificationReport, Error] = _verify_with_spin_from_files(
        state_file, cwp_file, bpmn_file
    )
    return result


def verify() -> None:
    argument_parser = _get_argument_parser()
    args = argument_parser.parse_args()

    if args.cloud:
        result = _verify_on_lambda_from_files(
            args.state_file, args.cwp_file, args.bpmn_file
        )
    else:
        result = cli_verify(args.state_file, args.cwp_file, args.bpmn_file)

    if not_(is_successful)(result):
        error: Error = unsafe_perform_io(result.failure())
        print(get_error_message(error))
        return

    spin_verification_report: SpinVerificationReport = unsafe_perform_io(
        result.unwrap()
    )
    print(spin_verification_report.spin_report)


def web_verify(
    state: str, cwp_str: str, bpmn_str: str
) -> IOResult[SpinVerificationReport, Error]:
    result: IOResult[SpinVerificationReport, Error] = element_tree_from_string(
        cwp_str
    ).bind(  # pyright: ignore[reportUnknownMemberType]
        lambda cwp: element_tree_from_string(bpmn_str).bind(  # pyright: ignore[reportUnknownMemberType]
            lambda bpmn: _verify_with_spin(state, cwp, bpmn)
        )
    )
    return result
