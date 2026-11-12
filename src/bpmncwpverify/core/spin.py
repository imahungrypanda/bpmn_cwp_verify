import os
import re
import subprocess

from returns.io import IOFailure, IOResult, IOSuccess, impure_safe
from returns.pipeline import flow
from returns.pointfree import bind_result
from returns.result import Failure, Result, Success

from bpmncwpverify.builder.promela_builder import PromelaBuilder
from bpmncwpverify.core.bpmn import Bpmn
from bpmncwpverify.core.counterexample import CounterExample
from bpmncwpverify.core.cwp import Cwp
from bpmncwpverify.core.error import (
    Error,
    NotInitializedError,
    SpinAssertionError,
    SpinCoverageError,
    SpinInvalidEndStateError,
    SpinSyntaxError,
    SubProcessRunError,
)
from bpmncwpverify.core.state import State
from bpmncwpverify.util.file import write_file_contents


def _process_spin_output(
    file_path: str, spin_report: str, bpmn: Bpmn
) -> IOResult[None, Error]:
    spin_parser: SpinOutputParser = SpinOutputParser()
    r: Result[None, Error] = flow(  # check this type one of these can return a string
        spin_parser.check_syntax_errors(file_path, spin_report, bpmn),
        bind_result(
            lambda _: spin_parser.check_invalid_end_state(file_path, spin_report, bpmn)
        ),  # pyright: ignore[reportUnknownLambdaType]
        bind_result(
            lambda _: spin_parser.check_coverage_errors(file_path, spin_report, bpmn)
        ),  # pyright: ignore[reportUnknownLambdaType]
        bind_result(
            lambda _: spin_parser.check_assertion_violation(
                file_path, spin_report, bpmn
            )
        ),  # pyright: ignore[reportUnknownLambdaType]
    )
    return IOResult.from_result(r)


def _run_spin(
    promela: str, file_path: str, cli_args: list[str], bpmn: Bpmn
) -> IOResult["SpinVerificationReport", Error]:
    file_name: str = os.path.basename(file_path)
    file_dir: str = os.path.dirname(file_path)

    def spin() -> IOResult[str, Error]:
        def spin_subprocess() -> str:
            return subprocess.run(
                ["spin"] + cli_args + [file_name],
                capture_output=True,
                text=True,
                cwd=file_dir,
            ).stdout

        return impure_safe(spin_subprocess)().alt(lambda _: SubProcessRunError("spin"))

    spin_result: IOResult[str, Error] = write_file_contents(promela, file_path).bind(  # pyright: ignore[reportUnknownMemberType]
        lambda _: spin()
    )

    result: IOResult[SpinVerificationReport, Error] = spin_result.bind(  # pyright: ignore[reportUnknownMemberType]
        lambda spin_report: _process_spin_output(file_path, spin_report, bpmn).bind(  # pyright: ignore[reportUnknownMemberType]
            lambda _: IOSuccess(
                SpinVerificationReport(file_path, promela, cli_args, spin_report)
            )
        )
    )

    return result


class SpinVerificationReport:
    __slots__ = ["file_path", "promela", "spin_cli_args", "spin_report"]

    def __init__(
        self, file_path: str, promela: str, spin_cli_args: list[str], spin_report: str
    ) -> None:
        self.file_path = file_path
        self.promela = promela
        self.spin_cli_args = spin_cli_args
        self.spin_report = spin_report


class SpinVerificationReportBuilder:
    __slots__ = ["file_path", "promela", "spin_cli_args"]

    def __init__(self) -> None:
        self.file_path: IOResult[str, Error] = IOFailure(
            NotInitializedError("SpinVerificationReportBuilder.filename")
        )
        self.promela: IOResult[str, Error] = IOFailure(
            NotInitializedError("SpinVerificationReportBuilder.promela")
        )
        self.spin_cli_args: IOResult[list[str], Error] = IOFailure(
            NotInitializedError("SpinVerificationReportBuilder.spin_cli_args")
        )

    def build(self, bpmn: Bpmn) -> IOResult[SpinVerificationReport, Error]:
        spin_result: IOResult[SpinVerificationReport, Error] = self.promela.bind(  # pyright: ignore[reportUnknownMemberType]
            lambda promela: self.file_path.bind(  # pyright: ignore[reportUnknownMemberType]
                lambda filename: self.spin_cli_args.bind(  # pyright: ignore[reportUnknownMemberType]
                    lambda cli_args: _run_spin(promela, filename, cli_args, bpmn)
                )
            )
        )
        return spin_result

    def with_promela(self, promela: str) -> "SpinVerificationReportBuilder":
        self.promela = IOSuccess(promela)
        return self

    def with_file_name(self, filename: str) -> "SpinVerificationReportBuilder":
        self.file_path = IOSuccess(filename)
        return self

    def with_spin_cli_args(
        self, spin_cli_args: list[str]
    ) -> "SpinVerificationReportBuilder":
        self.spin_cli_args = IOSuccess(spin_cli_args)
        return self


class SpinOutputParser:
    def _get_re_matches(self, regex: str, spin_msg: str) -> list[dict[str, str]]:
        r = re.compile(regex)

        return [
            {k: re.sub(r"\s+", " ", v).strip() for k, v in t.groupdict().items()}
            for t in r.finditer(spin_msg)
        ]

    def check_invalid_end_state(
        self, file_path: str, spin_msg: str, bpmn: Bpmn
    ) -> Result[None, Error]:
        errors = self._get_re_matches(r"invalid end state \((?P<info>.*)\)", spin_msg)

        counter_example = CounterExample.generate_counterexample(
            file_path, SpinInvalidEndStateError, bpmn
        )

        return (
            Failure(SpinInvalidEndStateError(counter_example.to_json(), errors))
            if errors
            else Success(None)
        )

    def check_assertion_violation(
        self, file_path: str, spin_msg: str, bpmn: Bpmn
    ) -> Result[None, Error]:
        errors = self._get_re_matches(
            r"assertion violated \(?(?P<assertion>[^\s)]*)\)? (?P<depth>.*)", spin_msg
        )

        counter_example = CounterExample.generate_counterexample(
            file_path, SpinAssertionError, bpmn
        )

        return (
            Failure(SpinAssertionError(counter_example.to_json(), errors))
            if errors
            else Success(None)
        )

    def check_syntax_errors(
        self, file_path: str, spin_msg: str, bpmn: Bpmn
    ) -> Result[str, Error]:
        errors = self._get_re_matches(
            r"spin: (?P<file_path>.*?):(?P<line_number>\d+),\sError: (?P<error_msg>.*)",
            spin_msg,
        )

        return Failure(SpinSyntaxError(errors)) if errors else Success(spin_msg)

    def check_coverage_errors(
        self, file_path: str, spin_msg: str, bpmn: Bpmn
    ) -> Result[None, Error]:
        # Regular expression to match proctype and init blocks, excluding never claims
        block_pattern = re.compile(
            r"unreached in (?:proctype (?P<proctype>\w+)|(?P<init>init))\n(?P<body>(?:\s+[^\n]+(?!\s+unreached))+)"
        )

        # Regular expression to match line information
        line_pattern = re.compile(
            r"(?P<file>[\w\.]+):(?P<line>\d+), state \d+, (?P<message>\"(?!.*Assert).*?\")"
        )

        # Find all relevant blocks (excluding never claims)
        matches = block_pattern.finditer(spin_msg)

        detailed_errors: list[dict[str, str]] = []

        for match in matches:
            proctype_name = (
                match.group("proctype") if match.group("proctype") else "init"
            )

            lines_block = match.group("body")  # Extract only the lines within the block

            for line_match in line_pattern.finditer(lines_block):
                file_name = line_match.group("file")
                line_number = line_match.group("line")
                message = line_match.group("message")

                detailed_errors.append(
                    {
                        "proctype": proctype_name,
                        "file": file_name,
                        "line": line_number,
                        "message": message,
                    }
                )

        return (
            Failure(SpinCoverageError(detailed_errors))
            if detailed_errors
            else Success(None)
        )


def verify_with_spin(
    state: State,
    cwp: Cwp,
    bpmn: Bpmn,
) -> IOResult[SpinVerificationReport, Error]:
    promela_result: Result[str, Error] = (
        PromelaBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn).build()
    )
    OUTPUT_FILE = "/tmp/verification.pml"

    spin_verification_report_builder: SpinVerificationReportBuilder = (
        SpinVerificationReportBuilder()
    )
    result = IOResult.from_result(promela_result).bind(  # pyright: ignore[reportUnknownMemberType]
        lambda promela: spin_verification_report_builder.with_file_name(OUTPUT_FILE)
        .with_promela(promela)
        .with_spin_cli_args(["-run", "-noclaim"])
        .build(bpmn)
    )
    return result
