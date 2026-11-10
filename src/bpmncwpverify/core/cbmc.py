import re
import subprocess

from returns.io import IOResult, impure_safe
from returns.result import Result

from bpmncwpverify.builder.cbmc_builder import CbmcBuilder
from bpmncwpverify.core.bpmn import Bpmn
from bpmncwpverify.core.cwp import Cwp
from bpmncwpverify.core.error import (
    CbmcAssertionError,
    CbmcRunError,
    CbmcUnreachableStateError,
    Error,
)
from bpmncwpverify.core.state import State
from bpmncwpverify.util.file import write_file_contents

OUTPUT_FILE = "/tmp/verification.c"
COVERAGE_OUTPUT_FILE = "/tmp/verification_cover.c"

# CBMC exits with 0 when verification succeeds and 10 when a property fails.
# Anything else (parse errors, usage errors, ...) means CBMC did not verify.
_CBMC_EXIT_CODES = (0, 10)


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
            ["cbmc", file_path] + cli_args, capture_output=True, text=True
        )
        if completed.returncode not in _CBMC_EXIT_CODES:
            raise RuntimeError(
                f"exit code {completed.returncode}: "
                f"{(completed.stdout + completed.stderr).strip()}"
            )
        return completed.stdout

    return impure_safe(cbmc)().alt(lambda exc: CbmcRunError(str(exc)))


_PROPERTY_RE = re.compile(
    r"^\[(?P<property>[^\]]+)\] line (?P<line>\d+) (?P<description>.*): FAILURE$",
    re.MULTILINE,
)
_ASSERTION_RE = re.compile(r"^assertion (?P<assertion>.*?)(?: && \"(?P<msg>.*)\")?$")
_COVERAGE_RE = re.compile(
    r"^\[[^\]]+\] file \S+ line \d+ function \w+ condition '(?P<state>\w+) != FALSE': FAILED$",
    re.MULTILINE,
)


def _check_assertions(cbmc_report: str) -> Result[None, Error]:
    failures: list[dict[str, str]] = []
    for match in _PROPERTY_RE.finditer(cbmc_report):
        description = match["description"]
        assertion = _ASSERTION_RE.match(description)
        failures.append(
            {
                "property": match["property"],
                "function": match["property"].split(".")[0],
                "line": match["line"],
                "assertion": (assertion["msg"] or assertion["assertion"])
                if assertion
                else description,
            }
        )
    return (
        Result.from_failure(CbmcAssertionError(failures))
        if failures
        else Result.from_value(None)
    )


def _check_coverage(cbmc_report: str, cwp: Cwp) -> Result[None, Error]:
    # The start state holds before the first update, so it needs no cover.
    start = cwp.start_state.name if cwp.start_state else None
    unreached = [
        match["state"]
        for match in _COVERAGE_RE.finditer(cbmc_report)
        if match["state"] != start
    ]
    return (
        Result.from_failure(CbmcUnreachableStateError(unreached))
        if unreached
        else Result.from_value(None)
    )


def verify_with_cbmc(
    state: State,
    cwp: Cwp,
    bpmn: Bpmn,
) -> IOResult[CbmcVerificationReport, Error]:
    builder = CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn)
    c_result: Result[str, Error] = builder.build()
    bound_result: Result[int, Error] = builder.unwind_bound()
    coverage_result: Result[str, Error] = builder.with_state_coverage(True).build()

    def run(
        c_code: str, bound: int, coverage_c: str
    ) -> IOResult[CbmcVerificationReport, Error]:
        unwind = str(bound)
        assert_args = ["--unwind", unwind, "--unwinding-assertions"]
        cover_args = ["--unwind", unwind, "--cover", "cover"]

        def check_reachability(
            report: str,
        ) -> IOResult[CbmcVerificationReport, Error]:
            return (
                write_file_contents(coverage_c, COVERAGE_OUTPUT_FILE)
                .bind(lambda _: _run_cbmc(COVERAGE_OUTPUT_FILE, cover_args))  # pyright: ignore[reportUnknownMemberType]
                .bind(  # pyright: ignore[reportUnknownMemberType]
                    lambda cover_report: IOResult.from_result(
                        _check_coverage(cover_report, cwp)
                    ).map(
                        lambda _: CbmcVerificationReport(
                            OUTPUT_FILE,
                            c_code,
                            assert_args,
                            report + "\n" + cover_report,
                        )
                    )
                )
            )

        return (
            write_file_contents(c_code, OUTPUT_FILE)
            .bind(lambda _: _run_cbmc(OUTPUT_FILE, assert_args))  # pyright: ignore[reportUnknownMemberType]
            .bind(  # pyright: ignore[reportUnknownMemberType]
                lambda report: IOResult.from_result(_check_assertions(report)).bind(  # pyright: ignore[reportUnknownMemberType]
                    lambda _: check_reachability(report)
                )
            )
        )

    return IOResult.from_result(c_result).bind(  # pyright: ignore[reportUnknownMemberType]
        lambda c_code: IOResult.from_result(bound_result).bind(  # pyright: ignore[reportUnknownMemberType]
            lambda bound: IOResult.from_result(coverage_result).bind(  # pyright: ignore[reportUnknownMemberType]
                lambda coverage_c: run(c_code, bound, coverage_c)
            )
        )
    )
