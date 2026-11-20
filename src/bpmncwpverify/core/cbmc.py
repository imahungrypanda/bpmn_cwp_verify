import os
import re
import subprocess

from returns.io import IOResult, impure_safe
from returns.result import Failure, Result, Success

from bpmncwpverify.builder.cbmc_builder import CbmcBuilder
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

# CBMC exits with 0 when it verified, and 10 when a property failed.
_EXIT_SUCCESS = 0
_EXIT_PROPERTY_FAILED = 10

_PROPERTY_REGEX = re.compile(
    r"^\[(?P<id>[^\]]+)\] line (?P<line>\d+) (?P<description>.*): (?P<status>SUCCESS|FAILURE)$"
)
_COVER_REGEX = re.compile(
    r"^\[(?P<id>[^\]]+)\] file (?P<file>\S+) line (?P<line>\d+) .*: (?P<status>SATISFIED|FAILED)$"
)


class CbmcVerificationReport:
    __slots__ = ["file_path", "c_code", "cbmc_cli_args", "cbmc_report"]

    def __init__(
        self, file_path: str, c_code: str, cbmc_cli_args: list[str], cbmc_report: str
    ) -> None:
        self.file_path = file_path
        self.c_code = c_code
        self.cbmc_cli_args = cbmc_cli_args
        self.cbmc_report = cbmc_report


def _run_cbmc(file_path: str, cli_args: list[str]) -> IOResult[str, Error]:
    def cbmc() -> str:
        completed = subprocess.run(
            ["cbmc", os.path.basename(file_path)] + cli_args,
            capture_output=True,
            text=True,
            cwd=os.path.dirname(file_path),
        )
        if completed.returncode not in (_EXIT_SUCCESS, _EXIT_PROPERTY_FAILED):
            raise RuntimeError(
                f"cbmc exited with {completed.returncode}: {completed.stdout}{completed.stderr}".strip()
            )
        return completed.stdout

    return impure_safe(cbmc)().alt(lambda exc: CbmcRunError(str(exc)))


def _check_assertions(output: str) -> Result[None, Error]:
    failures: list[dict[str, str]] = []
    for line in output.splitlines():
        match = _PROPERTY_REGEX.match(line.strip())
        if match and match.group("status") == "FAILURE":
            failures.append(
                {"line": match.group("line"), "description": match.group("description")}
            )
    return Failure(CbmcAssertionError(failures)) if failures else Success(None)


def _check_coverage(output: str, c_code: str) -> Result[None, Error]:
    c_lines = c_code.splitlines()
    unreached: list[str] = []
    for line in output.splitlines():
        match = _COVER_REGEX.match(line.strip())
        if match and match.group("status") == "FAILED":
            # The cover is on the line after a comment that names what it covers
            comment = c_lines[int(match.group("line")) - 2].strip()
            unreached.append(comment.removeprefix("/*").removesuffix("*/").strip())
    return Failure(CbmcUnreachableError(unreached)) if unreached else Success(None)


def _summary(assertion_output: str, cover_output: str) -> str:
    """CBMC's verdict on the assertions and how many covers it satisfied"""
    lines = [
        line
        for line in assertion_output.splitlines() + cover_output.splitlines()
        if line.startswith(("VERIFICATION", "** "))
    ]
    return "\n".join(lines)


def _run_checks(
    c_code: str, file_path: str, unwind: int
) -> IOResult[CbmcVerificationReport, Error]:
    assertion_args = ["--unwind", str(unwind), "--unwinding-assertions"]
    cover_args = [
        "-DREACHABILITY",
        "--cover",
        "cover",
        "--unwind",
        str(unwind),
    ]
    return write_file_contents(c_code, file_path).bind(  # pyright: ignore[reportUnknownMemberType]
        lambda _: _run_cbmc(file_path, assertion_args).bind(  # pyright: ignore[reportUnknownMemberType]
            lambda assertion_output: IOResult.from_result(
                _check_assertions(assertion_output)
            ).bind(  # pyright: ignore[reportUnknownMemberType]
                lambda _: _run_cbmc(file_path, cover_args).bind(  # pyright: ignore[reportUnknownMemberType]
                    lambda cover_output: IOResult.from_result(
                        _check_coverage(cover_output, c_code)
                    ).map(  # pyright: ignore[reportUnknownMemberType]
                        lambda _: CbmcVerificationReport(
                            file_path,
                            c_code,
                            assertion_args,
                            _summary(assertion_output, cover_output),
                        )
                    )
                )
            )
        )
    )


def verify_with_cbmc(
    state: State, cwp: Cwp, bpmn: Bpmn, file_path: str = OUTPUT_FILE
) -> IOResult[CbmcVerificationReport, Error]:
    builder = CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn)
    return IOResult.from_result(builder.build()).bind(  # pyright: ignore[reportUnknownMemberType]
        lambda c_code: IOResult.from_result(builder.unwind()).bind(  # pyright: ignore[reportUnknownMemberType]
            lambda unwind: _run_checks(c_code, file_path, unwind)
        )
    )
