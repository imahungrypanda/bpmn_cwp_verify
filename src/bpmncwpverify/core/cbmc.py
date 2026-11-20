import os
import re
import subprocess

from returns.io import IOFailure, IOResult, impure_safe
from returns.result import Failure, Result, Success

from bpmncwpverify.builder.cbmc_builder import REACHABILITY_MACRO, CbmcBuilder
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

# CBMC exits with 0 when it has nothing to report and 10 when a property fails
_OK_EXIT_CODES = (0, 10)


class CbmcVerificationReport:
    __slots__ = ["file_path", "c_code", "cbmc_cli_args", "cbmc_report"]

    def __init__(
        self,
        file_path: str,
        c_code: str,
        cbmc_cli_args: list[str],
        cbmc_report: str,
    ) -> None:
        self.file_path = file_path
        self.c_code = c_code
        self.cbmc_cli_args = cbmc_cli_args
        self.cbmc_report = cbmc_report


def _run_cbmc(file_path: str, cli_args: list[str]) -> IOResult[str, Error]:
    file_name = os.path.basename(file_path)
    file_dir = os.path.dirname(file_path)

    def cbmc_subprocess() -> str:
        completed = subprocess.run(
            ["cbmc", file_name] + cli_args,
            capture_output=True,
            text=True,
            cwd=file_dir or None,
        )
        if completed.returncode not in _OK_EXIT_CODES:
            raise RuntimeError(
                f"cbmc exited with code {completed.returncode}: "
                f"{(completed.stdout + completed.stderr).strip()}"
            )
        return completed.stdout

    return impure_safe(cbmc_subprocess)().alt(lambda exc: CbmcRunError(str(exc)))


def check_assertions(report: str) -> Result[None, Error]:
    """Fails if CBMC reports a failed assertion (an unwinding assertion included)."""
    failures = [
        {"id": m.group("id"), "line": m.group("line"), "description": m.group("desc")}
        for m in re.finditer(
            r"^\[(?P<id>[^\]]+)\] line (?P<line>\d+) (?P<desc>.*): FAILURE$",
            report,
            re.MULTILINE,
        )
    ]
    return Failure(CbmcAssertionError(failures)) if failures else Success(None)


def check_reachability(report: str, c_code: str) -> Result[None, Error]:
    """
    Fails if a cover is unsatisfied. A cover is named by the comment on its
    line of the C file, and a name is unreachable only if all its covers are.
    """
    lines = c_code.split("\n")
    reached: dict[str, bool] = {}
    for m in re.finditer(
        r"^\[[^\]]+\] file \S+ line (?P<line>\d+) .*: (?P<result>SATISFIED|FAILED)$",
        report,
        re.MULTILINE,
    ):
        line = lines[int(m.group("line")) - 1]
        comment = re.search(r"/\* (.*) \*/\s*$", line)
        name = comment.group(1) if comment else f"line {m.group('line')}"
        reached[name] = reached.get(name, False) or m.group("result") == "SATISFIED"
    unreachable = [name for name, ok in reached.items() if not ok]
    return Failure(CbmcUnreachableError(unreachable)) if unreachable else Success(None)


def _verify(
    c_code: str, unwind: int, file_path: str
) -> IOResult[CbmcVerificationReport, Error]:
    assertion_args = ["--unwind", str(unwind), "--unwinding-assertions"]
    cover_args = [
        f"-D{REACHABILITY_MACRO}",
        "--unwind",
        str(unwind),
        "--cover",
        "cover",
    ]

    def assertions(_: None) -> IOResult[str, Error]:
        return _run_cbmc(file_path, assertion_args).bind(  # pyright: ignore[reportUnknownMemberType]
            lambda report: IOResult.from_result(check_assertions(report)).map(
                lambda _: report
            )
        )

    def reachability(assertion_report: str) -> IOResult[CbmcVerificationReport, Error]:
        return _run_cbmc(file_path, cover_args).bind(  # pyright: ignore[reportUnknownMemberType]
            lambda report: IOResult.from_result(check_reachability(report, c_code)).map(
                lambda _: CbmcVerificationReport(
                    file_path,
                    c_code,
                    assertion_args,
                    f"{assertion_report}\n{report}",
                )
            )
        )

    return write_file_contents(c_code, file_path).bind(assertions).bind(reachability)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]


def verify_with_cbmc(
    state: State, cwp: Cwp, bpmn: Bpmn, file_path: str = OUTPUT_FILE
) -> IOResult[CbmcVerificationReport, Error]:
    built = CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn).build()
    if isinstance(built, Failure):
        return IOFailure(built.failure())
    program = built.unwrap()
    return _verify(program.code, program.unwind, file_path)
