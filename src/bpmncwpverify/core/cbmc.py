import os
import re
import subprocess
import tempfile

from returns.io import IOResult, IOSuccess, impure_safe
from returns.result import Result

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

CBMC_TIMEOUT_SECONDS = 600
# CBMC exits with 0 when the properties hold and 10 when some don't. Anything else is a failure to run.
_CBMC_OK_CODES = (0, 10)

_PROPERTY_RE = re.compile(
    r"^\[(?P<id>[^\]]+)\] line (?P<line>\d+) (?P<description>.*): (?P<status>SUCCESS|FAILURE)$",
    re.MULTILINE,
)
_COVER_RE = re.compile(
    r"^\[(?P<id>[^\]]+\.coverage\.\d+)\] file \S+ line (?P<line>\d+) .*: (?P<status>SATISFIED|FAILED)$",
    re.MULTILINE,
)
_COVER_NAME_RE = re.compile(r"//\s*(?P<name>(?:end event|CWP state) .+)$")


class CbmcVerificationReport:
    __slots__ = [
        "file_path",
        "c_source",
        "unwind",
        "cbmc_report",
        "reachability_report",
    ]

    def __init__(
        self,
        file_path: str,
        c_source: str,
        unwind: int,
        cbmc_report: str,
        reachability_report: str,
    ) -> None:
        self.file_path = file_path
        self.c_source = c_source
        self.unwind = unwind
        self.cbmc_report = cbmc_report
        self.reachability_report = reachability_report

    @property
    def report(self) -> str:
        return f"{self.cbmc_report}\n{self.reachability_report}"


def _run_cbmc(file_path: str, cbmc_args: list[str]) -> IOResult[str, Error]:
    file_name = os.path.basename(file_path)

    def cbmc() -> str:
        completed = subprocess.run(
            ["cbmc", file_name] + cbmc_args,
            capture_output=True,
            text=True,
            cwd=os.path.dirname(file_path),
            timeout=CBMC_TIMEOUT_SECONDS,
        )
        if completed.returncode not in _CBMC_OK_CODES:
            raise RuntimeError(
                f"cbmc exited with status {completed.returncode}: "
                f"{(completed.stdout + completed.stderr).strip()}"
            )
        return completed.stdout

    return impure_safe(cbmc)().alt(lambda exc: CbmcRunError(str(exc)))


def check_assertions(file_path: str, report: str) -> Result[None, Error]:
    failures = [
        {k: v.strip() for k, v in m.groupdict().items()}
        for m in _PROPERTY_RE.finditer(report)
        if m.group("status") == "FAILURE"
    ]
    return (
        Result.from_failure(CbmcAssertionError(failures))
        if failures
        else Result.from_value(None)
    )


def check_reachability(c_source: str, report: str) -> Result[None, Error]:
    lines = c_source.splitlines()
    unreachable: list[str] = []
    for m in _COVER_RE.finditer(report):
        if m.group("status") != "FAILED":
            continue
        line_no = int(m.group("line"))
        name = (
            _COVER_NAME_RE.search(lines[line_no - 1]) if line_no <= len(lines) else None
        )
        unreachable.append(name.group("name") if name else f"line {line_no}")
    return (
        Result.from_failure(CbmcUnreachableError(unreachable))
        if unreachable
        else Result.from_value(None)
    )


def _verify(
    c_source: str, bound_unwind: int, file_path: str
) -> IOResult[CbmcVerificationReport, Error]:
    unwind = ["--unwind", str(bound_unwind)]
    return (
        write_file_contents(c_source, file_path)
        .bind(  # pyright: ignore[reportUnknownMemberType]
            lambda _: _run_cbmc(file_path, unwind + ["--unwinding-assertions"])
        )
        .bind(  # pyright: ignore[reportUnknownMemberType]
            lambda cbmc_report: IOResult.from_result(
                check_assertions(file_path, cbmc_report)
            ).bind(  # pyright: ignore[reportUnknownMemberType]
                lambda _: _run_cbmc(
                    file_path,
                    [f"-D{REACHABILITY_MACRO}", "--cover", "cover"] + unwind,
                ).bind(  # pyright: ignore[reportUnknownMemberType]
                    lambda reach_report: IOResult.from_result(
                        check_reachability(c_source, reach_report)
                    ).bind(  # pyright: ignore[reportUnknownMemberType]
                        lambda _: IOSuccess(
                            CbmcVerificationReport(
                                file_path,
                                c_source,
                                bound_unwind,
                                cbmc_report,
                                reach_report,
                            )
                        )
                    )
                )
            )
        )
    )


def _make_dir() -> IOResult[str, Error]:
    def make_dir() -> str:
        return tempfile.mkdtemp(prefix="bpmncwpverify_")

    return impure_safe(make_dir)().alt(lambda exc: CbmcRunError(str(exc)))  # pyright: ignore[reportReturnType]


def verify_with_cbmc(
    state: State, cwp: Cwp, bpmn: Bpmn
) -> IOResult[CbmcVerificationReport, Error]:
    program: Result[CbmcProgram, Error] = (
        CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn).build()
    )
    directory: IOResult[str, Error] = _make_dir()
    return IOResult.from_result(program).bind(  # pyright: ignore[reportUnknownMemberType]
        lambda p: directory.bind(  # pyright: ignore[reportUnknownMemberType, reportUnknownLambdaType]
            lambda d: _verify(p.source, p.unwind, os.path.join(d, "verification.c"))
        )
    )
