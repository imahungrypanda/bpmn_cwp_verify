import os
import re
import subprocess

from returns.io import IOResult, impure_safe
from returns.result import Failure, Result, Success

from bpmncwpverify.builder.cbmc_builder import (
    REACHABILITY_MACRO,
    CbmcBuilder,
    CbmcProgram,
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

# Exit codes of cbmc: 0 means it verified, 10 means a property failed.
_CBMC_OK_CODES = (0, 10)


class CbmcVerificationReport:
    __slots__ = ["file_path", "c_code", "bound", "cbmc_report"]

    def __init__(
        self, file_path: str, c_code: str, bound: int, cbmc_report: str
    ) -> None:
        self.file_path = file_path
        self.c_code = c_code
        self.bound = bound
        self.cbmc_report = cbmc_report


def _run_cbmc(file_path: str, cli_args: list[str]) -> IOResult[str, Error]:
    def cbmc() -> str:
        proc = subprocess.run(
            ["cbmc", os.path.basename(file_path)] + cli_args,
            capture_output=True,
            text=True,
            cwd=os.path.dirname(file_path) or None,
        )
        if proc.returncode not in _CBMC_OK_CODES:
            raise RuntimeError(
                f"exit code {proc.returncode}: {(proc.stdout + proc.stderr).strip()}"
            )
        return proc.stdout

    return impure_safe(cbmc)().alt(lambda exc: CbmcRunError(str(exc)))


def _check_assertions(report: str) -> Result[None, Error]:
    failures = [
        {
            "property": m.group("property"),
            "line": m.group("line"),
            "description": m.group("description"),
        }
        for m in re.finditer(
            r"^\[(?P<property>[^\]]+)\] (?:file \S+ )?line (?P<line>\d+) "
            r"(?P<description>.*): FAILURE$",
            report,
            re.MULTILINE,
        )
    ]
    return Failure(CbmcAssertionError(failures)) if failures else Success(None)


def _check_reachability(report: str, c_code: str) -> Result[None, Error]:
    c_lines = c_code.splitlines()
    unreachable: list[str] = []
    for m in re.finditer(
        r"^\[[^\]]+\] file \S+ line (?P<line>\d+) .*: FAILED$", report, re.MULTILINE
    ):
        source = c_lines[int(m.group("line")) - 1]
        label = re.search(r"/\* (.*) \*/", source)
        unreachable.append(label.group(1) if label else f"line {m.group('line')}")
    return Failure(CbmcUnreachableError(unreachable)) if unreachable else Success(None)


def _verify(
    program: CbmcProgram, file_path: str
) -> IOResult[CbmcVerificationReport, Error]:
    unwind = ["--unwind", str(program.unwind)]
    assertion_args = unwind + ["--unwinding-assertions"]
    cover_args = unwind + [f"-D{REACHABILITY_MACRO}", "--cover", "cover"]

    def assertions() -> IOResult[str, Error]:
        return _run_cbmc(file_path, assertion_args).bind(  # pyright: ignore[reportUnknownMemberType]
            lambda report: IOResult.from_result(
                _check_assertions(report).map(lambda _: report)
            )
        )

    def reachability(first_report: str) -> IOResult[str, Error]:
        return _run_cbmc(file_path, cover_args).bind(  # pyright: ignore[reportUnknownMemberType]
            lambda report: IOResult.from_result(
                _check_reachability(report, program.c_code).map(
                    lambda _: first_report + "\n" + report
                )
            )
        )

    return (
        write_file_contents(program.c_code, file_path)
        .bind(lambda _: assertions())  # pyright: ignore[reportUnknownMemberType, reportUnknownLambdaType]
        .bind(reachability)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        .map(
            lambda report: CbmcVerificationReport(
                file_path, program.c_code, program.bound, report
            )
        )
    )


def verify_with_cbmc(
    state: State, cwp: Cwp, bpmn: Bpmn, file_path: str = OUTPUT_FILE
) -> IOResult[CbmcVerificationReport, Error]:
    program: Result[CbmcProgram, Error] = (
        CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn).build_program()
    )
    return IOResult.from_result(program).bind(  # pyright: ignore[reportUnknownMemberType]
        lambda p: _verify(p, file_path)
    )
