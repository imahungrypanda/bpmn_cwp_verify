import os
import re
import subprocess

from returns.io import IOFailure, IOResult, IOSuccess, impure_safe
from returns.result import Failure, Result, Success

from bpmncwpverify.builder.cbmc_builder import (
    REACHABILITY_MACRO,
    CbmcBuilder,
    CbmcOutputs,
)
from bpmncwpverify.core.bpmn import Bpmn
from bpmncwpverify.core.cwp import Cwp
from bpmncwpverify.core.error import (
    CbmcAssertionError,
    CbmcRunError,
    CbmcUnreachableError,
    Error,
    NotInitializedError,
)
from bpmncwpverify.core.state import State
from bpmncwpverify.util.file import write_file_contents

OUTPUT_FILE = "/tmp/verification.c"

# CBMC exits with 0 when verification succeeds and 10 when it fails; anything
# else (parse errors, bad options) means it did not check the program.
_CBMC_OK_CODES = (0, 10)

_FAILED_PROPERTY = re.compile(
    r"^\[(?P<property>[^\]]+)\] line (?P<line>\d+) (?P<description>.*): FAILURE$",
    re.MULTILINE,
)
_COVER_RESULT = re.compile(
    r"^\[(?P<property>[^\]]+)\] file \S+ line (?P<line>\d+) .*: (?P<status>SATISFIED|FAILED)$",
    re.MULTILINE,
)


def _assertion_args(unwind: int) -> list[str]:
    return ["--unwind", str(unwind), "--unwinding-assertions"]


def _reachability_args(unwind: int) -> list[str]:
    return [f"-D{REACHABILITY_MACRO}", "--cover", "cover", "--unwind", str(unwind)]


def parse_assertion_failures(cbmc_report: str) -> Result[None, Error]:
    """Fails when CBMC reported an assertion (or unwinding assertion) failure."""
    failures = [m.groupdict() for m in _FAILED_PROPERTY.finditer(cbmc_report)]
    return Failure(CbmcAssertionError(failures)) if failures else Success(None)


def parse_unreached(c_code: str, cbmc_report: str) -> Result[None, Error]:
    """Fails when a cover could not be satisfied, naming it from its C source."""
    source = c_code.splitlines()
    unreached: list[dict[str, str]] = []
    for match in _COVER_RESULT.finditer(cbmc_report):
        if match["status"] != "FAILED":
            continue
        line = int(match["line"])
        text = source[line - 1].strip() if 0 < line <= len(source) else ""
        cover = re.match(r"__CPROVER_cover\((.*)\);$", text)
        unreached.append(
            {
                "property": match["property"],
                "line": match["line"],
                "description": cover[1] if cover else text,
            }
        )
    return Failure(CbmcUnreachableError(unreached)) if unreached else Success(None)


def _run_cbmc(file_path: str, cli_args: list[str]) -> IOResult[str, Error]:
    def cbmc() -> str:
        completed = subprocess.run(
            ["cbmc", os.path.basename(file_path)] + cli_args,
            capture_output=True,
            text=True,
            cwd=os.path.dirname(file_path),
        )
        if completed.returncode not in _CBMC_OK_CODES:
            raise RuntimeError(
                f"cbmc exited with {completed.returncode}: "
                f"{(completed.stderr or completed.stdout).strip()}"
            )
        return completed.stdout

    return impure_safe(cbmc)().alt(lambda exc: CbmcRunError(str(exc)))


class CbmcVerificationReport:
    __slots__ = [
        "file_path",
        "c_code",
        "bound",
        "assertion_report",
        "reachability_report",
    ]

    def __init__(
        self,
        file_path: str,
        c_code: str,
        bound: int,
        assertion_report: str,
        reachability_report: str,
    ) -> None:
        self.file_path = file_path
        self.c_code = c_code
        self.bound = bound
        self.assertion_report = assertion_report
        self.reachability_report = reachability_report

    @property
    def cbmc_report(self) -> str:
        return f"{self.assertion_report}\n{self.reachability_report}"


def _run_cbmc_checks(
    outputs: CbmcOutputs, file_path: str
) -> IOResult[CbmcVerificationReport, Error]:
    unwind = outputs.unwind

    def check_assertions() -> IOResult[str, Error]:
        return _run_cbmc(file_path, _assertion_args(unwind)).bind(  # pyright: ignore[reportUnknownMemberType]
            lambda report: IOResult.from_result(
                parse_assertion_failures(report).map(lambda _: report)
            )
        )

    def check_reachability() -> IOResult[str, Error]:
        return _run_cbmc(file_path, _reachability_args(unwind)).bind(  # pyright: ignore[reportUnknownMemberType]
            lambda report: IOResult.from_result(
                parse_unreached(outputs.c_code, report).map(lambda _: report)
            )
        )

    return (
        write_file_contents(outputs.c_code, file_path)
        .bind(lambda _: check_assertions())  # pyright: ignore[reportUnknownMemberType]
        .bind(
            lambda assertion_report: check_reachability().map(  # pyright: ignore[reportUnknownMemberType]
                lambda reachability_report: CbmcVerificationReport(
                    file_path,
                    outputs.c_code,
                    outputs.bound,
                    assertion_report,
                    reachability_report,
                )
            )
        )
    )


class CbmcVerificationReportBuilder:
    __slots__ = ["file_path", "outputs"]

    def __init__(self) -> None:
        self.file_path: IOResult[str, Error] = IOFailure(
            NotInitializedError("CbmcVerificationReportBuilder.file_path")
        )
        self.outputs: IOResult[CbmcOutputs, Error] = IOFailure(
            NotInitializedError("CbmcVerificationReportBuilder.outputs")
        )

    def build(self) -> IOResult[CbmcVerificationReport, Error]:
        return self.outputs.bind(  # pyright: ignore[reportUnknownMemberType]
            lambda outputs: self.file_path.bind(  # pyright: ignore[reportUnknownMemberType]
                lambda file_path: _run_cbmc_checks(outputs, file_path)
            )
        )

    def with_file_path(self, file_path: str) -> "CbmcVerificationReportBuilder":
        self.file_path = IOSuccess(file_path)
        return self

    def with_outputs(self, outputs: CbmcOutputs) -> "CbmcVerificationReportBuilder":
        self.outputs = IOSuccess(outputs)
        return self


def verify_with_cbmc(
    state: State,
    cwp: Cwp,
    bpmn: Bpmn,
) -> IOResult[CbmcVerificationReport, Error]:
    outputs = CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn).build()
    return IOResult.from_result(outputs).bind(  # pyright: ignore[reportUnknownMemberType]
        lambda c_outputs: (
            CbmcVerificationReportBuilder()
            .with_file_path(OUTPUT_FILE)
            .with_outputs(c_outputs)
            .build()
        )
    )
