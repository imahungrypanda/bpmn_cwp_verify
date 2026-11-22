from xml.etree.ElementTree import Element

from returns.result import Failure, Result

from bpmncwpverify.builder.cwp_builder import CwpBuilder
from bpmncwpverify.core.cwp import Cwp, CwpEdge, CwpState
from bpmncwpverify.core.error import (
    CwpEdgeNoParentExprError,
    CwpEdgeNoStateError,
    CwpFileStructureError,
    CwpUnsupportedElementError,
    Error,
)
from bpmncwpverify.core.expr import ExpressionListener
from bpmncwpverify.core.state import State
from bpmncwpverify.visitors.cwp_graph_visitor import CwpGraphVizVisitor


class CwpXmlParser:
    def _get_mx_cells(self, root: Element) -> list[Element]:
        if (diagram := root.find("diagram")) is None:
            raise Exception(CwpFileStructureError("diagram"))
        if (mx_graph_model := diagram.find("mxGraphModel")) is None:
            raise Exception(CwpFileStructureError("mxGraphModel"))
        if (mx_root := mx_graph_model.find("root")) is None:
            raise Exception(CwpFileStructureError("root"))
        if not (mx_cells := mx_root.findall("mxCell")):
            raise Exception(CwpFileStructureError("mxCell"))
        if object := mx_root.findall("object"):
            raise Exception(CwpUnsupportedElementError(len(object), "object"))
        return mx_cells

    def _get_all_items(self, mx_cells: list[Element]) -> list[Element]:
        return [itm for itm in mx_cells]

    def _get_edges(self, mx_cells: list[Element]) -> list[Element]:
        return [itm for itm in mx_cells if itm.get("edge")]

    def _get_states(self, mx_cells: list[Element]) -> list[Element]:
        return [itm for itm in mx_cells if itm.get("vertex")]

    def _add_states(self, builder: CwpBuilder, states: list[Element]) -> None:
        unsupported_shapes: int = 0
        for element in states:
            style = element.get("style")
            if style and "edgeLabel" not in style:
                if "rounded=1" not in style and "rounded=0" not in style:
                    unsupported_shapes += 1
                state = CwpState.from_xml(element)
                builder = builder.with_state(state)

        if unsupported_shapes != 0:
            raise Exception(
                CwpUnsupportedElementError(
                    unsupported_shapes, "different shapes other than rectangles"
                )
            )

    def _add_edges(self, builder: CwpBuilder, edges: list[Element]) -> None:
        for element in edges:
            source_ref = element.get("source")
            target_ref = element.get("target")
            if not target_ref or not source_ref:
                raise Exception(CwpEdgeNoStateError(element))
            edge = CwpEdge.from_xml(element, builder.gen_edge_name())

            builder = builder.with_edge(edge, source_ref, target_ref)

    def _add_incoming_edge_to_start_state(
        self, builder: CwpBuilder, state: State
    ) -> None:
        expr: list[str] = []
        for v in state.vars:
            expr.append(f"{v.id} == {v.init.value}")

        edge_expr = " && ".join(expr)

        edge = CwpEdge("Init_Edge", builder.gen_edge_name())
        edge.expression = edge_expr

        builder.find_start_state()
        builder = builder.with_start_edge(edge)

    def _check_expressions(
        self,
        builder: CwpBuilder,
        all_items: list[Element],
        expr_lstnr: ExpressionListener,
        state: State,
    ) -> None:
        for itm in all_items:
            style = itm.get(
                "style"
            )  # TODO: if edge does not have expression, then throw error
            if style and "edgeLabel" in style:
                parent = itm.get("parent")
                expression = itm.get("value")
                if not (parent and expression):
                    raise Exception(CwpEdgeNoParentExprError(itm))
                builder.check_expression(expr_lstnr, expression, parent, state)

    @staticmethod
    def from_xml(root: Element, state: State) -> Result["Cwp", Error]:
        builder = CwpBuilder()
        parser = CwpXmlParser()

        try:
            mx_cells = parser._get_mx_cells(root)
            all_items = parser._get_all_items(mx_cells)
            edges = parser._get_edges(mx_cells)
            states = parser._get_states(mx_cells)
            expr_lstnr = ExpressionListener(state)
            parser._add_states(builder, states)
            parser._add_edges(builder, edges)
            parser._add_incoming_edge_to_start_state(builder, state)
            parser._check_expressions(builder, all_items, expr_lstnr, state)
        except Exception as e:
            assert e.args, "Error does not have enough arguments"
            return Failure(e.args[0])

        result: Result[Cwp, Error] = builder.build()
        return result


def generate_graph_viz(cwp: Cwp) -> None:
    graph_viz_visitor = CwpGraphVizVisitor()

    cwp.accept(graph_viz_visitor)

    graph_viz_visitor.dot.render("graphs/cwp_graph.gv", format="png")  # type: ignore[unused-ignore]
