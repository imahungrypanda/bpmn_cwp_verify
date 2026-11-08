import json
from typing import Any

from returns.io import IOResult
from returns.pipeline import is_successful
from returns.unsafe import unsafe_perform_io

from bpmncwpverify.cli import web_verify
from bpmncwpverify.core.error import Error
from bpmncwpverify.core.spin import SpinVerificationReport


def lambda_handler(event: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    try:
        body = event.get("body", "{}")
        data = json.loads(body)
        state = data.get("state", None)
        cwp = data.get("cwp", None)
        bpmn = data.get("bpmn", None)
        if not (state and cwp and bpmn):
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing file(s)"}),
            }

        result: IOResult[SpinVerificationReport, Error] = web_verify(state, cwp, bpmn)
        if is_successful(result):
            outputs: SpinVerificationReport = unsafe_perform_io(result.unwrap())
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "file_path": outputs.file_path,
                        "promela": outputs.promela,
                        "spin_cli_args": outputs.spin_cli_args,
                        "spin_report": outputs.spin_report,
                    }
                ),
            }
        else:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Verification failed"}),
            }
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
