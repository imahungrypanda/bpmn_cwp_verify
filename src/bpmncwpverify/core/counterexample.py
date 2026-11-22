import json
import subprocess

from bpmncwpverify.core.bpmn import Bpmn
from bpmncwpverify.core.error import Error
from bpmncwpverify.util.stringmanager import NL_SINGLE, StringManager


class ErrorTrace:
    """
    Class to represent an error trace.
    """

    __slots__ = ["id", "changed_vars", "cur_cwp_state", "related_variables"]

    def __init__(self, id: str, changed_vars: list[str], cur_cwp_state: str):
        self.id = id
        self.changed_vars = changed_vars
        self.cur_cwp_state = cur_cwp_state


class CounterExample:
    """
    Class to represent a counterexample.
    """

    __slots__ = ["trace_steps", "error", "issue", "vars"]

    def __init__(
        self,
        trace_steps: list[ErrorTrace],
        error: type["Error"],
        issue: str = "",
        vars: list[str] = [],
    ):
        self.trace_steps = trace_steps
        self.error = error.__name__
        self.issue = issue
        self.vars = vars

    def to_json(self) -> str:
        """
        Convert the counterexample to a JSON-compatible dictionary.
        """
        format = {
            "error": str(self.error),
            "issue": self.issue,
            "init variables": self.vars,
            "trace_steps": [
                {
                    "id": step.id,
                    "changed_vars": step.changed_vars,
                    "cur_cwp_state": step.cur_cwp_state,
                }
                for step in self.trace_steps
            ],
        }
        return json.dumps(format, indent=4)

    @staticmethod
    def generate_counterexample(
        file_path: str, error: type["Error"], bpmn: Bpmn
    ) -> "CounterExample":
        """
        Generate a counterexample from the given file path and error.
        """
        spin_trace_string = subprocess.run(
            ["spin", "-t", file_path], capture_output=True, text=True
        ).stdout
        filtered_str = CounterExample.filter_spin_trace(spin_trace_string)
        vars = CounterExample.extract_init_variables(filtered_str)
        counter_steps, issue = CounterExample.extract_steps_v_two(filtered_str, bpmn)

        return CounterExample(counter_steps, error, issue, vars)

    @staticmethod
    def filter_spin_trace(spin_trace_string: str) -> str:
        """
        Filter the spin trace string and return a string.
        """
        lines = spin_trace_string.splitlines()
        filtered_str = StringManager()
        for line in lines:
            if "spin:" in line:
                filtered_str.write_str(line.split("spin:")[0])
                break
            else:
                filtered_str.write_str(line, NL_SINGLE)
        return str(filtered_str)

    @staticmethod
    def extract_init_variables(filtered_str: str) -> list[str]:
        lines = filtered_str.splitlines()
        vars: list[str] = []

        for line in lines:
            if "ID:" in line or not line:
                break
            else:
                vars.append(line.strip())

        return vars

    @staticmethod
    def extract_steps_v_two(
        filtered_str: str, bpmn: Bpmn
    ) -> tuple[list[ErrorTrace], str]:
        lines = filtered_str.splitlines()
        line_index = 0
        steps: list[ErrorTrace] = []
        id = ""
        changed_variables: list[str] = []
        state = ""
        issue = ""

        while line_index < len(lines):
            if "ID: " in lines[line_index]:
                id = lines[line_index].split(":", 1)[1].strip()

                if id in bpmn.processes:
                    id = bpmn.processes[id].name
                elif id in bpmn.id_to_element:
                    id = bpmn.id_to_element[id].name

                state = ""
                line_index += 1

            elif "Changed Vars:" in lines[line_index]:
                changed_variables = []
                line_index += 1
                while len(lines) != line_index and ":" not in lines[line_index]:
                    varaiable = lines[line_index].strip()
                    changed_variables.append(varaiable)
                    line_index += 1

            elif "Current state:" in lines[line_index]:
                state = lines[line_index].split(":", 1)[1].strip()
                line_index += 1

            else:
                if "Assert:" in lines[line_index]:
                    issue = lines[line_index].strip()
                line_index += 1

            if line_index == len(lines) or "ID: " in lines[line_index] and id != "":
                steps.append(ErrorTrace(id, changed_variables, state))

        return steps, issue
