import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

from returns.io import IOResult, impure_safe
from returns.result import Failure, Result, Success

from bpmncwpverify.builder.cbmc_builder import (
    COVER_CWP_STATE,
    COVER_END_EVENT,
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
)
from bpmncwpverify.core.state import State
from bpmncwpverify.util.file import write_file_contents

OUTPUT_FILE = "/tmp/verification.c"
CBMC_COMMON_ARGS = ["--no-standard-checks"]
# cbmc exits with 0 when it verifies and 10 when a property fails
CBMC_RAN_CODES = (0, 10)

_PROPERTY_RE = re.compile(
    r"^\[(?P<property>[^\]]+)\]\s+(?:file \S+ )?line (?P<line>\d+)\s+"
    r"(?:function \S+\s+)?(?P<description>.*?):\s+(?P<status>SUCCESS|FAILURE)\s*$",
    re.MULTILINE,
)
_COVER_RE = re.compile(
    r"^\[(?P<property>[^\]]+\.coverage\.\d+)\]\s+file \S+ line (?P<line>\d+)\s+"
    r".*:\s+(?P<status>SATISFIED|FAILED)\s*$",
    re.MULTILINE,
)
_COVER_COMMENT_RE = re.compile(
    rf"/\* (?P<kind>{COVER_END_EVENT}|{COVER_CWP_STATE}) (?P<name>.*) \*/"
)


class CbmcVerificationReport:
    __slots__ = ["file_path", "c", "cbmc_cli_args", "cbmc_report"]

    def __init__(
        self,
        file_path: str,
        c: str,
        cbmc_cli_args: list[list[str]],
        cbmc_report: str,
    ) -> None:
        self.file_path = file_path
        self.c = c
        self.cbmc_cli_args = cbmc_cli_args
        self.cbmc_report = cbmc_report


def _cbmc_args(unwind: int, reachability: bool) -> list[str]:
    args = ["--unwind", str(unwind)] + CBMC_COMMON_ARGS
    if reachability:
        args += [f"-D{REACHABILITY_MACRO}", "--cover", "cover"]
    return args


def _run_cbmc(file_path: str, args: list[str]) -> IOResult[str, Error]:
    def cbmc() -> str:
        completed = subprocess.run(
            ["cbmc", file_path] + args, capture_output=True, text=True
        )
        if completed.returncode not in CBMC_RAN_CODES:
            raise RuntimeError((completed.stdout + completed.stderr).strip())
        return completed.stdout

    return impure_safe(cbmc)().alt(lambda exc: CbmcRunError(str(exc)))


def check_assertions(cbmc_report: str) -> Result[None, Error]:
    failures = [
        {
            "property": m["property"],
            "line": m["line"],
            "description": m["description"],
        }
        for m in _PROPERTY_RE.finditer(cbmc_report)
        if m["status"] == "FAILURE"
    ]
    return Failure(CbmcAssertionError(failures)) if failures else Success(None)


def check_reachability(cbmc_report: str, c: str) -> Result[None, Error]:
    c_lines = c.split("\n")
    unreachable: list[dict[str, str]] = []
    for m in _COVER_RE.finditer(cbmc_report):
        if m["status"] != "FAILED":
            continue
        line = int(m["line"])
        comment = (
            _COVER_COMMENT_RE.search(c_lines[line - 1])
            if line <= len(c_lines)
            else None
        )
        unreachable.append(
            {
                "kind": comment["kind"] if comment else "cover",
                "name": comment["name"] if comment else f"at line {line}",
                "line": m["line"],
            }
        )
    return Failure(CbmcUnreachableError(unreachable)) if unreachable else Success(None)


def _run_cbmc_checks(
    outputs: CbmcOutputs, file_path: str
) -> IOResult[CbmcVerificationReport, Error]:
    assertion_args = _cbmc_args(outputs.unwind, reachability=False)
    cover_args = _cbmc_args(outputs.unwind, reachability=True)

    def run_both() -> tuple[IOResult[str, Error], IOResult[str, Error]]:
        # The two runs are independent processes, so they run side by side
        with ThreadPoolExecutor(max_workers=2) as pool:
            assertions = pool.submit(_run_cbmc, file_path, assertion_args)
            covers = pool.submit(_run_cbmc, file_path, cover_args)
            return assertions.result(), covers.result()

    def process(
        assertion_report: str, cover_report: str
    ) -> IOResult[CbmcVerificationReport, Error]:
        checked: Result[None, Error] = check_assertions(assertion_report).bind(  # pyright: ignore[reportUnknownMemberType]
            lambda _: check_reachability(cover_report, outputs.c)
        )
        return IOResult.from_result(checked).map(
            lambda _: CbmcVerificationReport(
                file_path,
                outputs.c,
                [assertion_args, cover_args],
                assertion_report + cover_report,
            )
        )

    def after_write(_: None) -> IOResult[CbmcVerificationReport, Error]:
        assertions, covers = run_both()
        return assertions.bind(  # pyright: ignore[reportUnknownMemberType]
            lambda a: covers.bind(lambda c: process(a, c))  # pyright: ignore[reportUnknownMemberType, reportUnknownLambdaType]
        )

    return write_file_contents(outputs.c, file_path).bind(after_write)  # pyright: ignore[reportUnknownMemberType]


def verify_with_cbmc(
    state: State,
    cwp: Cwp,
    bpmn: Bpmn,
) -> IOResult[CbmcVerificationReport, Error]:
    built: Result[CbmcOutputs, Error] = (
        CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn).build()
    )
    return IOResult.from_result(built).bind(  # pyright: ignore[reportUnknownMemberType]
        lambda outputs: _run_cbmc_checks(outputs, OUTPUT_FILE)
    )
