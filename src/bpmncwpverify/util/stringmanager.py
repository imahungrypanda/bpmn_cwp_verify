from enum import Enum
from typing import Union

NL_NONE = 0
NL_SINGLE = 1
NL_DOUBLE = 2


class IndentAction(Enum):
    NIL = 0
    INC = 1
    DEC = 2


class StringManager:
    __slots__ = ["contents", "indent"]

    def __init__(self) -> None:
        self.contents: list[str] = []
        self.indent = 0

    def _tab(self) -> str:
        """return string contianing 'self.indent' tabs"""
        return "\t" * self.indent

    def _newline(self, nl: int) -> str:
        """Return string containing 'nl' new lines."""
        return "\n" * nl

    def _inc_indent(self) -> None:
        self.indent += 1

    def _dec_indent(self) -> None:
        assert self.indent > 0
        self.indent -= 1

    def write_str(
        self,
        new_str: Union[str, "StringManager"],
        nl: int = NL_NONE,
        indent_action: IndentAction = IndentAction.NIL,
    ) -> None:
        """
        Appends a string or the contents of a StringManager object to the internal contents list
        with specified newline and indentation behavior.
        """
        # Validate input for StringManager instance usage
        if isinstance(new_str, StringManager):
            if nl != NL_NONE or indent_action != IndentAction.NIL:
                raise ValueError(
                    "When passing a StringManager, nl must be NL_NONE and indent_action must be IndentAction.NIL"
                )

        if indent_action == IndentAction.DEC:
            self._dec_indent()

        def needs_tab(idx: int, items: list[str]) -> bool:
            """Helper function to determine if tabulation is necessary."""
            # Check if it's the first item and if the last content line ends with a newline
            if idx == 0:
                return bool(self.contents and self.contents[-1].endswith("\n"))
            # Check the previous item for a newline
            return items[idx - 1].endswith("\n")

        # Normalize the input into a list for consistent handling
        items = [new_str] if isinstance(new_str, str) else new_str.contents

        for idx, item in enumerate(items):
            tab_required = needs_tab(idx, items)
            newline_suffix = self._newline(nl) if isinstance(new_str, str) else ""
            self.contents.append(
                f"{self._tab() if tab_required else ''}{item}{newline_suffix}"
            )

        if indent_action == IndentAction.INC:
            self._inc_indent()

    def __repr__(self) -> str:
        return "".join(self.contents)
