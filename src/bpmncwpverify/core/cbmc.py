import json
import os
import shutil
import subprocess
import tempfile
from typing import Any

from returns.io import IOFailure, IOResult, IOSuccess, impure_safe
from returns.result import Failure, Result, Success
from returns.unsafe import unsafe_perform_io

from bpmncwpverify.builder.cbmc_builder import REACHABILITY_MACRO, CbmcBuilder
from bpmncwpverify.core.bpmn import Bpmn
from bpmncwpverify.core.cwp import Cwp
from bpmncwpverify.core.error import (
    CbmcAssertionError,
    CbmcRunError,
    CbmcUnreachableError,
    Error,
    SubProcessRunError,
)
from bpmncwpverify.core.state import State
from bpmncwpverify.util.file import write_file_contents

C_FILE_NAME = "verification.c"

# CBMC exits with 0 when verification succeeds and 10 when a property fails.
# Anything else means CBMC did not get to check the program.
_CBMC_OK_EXIT_CODES = (0, 10)


class CbmcVerificationReport:
    __slots__ = ["c_program", "bound", "assertion_report", "reachability_report"]

    def __init__(
        self,
        c_program: str,
        bound: int,
        assertion_report: str,
        reachability_report: str,
    ) -> None:
        self.c_program = c_program
        self.bound = bound
        self.assertion_report = assertion_report
        self.reachability_report = reachability_report

    def summary(self) -> str:
        return (
            "CBMC verification successful: no assertion fails and every end event "
            f"and CWP state is reachable (unwinding bound {self.bound})"
        )


def _run_cbmc(
    file_name: str, file_dir: str, cli_args: list[str]
) -> IOResult[str, Error]:
    def cbmc() -> str:
        completed = subprocess.run(
            ["cbmc", file_name, "--json-ui"] + cli_args,
            capture_output=True,
            text=True,
            cwd=file_dir,
        )
        if completed.returncode not in _CBMC_OK_EXIT_CODES:
            raise RuntimeError(_cbmc_messages(completed.stdout) or completed.stderr)
        return completed.stdout

    return impure_safe(cbmc)().alt(
        lambda exc: (
            CbmcRunError(str(exc))
            if isinstance(exc, RuntimeError)
            else SubProcessRunError("cbmc")
        )
    )


def _load(output: str) -> Result[list[dict[str, Any]], Error]:
    """The objects in CBMC's JSON output."""
    try:
        items = json.loads(output)
    except json.JSONDecodeError as exc:
        return Failure(CbmcRunError(f"unreadable CBMC output: {exc}"))
    return Success([item for item in items if isinstance(item, dict)])  # pyright: ignore[reportUnknownVariableType]


def _cbmc_messages(output: str) -> str:
    """The error messages in CBMC's JSON output, or the output when not JSON."""
    items = _load(output)
    if isinstance(items, Failure):
        return output.strip()
    return "; ".join(
        str(item["messageText"])
        for item in items.unwrap()
        if item.get("messageType") == "ERROR"
    )


def _describe(item: dict[str, Any]) -> dict[str, str]:
    location: dict[str, Any] = item.get("sourceLocation") or {}
    return {
        "description": str(item.get("description", "")),
        "line": str(location.get("line", "")),
        "function": str(location.get("function", "")),
    }


def _properties(output: str) -> Result[list[dict[str, Any]], Error]:
    """
    The checked properties in CBMC's JSON output: the `result` list, or, when
    CBMC was told to stop at the first failure, the one failing property.
    """
    loaded = _load(output)
    if isinstance(loaded, Failure):
        return loaded
    items = loaded.unwrap()
    if not any("cProverStatus" in item for item in items):
        return Failure(CbmcRunError("CBMC did not report a verification result"))
    properties: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item.get("result"), list):
            properties.extend(item["result"])
        elif "property" in item and "status" in item:
            properties.append(item)
    return Success(properties)


def check_assertions(output: str) -> Result[None, Error]:
    """Fails with the assertions CBMC found failing in the assertion run."""
    properties = _properties(output)
    if isinstance(properties, Failure):
        return properties
    failures = [
        _describe(p) for p in properties.unwrap() if p.get("status") != "SUCCESS"
    ]
    return Failure(CbmcAssertionError(failures)) if failures else Success(None)


def _cover_comment(c_program: str, line: str) -> str:
    """The comment naming the element a `__CPROVER_cover` line stands for."""
    lines = c_program.splitlines()
    text = lines[int(line) - 1] if line.isdigit() and int(line) <= len(lines) else ""
    return text.split("// ", 1)[1].strip() if "// " in text else ""


def check_reachability(output: str, c_program: str = "") -> Result[None, Error]:
    """Fails with the covers CBMC could not satisfy in the reachability run."""
    loaded = _load(output)
    if isinstance(loaded, Failure):
        return loaded
    goal_lists = [item["goals"] for item in loaded.unwrap() if "goals" in item]
    if not goal_lists:
        return Failure(CbmcRunError("no 'goals' in the CBMC output"))
    missed: list[dict[str, str]] = []
    for goal in goal_lists[0]:
        if str(goal.get("status")).lower() != "satisfied":
            described = _describe(goal)
            comment = _cover_comment(c_program, described["line"])
            missed.append(
                described | {"description": comment or described["description"]}
            )
    return Failure(CbmcUnreachableError(missed)) if missed else Success(None)


def _run_both(
    c_program: str, bound: int, file_path: str
) -> IOResult[CbmcVerificationReport, Error]:
    file_name = os.path.basename(file_path)
    file_dir = os.path.dirname(file_path)
    unwind = ["--unwind", str(bound + 1)]

    written = write_file_contents(c_program, file_path)
    if isinstance(written, IOFailure):
        return written

    # Stops at the first failing assertion: the answer is the same, and it keeps
    # a workflow that is broken from taking as long as one that is not.
    assertion_run = _run_cbmc(file_name, file_dir, unwind + ["--stop-on-fail"])
    if isinstance(assertion_run, IOFailure):
        return assertion_run
    assertion_report = unsafe_perform_io(assertion_run.unwrap())
    checked = check_assertions(assertion_report)
    if isinstance(checked, Failure):
        return IOFailure(checked.failure())

    cover_args = [f"-D{REACHABILITY_MACRO}", "--cover", "cover"] + unwind
    reachability_run = _run_cbmc(file_name, file_dir, cover_args)
    if isinstance(reachability_run, IOFailure):
        return reachability_run
    reachability_report = unsafe_perform_io(reachability_run.unwrap())
    checked = check_reachability(reachability_report, c_program)
    if isinstance(checked, Failure):
        return IOFailure(checked.failure())

    return IOSuccess(
        CbmcVerificationReport(c_program, bound, assertion_report, reachability_report)
    )


def verify_with_cbmc(
    state: State, cwp: Cwp, bpmn: Bpmn
) -> IOResult[CbmcVerificationReport, Error]:
    builder = CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn)
    c_program = builder.build()
    if isinstance(c_program, Failure):
        return IOFailure(c_program.failure())
    bound = builder.bound()
    if isinstance(bound, Failure):
        return IOFailure(bound.failure())

    work_dir = tempfile.mkdtemp(prefix="bpmncwpverify_")
    try:
        return _run_both(
            c_program.unwrap(), bound.unwrap(), os.path.join(work_dir, C_FILE_NAME)
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
