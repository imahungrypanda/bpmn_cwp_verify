import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

from returns.io import IOFailure, IOResult, IOSuccess, impure_safe
from returns.pipeline import is_successful
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
)
from bpmncwpverify.core.state import State
from bpmncwpverify.util.file import write_file_contents

OUTPUT_FILE = "/tmp/verification.c"
# CBMC exits with 0 when it proves everything and 10 when a property fails;
# anything else means it could not do its job
_CBMC_OK_CODES = (0, 10)
_GOAL_COMMENT = re.compile(r"/\*\s*(?P<comment>.*?)\s*\*/\s*$")

_Json = Any
MAX_PROCESSES = 8


def _cbmc_args(file_name: str, unwind: int, reachability: bool) -> list[str]:
    args = ["cbmc", file_name, "--unwind", str(unwind), "--json-ui"]
    if reachability:
        return args + [f"-D{REACHABILITY_MACRO}", "--cover", "cover"]
    # The formula only needs what the assertions depend on
    return args + ["--slice-formula"]


def _run_cbmc(args: list[str], file_dir: str) -> IOResult[list[_Json], Error]:
    def cbmc() -> tuple[int, str]:
        completed = subprocess.run(args, capture_output=True, text=True, cwd=file_dir)
        return completed.returncode, completed.stdout

    def parse(outcome: tuple[int, str]) -> Result[list[_Json], Error]:
        code, stdout = outcome
        try:
            messages = cast(list[_Json], json.loads(stdout))
        except json.JSONDecodeError:
            return Failure(CbmcRunError(f"unreadable output (exit code {code})"))
        if code not in _CBMC_OK_CODES:
            errors = [
                m["messageText"]
                for m in messages
                if m.get("messageType") == "ERROR" and "messageText" in m
            ]
            return Failure(CbmcRunError("; ".join(errors) or f"exit code {code}"))
        return Success(messages)

    def to_error(exc: Exception) -> Error:
        return CbmcRunError(str(exc))

    outcome: IOResult[tuple[int, str], Error] = impure_safe(cbmc)().alt(to_error)
    return outcome.bind(lambda result: IOResult.from_result(parse(result)))  # pyright: ignore[reportUnknownMemberType, reportUnknownLambdaType]


def _property_names(messages: list[_Json]) -> list[str]:
    return [
        str(prop["name"])
        for message in messages
        for prop in message.get("properties", [])
    ]


def _run_cbmc_in_parallel(
    args: list[str], file_dir: str
) -> IOResult[list[_Json], Error]:
    """
    CBMC checks the properties one after another, and the CWP assertions
    repeated on every pass of the loop take most of the time. So the
    properties are shared out among a few CBMC processes that run at once.
    """

    def run_group(group: list[str]) -> IOResult[list[_Json], Error]:
        selected = [arg for name in group for arg in ("--property", name)]
        return _run_cbmc(args + selected, file_dir)

    def run_groups(names: list[str]) -> IOResult[list[_Json], Error]:
        workers = max(1, min(MAX_PROCESSES, len(names), os.cpu_count() or 1))
        groups = [names[index::workers] for index in range(workers)]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            outcomes = list(pool.map(run_group, groups))
        for outcome in outcomes:
            if not is_successful(outcome):
                return outcome
        return IOSuccess(
            [
                message
                for outcome in outcomes
                for message in unsafe_perform_io(outcome.unwrap())
            ]
        )

    return _run_cbmc(args + ["--show-properties"], file_dir).bind(  # pyright: ignore[reportUnknownMemberType]
        lambda messages: run_groups(_property_names(messages))
    )


def _line(source_location: _Json) -> str:
    return str(source_location.get("line", "?"))


def _failed_assertions(messages: list[_Json]) -> list[dict[str, str]]:
    return [
        {
            "property": str(result.get("property", "")),
            "line": _line(result.get("sourceLocation", {})),
            "description": str(result.get("description", "")),
        }
        for message in messages
        for result in message.get("result", [])
        if result.get("status") == "FAILURE"
    ]


def _goal_name(c_lines: list[str], line: str, fallback: str) -> str:
    """The comment the builder put after a cover goal says what it is for."""
    if line.isdigit() and 0 < int(line) <= len(c_lines):
        match = _GOAL_COMMENT.search(c_lines[int(line) - 1])
        if match:
            return match.group("comment")
    return fallback


def _unreached_goals(messages: list[_Json], c_program: str) -> list[dict[str, str]]:
    c_lines = c_program.split("\n")
    unreached: list[dict[str, str]] = []
    for message in messages:
        for goal in message.get("goals", []):
            if goal.get("status") == "satisfied":
                continue
            line = _line(goal.get("sourceLocation", {}))
            unreached.append(
                {
                    "line": line,
                    "description": _goal_name(
                        c_lines, line, str(goal.get("description", ""))
                    ),
                }
            )
    return unreached


class CbmcVerificationReport:
    __slots__ = ["assertion_report", "c_program", "cover_report", "file_path", "unwind"]

    def __init__(
        self,
        file_path: str,
        c_program: str,
        unwind: int,
        assertion_report: list[_Json],
        cover_report: list[_Json],
    ) -> None:
        self.file_path = file_path
        self.c_program = c_program
        self.unwind = unwind
        self.assertion_report = assertion_report
        self.cover_report = cover_report

    def summary(self) -> str:
        return (
            f"CBMC verified {self.file_path} with --unwind {self.unwind}: "
            "no assertion fails and every end event and CWP state is reachable"
        )


def _check_assertions(messages: list[_Json]) -> Result[None, Error]:
    failures = _failed_assertions(messages)
    return Failure(CbmcAssertionError(failures)) if failures else Success(None)


def _check_reachability(messages: list[_Json], c_program: str) -> Result[None, Error]:
    unreached = _unreached_goals(messages, c_program)
    return Failure(CbmcUnreachableError(unreached)) if unreached else Success(None)


def _run_cbmc_on_file(
    c_program: str, file_path: str, unwind: int
) -> IOResult[CbmcVerificationReport, Error]:
    file_name = os.path.basename(file_path)
    file_dir = os.path.dirname(file_path) or "."

    def verify(
        assertion_report: list[_Json], cover_report: list[_Json]
    ) -> IOResult[CbmcVerificationReport, Error]:
        checked: Result[None, Error] = _check_assertions(assertion_report)
        reached: Result[None, Error] = checked.bind(  # pyright: ignore[reportUnknownMemberType]
            lambda _: _check_reachability(cover_report, c_program)
        )
        return IOResult.from_result(reached).map(  # pyright: ignore[reportUnknownMemberType]
            lambda _: CbmcVerificationReport(
                file_path, c_program, unwind, assertion_report, cover_report
            )
        )

    return write_file_contents(c_program, file_path).bind(  # pyright: ignore[reportUnknownMemberType]
        lambda _: _run_cbmc_in_parallel(
            _cbmc_args(file_name, unwind, False), file_dir
        ).bind(  # pyright: ignore[reportUnknownMemberType]
            lambda assertion_report: _run_cbmc(
                _cbmc_args(file_name, unwind, True), file_dir
            ).bind(lambda cover_report: verify(assertion_report, cover_report))  # pyright: ignore[reportUnknownMemberType]
        )
    )


def verify_with_cbmc(
    state: State,
    cwp: Cwp,
    bpmn: Bpmn,
    file_path: str = OUTPUT_FILE,
) -> IOResult[CbmcVerificationReport, Error]:
    builder = CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn)
    built: Result[tuple[str, int], Error] = builder.build().bind(  # pyright: ignore[reportUnknownMemberType]
        lambda c_program: builder.unwind().map(lambda unwind: (c_program, unwind))
    )
    if isinstance(built, Failure):
        return IOFailure(built.failure())
    c_program, unwind = built.unwrap()
    return _run_cbmc_on_file(c_program, file_path, unwind)
