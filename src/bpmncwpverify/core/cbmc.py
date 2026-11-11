import os
import re
import subprocess

from returns.io import IOFailure, IOResult, impure_safe
from returns.result import Failure, Result, Success

from bpmncwpverify.builder.cbmc_builder import (
    CWP_STATE_MARK,
    END_EVENT_MARK,
    REACHABILITY_MACRO,
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
CBMC_TIMEOUT_SECONDS = 600
# CBMC's exit codes: 0 the properties hold, 10 some do not. Anything else is an error
_EXIT_VERIFIED = 0
_EXIT_FAILED = 10

_FAILURE_RE = re.compile(
    r"^\[(?P<id>[^\]]+)\] (?:file \S+ )?line (?P<line>\d+) (?P<description>.*): FAILURE$",
    re.MULTILINE,
)
_COVER_RE = re.compile(
    r"^\[(?P<id>[^\]]+\.coverage\.\d+)\] file \S+ line (?P<line>\d+) .*: (?P<status>SATISFIED|FAILED)$",
    re.MULTILINE,
)
_MARK_RE = re.compile(
    rf"/\* ((?:{re.escape(CWP_STATE_MARK)}|{re.escape(END_EVENT_MARK)}).*?) \*/"
)


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


def _run_cbmc(file_path: str, cli_args: list[str]) -> IOResult[tuple[int, str], Error]:
    """Runs CBMC once, giving its exit code and everything it printed."""

    def cbmc() -> tuple[int, str]:
        completed = subprocess.run(
            ["cbmc", os.path.basename(file_path)] + cli_args,
            capture_output=True,
            text=True,
            cwd=os.path.dirname(file_path),
            timeout=CBMC_TIMEOUT_SECONDS,
        )
        return completed.returncode, completed.stdout + completed.stderr

    return impure_safe(cbmc)().alt(lambda exc: CbmcRunError(str(exc)))


def _check_run(code: int, output: str) -> Result[str, Error]:
    if code in (_EXIT_VERIFIED, _EXIT_FAILED):
        return Success(output)
    tail = " ".join(output.split())[-500:]
    return Failure(CbmcRunError(f"CBMC exited with code {code}: {tail}"))


def check_assertions(output: str) -> Result[None, Error]:
    failures = [
        {"description": m["description"], "line": m["line"]}
        for m in _FAILURE_RE.finditer(output)
    ]
    return Failure(CbmcAssertionError(failures)) if failures else Success(None)


def check_reachability(output: str, c_code: str) -> Result[None, Error]:
    """Every cover CBMC could not satisfy is something the workflow never reaches."""
    c_lines = c_code.splitlines()
    unreachable: list[str] = []
    for match in _COVER_RE.finditer(output):
        if match["status"] != "FAILED":
            continue
        line = int(match["line"])
        mark = _MARK_RE.search(c_lines[line - 1]) if 0 < line <= len(c_lines) else None
        item = mark[1] if mark else f"cover at line {line}"
        if item not in unreachable:
            unreachable.append(item)
    return Failure(CbmcUnreachableError(unreachable)) if unreachable else Success(None)


def _verify(
    c_code: str, file_path: str, bound: int, bpmn: Bpmn
) -> IOResult[CbmcVerificationReport, Error]:
    assertion_args = ["--unwind", str(bound + 1), "--unwinding-assertions"]
    reachability_args = [
        "--unwind",
        str(bound + 1),
        f"-D{REACHABILITY_MACRO}",
        "--cover",
        "cover",
    ]

    def assertion_run(_: None) -> IOResult[str, Error]:
        return _run_cbmc(file_path, assertion_args).bind(  # pyright: ignore[reportUnknownMemberType]
            lambda run: IOResult.from_result(_check_run(*run)).bind(  # pyright: ignore[reportUnknownMemberType]
                lambda out: IOResult.from_result(
                    check_assertions(out).map(lambda _: out)
                )
            )
        )

    def reachability_run(assertion_output: str) -> IOResult[str, Error]:
        return _run_cbmc(file_path, reachability_args).bind(  # pyright: ignore[reportUnknownMemberType]
            lambda run: IOResult.from_result(_check_run(*run)).bind(  # pyright: ignore[reportUnknownMemberType]
                lambda out: IOResult.from_result(
                    check_reachability(out, c_code).map(
                        lambda _: assertion_output + "\n" + out
                    )
                )
            )
        )

    return (
        write_file_contents(c_code, file_path)
        .bind(assertion_run)  # pyright: ignore[reportUnknownMemberType]
        .bind(reachability_run)  # pyright: ignore[reportUnknownMemberType]
        .map(  # pyright: ignore[reportUnknownMemberType]
            lambda report: CbmcVerificationReport(
                file_path, c_code, [assertion_args, reachability_args], report
            )
        )
    )


def verify_with_cbmc(
    state: State,
    cwp: Cwp,
    bpmn: Bpmn,
) -> IOResult[CbmcVerificationReport, Error]:
    builder = CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn)
    c_result: Result[str, Error] = builder.build()
    bound_result: Result[int, Error] = builder.bound()
    if isinstance(c_result, Failure):
        return IOFailure(c_result.failure())
    if isinstance(bound_result, Failure):
        return IOFailure(bound_result.failure())
    return _verify(c_result.unwrap(), OUTPUT_FILE, bound_result.unwrap(), bpmn)
