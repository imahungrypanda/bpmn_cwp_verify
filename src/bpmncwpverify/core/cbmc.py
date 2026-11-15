import os
import re
import subprocess

from returns.io import IOResult, impure_safe
from returns.result import Failure, Result, Success

from bpmncwpverify.builder.cbmc_builder import CbmcBuilder, CbmcProgram
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
CBMC_EXIT_CODES = (0, 10)  # verification succeeded, verification failed

_PROPERTY_RE = re.compile(
    r"^\[(?P<name>[^\]]+)\] line (?P<line>\d+) (?P<description>.*): FAILURE$",
    re.MULTILINE,
)
_COVER_RE = re.compile(
    r"^\[(?P<name>[^\]]+\.coverage\.\d+)\] file \S+ line (?P<line>\d+) .*: FAILED$",
    re.MULTILINE,
)
_CWP_COVER_RE = re.compile(r"cwp_state == CWP_STATE_(?P<name>\w+)\)")
_END_COVER_RE = re.compile(r"/\* (?P<name>\w+) \*/")


class CbmcVerificationReport:
    __slots__ = ["file_path", "c_source", "unwind", "cbmc_report", "cover_report"]

    def __init__(
        self,
        file_path: str,
        c_source: str,
        unwind: int,
        cbmc_report: str,
        cover_report: str,
    ) -> None:
        self.file_path = file_path
        self.c_source = c_source
        self.unwind = unwind
        self.cbmc_report = cbmc_report
        self.cover_report = cover_report


def _run_cbmc(file_path: str, cli_args: list[str]) -> IOResult[str, Error]:
    file_name = os.path.basename(file_path)

    def cbmc() -> str:
        completed = subprocess.run(
            ["cbmc", file_name] + cli_args,
            capture_output=True,
            text=True,
            cwd=os.path.dirname(file_path),
        )
        if completed.returncode not in CBMC_EXIT_CODES:
            raise RuntimeError(
                f"cbmc exited with code {completed.returncode}: "
                f"{(completed.stderr or completed.stdout).strip()}"
            )
        return completed.stdout

    return impure_safe(cbmc)().alt(lambda exc: CbmcRunError(str(exc)))


def _check_assertions(report: str) -> Result[None, Error]:
    failures = [m.groupdict() for m in _PROPERTY_RE.finditer(report)]
    return Failure(CbmcAssertionError(failures)) if failures else Success(None)


def _unreachable_target(source_line: str) -> dict[str, str]:
    if match := _CWP_COVER_RE.search(source_line):
        return {"kind": "CWP state", "name": match.group("name")}
    if match := _END_COVER_RE.search(source_line):
        return {"kind": "end event", "name": match.group("name")}
    return {"kind": "target", "name": source_line.strip()}


def _check_reachability(c_source: str, report: str) -> Result[None, Error]:
    source_lines = c_source.splitlines()
    unreachable = [
        _unreachable_target(source_lines[int(m.group("line")) - 1])
        for m in _COVER_RE.finditer(report)
    ]
    return Failure(CbmcUnreachableError(unreachable)) if unreachable else Success(None)


def _run_program(
    program: CbmcProgram, file_path: str
) -> IOResult[CbmcVerificationReport, Error]:
    unwind = ["--unwind", str(program.unwind)]
    cover = ["-DREACHABILITY", "--cover", "cover"] + unwind

    return (
        write_file_contents(program.source, file_path)
        .bind(lambda _: _run_cbmc(file_path, unwind))  # pyright: ignore[reportUnknownMemberType, reportUnknownLambdaType]
        .bind(
            lambda report: IOResult.from_result(_check_assertions(report)).bind(  # pyright: ignore[reportUnknownMemberType, reportUnknownLambdaType]
                lambda _: _run_cbmc(file_path, cover).bind(  # pyright: ignore[reportUnknownMemberType, reportUnknownLambdaType]
                    lambda cover_report: IOResult.from_result(
                        _check_reachability(program.source, cover_report)
                    ).map(
                        lambda _: CbmcVerificationReport(
                            file_path,
                            program.source,
                            program.unwind,
                            report,
                            cover_report,
                        )
                    )
                )
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
        lambda p: _run_program(p, file_path)
    )
