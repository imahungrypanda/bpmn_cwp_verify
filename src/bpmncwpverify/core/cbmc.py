import os
import re
import subprocess

from returns.io import IOResult, impure_safe
from returns.result import Failure, Result, Success

from bpmncwpverify.builder.cbmc_builder import COVER_MARK, CbmcBuilder
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

# `--slice-formula` keeps the first run well under a minute on larger workflows
ASSERTION_ARGS = ["--unwinding-assertions", "--slice-formula"]
REACHABILITY_ARGS = ["-DREACHABILITY", "--cover", "cover"]

_PROPERTY_RE = re.compile(
    r"^\[(?P<id>[^\]]+)\] (?:file \S+ )?line (?P<line>\d+) (?P<rest>.*): "
    r"(?P<status>SUCCESS|FAILURE|SATISFIED|FAILED)\s*$",
    re.MULTILINE,
)


def _run_cbmc(file_path: str, cli_args: list[str]) -> IOResult[str, Error]:
    def cbmc() -> str:
        completed = subprocess.run(
            ["cbmc", os.path.basename(file_path)] + cli_args,
            capture_output=True,
            text=True,
            cwd=os.path.dirname(file_path) or None,
        )
        output = completed.stdout
        # CBMC exits with 0 or 10 when it checked the program, anything else is an error
        if completed.returncode not in (0, 10):
            raise RuntimeError((completed.stdout + completed.stderr).strip()[-500:])
        return output

    return impure_safe(cbmc)().alt(lambda exc: CbmcRunError(str(exc)))


def _check_assertions(report: str) -> Result[None, Error]:
    failures = [
        {
            "line": match["line"],
            "description": match["rest"].removeprefix("function ").strip(),
        }
        for match in _PROPERTY_RE.finditer(report)
        if match["status"] == "FAILURE"
    ]
    if failures:
        return Failure(CbmcAssertionError(failures))
    if "VERIFICATION SUCCESSFUL" not in report:
        return Failure(CbmcRunError("CBMC did not report a result"))
    return Success(None)


def _check_reachability(report: str, c: str) -> Result[None, Error]:
    lines = c.splitlines()
    covers = list(_PROPERTY_RE.finditer(report))
    if not covers:
        return Failure(CbmcRunError("CBMC did not report any coverage"))
    unreachable: list[str] = []
    for match in covers:
        if match["status"] != "FAILED":
            continue
        source = lines[int(match["line"]) - 1]
        mark = source.find(COVER_MARK)
        unreachable.append(
            source[mark + len(COVER_MARK) :].strip(" */")
            if mark >= 0
            else f"line {match['line']}"
        )
    return Failure(CbmcUnreachableError(unreachable)) if unreachable else Success(None)


class CbmcVerificationReport:
    __slots__ = ["c", "cbmc_report", "file_path", "unwind"]

    def __init__(self, file_path: str, c: str, unwind: int, cbmc_report: str) -> None:
        self.file_path = file_path
        self.c = c
        self.unwind = unwind
        self.cbmc_report = cbmc_report


def _verify(
    c: str, file_path: str, unwind: int
) -> IOResult[CbmcVerificationReport, Error]:
    unwind_args = ["--unwind", str(unwind)]

    def check_reachability(assertion_report: str) -> IOResult[str, Error]:
        return _run_cbmc(file_path, unwind_args + REACHABILITY_ARGS).bind(  # pyright: ignore[reportUnknownMemberType]
            lambda cover_report: IOResult.from_result(
                _check_reachability(cover_report, c)
            ).map(lambda _: assertion_report + "\n" + cover_report)
        )

    return (
        write_file_contents(c, file_path)  # pyright: ignore[reportUnknownMemberType]
        .bind(lambda _: _run_cbmc(file_path, unwind_args + ASSERTION_ARGS))  # pyright: ignore[reportUnknownMemberType, reportUnknownLambdaType]
        .bind(  # pyright: ignore[reportUnknownMemberType]
            lambda report: IOResult.from_result(_check_assertions(report)).bind(  # pyright: ignore[reportUnknownMemberType]
                lambda _: check_reachability(report)
            )
        )
        .map(lambda report: CbmcVerificationReport(file_path, c, unwind, report))  # pyright: ignore[reportUnknownMemberType, reportUnknownLambdaType]
    )


def verify_with_cbmc(
    state: State, cwp: Cwp, bpmn: Bpmn
) -> IOResult[CbmcVerificationReport, Error]:
    builder = CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn)
    c_result: Result[str, Error] = builder.build()
    unwind_result: Result[int, Error] = builder.unwind()
    return IOResult.from_result(c_result).bind(  # pyright: ignore[reportUnknownMemberType]
        lambda c: IOResult.from_result(unwind_result).bind(  # pyright: ignore[reportUnknownMemberType]
            lambda unwind: _verify(c, OUTPUT_FILE, unwind)
        )
    )
