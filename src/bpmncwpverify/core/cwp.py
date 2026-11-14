import html
import re
from xml.etree.ElementTree import Element

from bs4 import BeautifulSoup


class Cwp:
    __slots__ = ["states", "edges", "start_state", "end_states"]

    def __init__(self) -> None:
        self.states: dict[str, CwpState] = {}
        self.edges: dict[str, CwpEdge] = {}
        self.start_state: CwpState
        self.end_states: list[CwpState] = []

    def accept(self, visitor: "CwpVisitor") -> None:
        result = visitor.visit_cwp(self)
        if result:
            self.start_state.accept(visitor)
        visitor.end_visit_cwp(self)


class CwpState:
    __slots__ = ["id", "name", "out_edges", "in_edges", "init_state"]

    def __init__(self, id: str, name: str) -> None:
        self.id = id
        self.name = name
        self.out_edges: list[CwpEdge] = []
        self.in_edges: list[CwpEdge] = []
        self.init_state: bool = False

    def accept(self, visitor: "CwpVisitor") -> None:
        result = visitor.visit_state(self)
        if result:
            for edge in self.out_edges:
                edge.accept(visitor)
        visitor.end_visit_state(self)

    @staticmethod
    def from_xml(element: Element) -> "CwpState":
        id = element.get("id")
        name = element.get("value")
        if id is None:
            raise Exception("id not in cwp state")
        if name is None:
            name = id
        name = re.sub("[?,+=/]", "", name)
        name = re.sub("-", " ", name)
        name = re.sub(r"\s+", "_", name)
        name = re.sub("</?div>", "", name).strip()
        return CwpState(id, name)


class CwpEdge:
    __slots__ = ["id", "name", "expression", "parent_id", "source", "dest", "is_leaf"]

    def __init__(self, id: str, name: str) -> None:
        self.id = id
        self.name = name
        self.expression: str = (
            ""  # TODO: expression needs to always be on an edge and cannot be empty
        )
        self.parent_id: str

        self.source: CwpState | None = None
        self.dest: CwpState
        self.is_leaf = False

    def set_source(self, state: CwpState) -> None:
        self.source = state

    def set_dest(self, state: CwpState) -> None:
        self.dest = state

    def accept(self, visitor: "CwpVisitor") -> None:
        if visitor.visit_edge(self) and not self.is_leaf:
            self.dest.accept(visitor)
        visitor.end_visit_edge(self)

    @staticmethod
    def has_html(expr: str) -> bool:
        HTML_HINTS = ("<br", "<span", "<div", "<font", "</")
        HTML_TAG_RE = re.compile(r"<\s*/?\s*[a-zA-Z][a-zA-Z0-9]*\b[^>]*>")

        if any(h in expr for h in HTML_HINTS):
            return True

        return bool(HTML_TAG_RE.search(expr))

    @staticmethod
    def deep_decode(expr: str) -> str:
        prev = expr

        for _ in range(5):
            curr = html.unescape(prev)

            if curr == prev:
                break
            prev = curr

        return prev

    @staticmethod
    def expression_reconstructor(s: list[str]) -> str:
        OPS = ("&&", "||")
        CONDITIONALS = ("==", "!=", "<=", "=<", "<", ">", ">=", "=>")
        ALL = OPS + CONDITIONALS
        prev_operation = ""
        i = 1

        while i != len(s):
            if i == len(s) - 1:
                break
            elif s[i] in OPS:
                prev_operation = s[i]
            elif s[i - 1] not in ALL and s[i] not in ALL:
                s.insert(i, prev_operation)
                i += 1
            i += 1

        return " ".join(s)

    @staticmethod
    def cleanup_expression(expression: str) -> str:
        decoded = CwpEdge.deep_decode(expression)
        decoded = re.sub(
            r"\s*(&&|\|\|)\s*", r" \1 ", decoded
        )  # adds spaces around logical operators for BeautifulSoup and expression_reconstructor

        if CwpEdge.has_html(decoded):
            soup = BeautifulSoup(decoded, "html.parser").get_text(" ", strip=True)
            decoded = CwpEdge.expression_reconstructor(soup.split())

        decoded = re.sub(
            r"\s*(&&|\|\||==|!=|>=|<=|=|<|>)\s*", r" \1 ", decoded
        )  # adds spaces between everything for standardization
        decoded = re.sub(
            r"\s+", " ", decoded
        ).strip()  # strips all extra spaces and leading/ending whitespace if any

        return decoded

    @staticmethod
    def from_xml(element: Element, name: str) -> "CwpEdge":
        id = element.get("id")
        if id is None:
            raise Exception("No ID for edge or no targetRef")
        return CwpEdge(id, name)


class CwpVisitor:
    def visit_state(self, state: CwpState) -> bool:
        return True

    def end_visit_state(self, state: CwpState) -> None:
        pass

    def visit_edge(self, edge: CwpEdge) -> bool:
        return True

    def end_visit_edge(self, edge: CwpEdge) -> None:
        pass

    def visit_cwp(self, model: Cwp) -> bool:
        return True

    def end_visit_cwp(self, model: Cwp) -> None:
        pass
