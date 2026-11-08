# type: ignore
import pytest
from returns.functions import not_
from returns.pipeline import is_successful

from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.error import (
    CwpEdgeNoParentExprError,
    CwpEdgeNoStateError,
    CwpFileStructureError,
    CwpUnsupportedElementError,
)


class TestCwpXmlParser:
    def test_get_xml_cells_works(self, mocker):
        root = mocker.Mock()
        diagram = mocker.Mock()
        mx_graph_model = mocker.Mock()
        mx_root = mocker.Mock()
        mx_cells = mocker.Mock()
        root.find.return_value = diagram
        diagram.find.return_value = mx_graph_model
        mx_graph_model.find.return_value = mx_root
        mx_root.findall.side_effect = lambda x: mx_cells if x == "mxCell" else {}
        CwpXmlParser._get_mx_cells(mocker.Mock(), root)
        # should not throw error

    def test_get_xml_cells_fail(self, mocker):
        root = mocker.Mock()
        diagram = mocker.Mock()
        mx_graph_model = mocker.Mock()
        mx_root = mocker.Mock()
        mx_cells = mocker.Mock()
        object = [mocker.Mock()]
        root.find.return_value = diagram

        diagram.find.return_value = mx_graph_model
        mx_graph_model.find.return_value = mx_root
        mx_root.findall.side_effect = lambda x: mx_cells if x == "mxCell" else object

        with pytest.raises(Exception) as exc_info:
            CwpXmlParser._get_mx_cells(mocker.Mock(), root)

        assert isinstance(exc_info.value.args[0], CwpUnsupportedElementError)
        assert exc_info.value.args[0].element == "object"

    def test_get_xml_cells_no_diagram(self, mocker):
        root = mocker.Mock()
        root.find.return_value = None

        with pytest.raises(Exception) as exc_info:
            CwpXmlParser._get_mx_cells(mocker.Mock(), root)

        assert isinstance(exc_info.value.args[0], CwpFileStructureError)
        assert exc_info.value.args[0].element == "diagram"

    def test_get_xml_cells_no_graph_model(self, mocker):
        root = mocker.Mock()
        diagram = mocker.Mock()
        root.find.return_value = diagram
        diagram.find.return_value = None

        with pytest.raises(Exception) as exc_info:
            CwpXmlParser._get_mx_cells(mocker.Mock(), root)

        assert isinstance(exc_info.value.args[0], CwpFileStructureError)
        assert exc_info.value.args[0].element == "mxGraphModel"

    def test_get_xml_cells_no_mx_root(self, mocker):
        root = mocker.Mock()
        diagram = mocker.Mock()
        mx_model = mocker.Mock()
        root.find.return_value = diagram
        diagram.find.return_value = mx_model
        mx_model.find.return_value = None

        with pytest.raises(Exception) as exc_info:
            CwpXmlParser._get_mx_cells(mocker.Mock(), root)

        assert isinstance(exc_info.value.args[0], CwpFileStructureError)
        assert exc_info.value.args[0].element == "root"

    def test_get_xml_cells_no_mx_cells(self, mocker):
        root = mocker.Mock()
        diagram = mocker.Mock()
        mx_model = mocker.Mock()
        mx_root = mocker.Mock()
        root.find.return_value = diagram
        diagram.find.return_value = mx_model
        mx_model.find.return_value = mx_root
        mx_root.findall.return_value = None

        with pytest.raises(Exception) as exc_info:
            CwpXmlParser._get_mx_cells(mocker.Mock(), root)

        assert isinstance(exc_info.value.args[0], CwpFileStructureError)
        assert exc_info.value.args[0].element == "mxCell"

    def test_add_states(self, mocker):
        states = []
        for _ in range(3):
            mock_state = mocker.Mock()
            mock_state.get.return_value = "rounded=1;test"
            states.append(mock_state)

        mock_builder = mocker.Mock()
        mock_builder.with_state.return_value = mock_builder
        mock_from_xml = mocker.patch(
            "bpmncwpverify.core.accessmethods.cwpmethods.CwpState.from_xml",
            return_value="test_state",
        )

        CwpXmlParser._add_states(mocker.Mock(), mock_builder, states)
        calls = [mocker.call("test_state") for _ in range(3)]
        mock_builder.with_state.assert_has_calls(calls)
        mock_from_xml.assert_has_calls([mocker.call(state) for state in states])

    def test_add_states_not_rectangles(self, mocker):
        states = []
        for _ in range(3):
            mock_state = mocker.Mock()
            mock_state.get.return_value = "ellipse;test"
            states.append(mock_state)

        mock_builder = mocker.Mock()
        mock_builder.with_state.return_value = mock_builder

        with pytest.raises(Exception) as exc_info:
            CwpXmlParser._add_states(mocker.Mock(), mock_builder, states)

        assert isinstance(exc_info.value.args[0], CwpUnsupportedElementError)
        assert (
            exc_info.value.args[0].element == "different shapes other than rectangles"
        )
        assert exc_info.value.args[0].number_of_elements == 3

    def test_add_edges_no_src_or_target(self, mocker):
        mock_edge = mocker.Mock()
        dyct = {"source": None, "target": "something"}
        mock_edge.get.side_effect = lambda x: dyct.get(x)
        edges = [mock_edge]
        with pytest.raises(Exception) as exc_info:
            CwpXmlParser._add_edges(mocker.Mock(), mocker.Mock(), edges)

        assert isinstance(exc_info.value.args[0], CwpEdgeNoStateError)
        assert exc_info.value.args[0].edge == mock_edge

        dyct["source"] = "something"
        dyct["target"] = None

        with pytest.raises(Exception) as exc_info:
            CwpXmlParser._add_edges(mocker.Mock(), mocker.Mock(), edges)

        assert isinstance(exc_info.value.args[0], CwpEdgeNoStateError)
        assert exc_info.value.args[0].edge == mock_edge

    def test_add_edges(self, mocker):
        mock_src = "src"
        mock_edge = mocker.Mock()
        mock_target = "target"
        mock_edge.get.side_effect = lambda x: {
            "source": mock_src,
            "target": mock_target,
        }.get(x)
        edges = [mock_edge]

        mock_builder = mocker.Mock()
        mock_builder.gen_edge_name.return_value = "A"
        mock_builder.with_state.return_value = mock_builder
        mock_from_xml = mocker.patch(
            "bpmncwpverify.core.accessmethods.cwpmethods.CwpEdge.from_xml",
            return_value="test_edge",
        )
        CwpXmlParser._add_edges(mocker.Mock(), mock_builder, edges)

        calls = [mocker.call("test_edge", "src", "target")]
        mock_builder.with_edge.assert_has_calls(calls)
        mock_from_xml.assert_has_calls([mocker.call(edge, "A") for edge in edges])

    def test_check_expressions(self, mocker):
        mock_builder = mocker.Mock()
        mock_expr_lstnr = mocker.Mock()
        mock_state = mocker.Mock()
        element = mocker.Mock()
        element.get.side_effect = lambda x: {
            "style": "edgeLabel",
            "parent": True,
            "value": True,
        }.get(x)

        mock_all_items = [element]
        CwpXmlParser._check_expressions(
            mocker.Mock(), mock_builder, mock_all_items, mock_expr_lstnr, mock_state
        )

        mock_builder.check_expression.assert_called_once()

    def test_check_expressions_with_no_parent(self, mocker):
        mock_builder = mocker.Mock()
        mock_expr_lstnr = mocker.Mock()
        mock_state = mocker.Mock()
        element = mocker.Mock()
        element.get.side_effect = lambda x: {"style": "edgeLabel"}.get(x)

        mock_all_items = [element]
        with pytest.raises(Exception) as exc_info:
            CwpXmlParser._check_expressions(
                mocker.Mock(), mock_builder, mock_all_items, mock_expr_lstnr, mock_state
            )

        assert isinstance(exc_info.value.args[0], CwpEdgeNoParentExprError)

        assert exc_info.value.args[0].edge == element

    def test_from_xml_no_error(self, mocker):
        mock_parser_object = mocker.Mock()
        mock_builder_object = mocker.Mock()
        mock_builder_class = mocker.patch(
            "bpmncwpverify.core.accessmethods.cwpmethods.CwpBuilder",
            return_value=mock_builder_object,
        )
        mock_parser_class = mocker.patch(
            "bpmncwpverify.core.accessmethods.cwpmethods.CwpXmlParser",
            return_value=mock_parser_object,
        )
        mock_expr_lstnr_class = mocker.patch(
            "bpmncwpverify.core.accessmethods.cwpmethods.ExpressionListener",
            return_value="expr_listener",
        )

        mock_parser_object._get_mx_cells.return_value = "mx_cells"
        mock_parser_object._get_all_items.return_value = "all_items"
        mock_parser_object._get_edges.return_value = "edges"
        mock_parser_object._get_states.return_value = "states"

        mock_root = mocker.Mock()
        mock_state = mocker.Mock()

        CwpXmlParser.from_xml(mock_root, mock_state)

        mock_builder_class.assert_called_once()
        mock_parser_class.assert_called_once()
        mock_parser_object._get_mx_cells.assert_called_once_with(mock_root)
        mock_parser_object._get_all_items.assert_called_once_with("mx_cells")
        mock_parser_object._get_edges.assert_called_once_with("mx_cells")
        mock_parser_object._get_states.assert_called_once_with("mx_cells")
        mock_expr_lstnr_class.assert_called_once_with(mock_state)
        mock_parser_object._add_states.assert_called_once_with(
            mock_builder_object, "states"
        )
        mock_parser_object._add_edges.assert_called_once_with(
            mock_builder_object, "edges"
        )

        mock_parser_object._check_expressions.assert_called_once_with(
            mock_builder_object, "all_items", "expr_listener", mock_state
        )

        mock_builder_object.build.assert_called_once()

    def test_from_xml_with_error(self, mocker):
        mock_parser_object = mocker.Mock()
        mocker.patch(
            "bpmncwpverify.core.accessmethods.cwpmethods.CwpXmlParser",
            return_value=mock_parser_object,
        )

        mock_parser_object._get_mx_cells.side_effect = AssertionError("TEST")

        mock_root = mocker.Mock()
        mock_state = mocker.Mock()

        result = CwpXmlParser.from_xml(mock_root, mock_state)
        assert not_(is_successful)(result)
        assert result.failure() == "TEST"
