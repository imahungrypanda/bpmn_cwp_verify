import os
import re
import subprocess

from returns.io import IOResult, impure_safe
from returns.result import Failure, Result, Success

from bpmncwpverify.builder.cbmc_builder import (
    CWP_REACHED_PREFIX,
    END_REACHED_PREFIX,
    CbmcBuilder,
)
from bpmncwpverify.core.bpmn import Bpmn
from bpmncwpverify.core.cwp import Cwp
from bpmncwpverify.core.error import (
    CbmcAssertionError,
    CbmcRunError,
    CbmcUnreachableError,
    Error,
)
from bpmncwpverify.core.state import State
from bpmncwpverify.util.file import write_file_contents

OUTPUT_FILE = "/tmp/verification.c"

# CBMC exits with 0 when everything holds (or every cover was checked) and with
# 10 when a property fails. Anything else means that it could not do its job.
_EXIT_OK = 0
_EXIT_PROPERTY_FAILED = 10

_ASSERTION_ARGS = ["--unwinding-assertions"]
_REACHABILITY_ARGS = ["-DREACHABILITY", "--cover", "cover"]

_FAILED_PROPERTY = re.compile(r"^\[(?P<id>[^\]]+)\] (?P<info>.*): FAILURE$", re.M)
_UNCOVERED = re.compile(r"condition '(?P<flag>\w+)(?: != FALSE)?': FAILED$", re.M)


class CbmcVerificationReport:
    __slots__ = ["file_path", "c_code", "cbmc_cli_args", "cbmc_report"]

    def __init__(
        self,
        file_path: str,
        c_code: str,
        cbmc_cli_args: list[list[str]],
        cbmc_report: str,
    ) -> None:
        self.file_path = file_path
        self.c_code = c_code
        self.cbmc_cli_args = cbmc_cli_args
        self.cbmc_report = cbmc_report


def _run_cbmc(file_path: str, cli_args: list[str]) -> IOResult[str, Error]:
    def cbmc() -> str:
        proc = subprocess.run(
            ["cbmc", os.path.basename(file_path)] + cli_args,
            capture_output=True,
            text=True,
            cwd=os.path.dirname(file_path) or ".",
        )
        if proc.returncode not in (_EXIT_OK, _EXIT_PROPERTY_FAILED):
            message = (proc.stderr or proc.stdout).strip()
            raise RuntimeError(f"exit code {proc.returncode}: {message}")
        return proc.stdout

    return impure_safe(cbmc)().alt(lambda exc: CbmcRunError(str(exc)))


def _check_assertions(report: str) -> Result[None, Error]:
    failures = [f"{m['info']} ({m['id']})" for m in _FAILED_PROPERTY.finditer(report)]
    return Failure(CbmcAssertionError(failures)) if failures else Success(None)


def _describe_target(flag: str) -> str:
    if flag.startswith(END_REACHED_PREFIX):
        return f"end event {flag[len(END_REACHED_PREFIX) :]}"
    if flag.startswith(CWP_REACHED_PREFIX):
        return f"CWP state {flag[len(CWP_REACHED_PREFIX) :]}"
    return flag


def _check_reachability(report: str) -> Result[None, Error]:
    unreached = [_describe_target(m["flag"]) for m in _UNCOVERED.finditer(report)]
    return Failure(CbmcUnreachableError(unreached)) if unreached else Success(None)


def _verify_c(
    c_code: str, file_path: str, bound: int
) -> IOResult[CbmcVerificationReport, Error]:
    unwind = ["--unwind", str(bound + 1)]
    assertion_args = unwind + _ASSERTION_ARGS
    reachability_args = unwind + _REACHABILITY_ARGS

    def reports(assertion_report: str) -> IOResult[CbmcVerificationReport, Error]:
        return (
            IOResult.from_result(_check_assertions(assertion_report))
            .bind(lambda _: _run_cbmc(file_path, reachability_args))  # pyright: ignore[reportUnknownMemberType, reportUnknownLambdaType]
            .bind(  # pyright: ignore[reportUnknownMemberType]
                lambda reach_report: IOResult.from_result(
                    _check_reachability(reach_report)
                ).map(
                    lambda _: CbmcVerificationReport(
                        file_path,
                        c_code,
                        [assertion_args, reachability_args],
                        f"{assertion_report}\n{reach_report}",
                    )
                )
            )
        )

    return write_file_contents(c_code, file_path).bind(  # pyright: ignore[reportUnknownMemberType]
        lambda _: _run_cbmc(file_path, assertion_args).bind(reports)  # pyright: ignore[reportUnknownMemberType, reportUnknownLambdaType]
    )


def verify_with_cbmc(
    state: State,
    cwp: Cwp,
    bpmn: Bpmn,
) -> IOResult[CbmcVerificationReport, Error]:
    builder = CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn)
    return IOResult.from_result(builder.build()).bind(  # pyright: ignore[reportUnknownMemberType]
        lambda c_code: IOResult.from_result(builder.unwinding_bound()).bind(  # pyright: ignore[reportUnknownMemberType]
            lambda bound: _verify_c(c_code, OUTPUT_FILE, bound)
        )
    )
