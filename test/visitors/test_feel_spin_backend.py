from returns.io import IOSuccess
from returns.result import Success

from bpmncwpverify.cli import cli_verify
from bpmncwpverify.core.bpmn import ExclusiveGatewayNode, SequenceFlow, Task
from bpmncwpverify.core.cwp import CwpEdge, CwpState
from bpmncwpverify.core.feel import parse_behavior, parse_expression
from bpmncwpverify.visitors.bpmn_promela_visitor import Context, PromelaGenVisitor
from bpmncwpverify.visitors.cwp_graph_visitor import CwpGraphVizVisitor
from bpmncwpverify.visitors.cwp_promela_visitor import CwpPromelaVisitor
from bpmncwpverify.visitors.feel_to_promela_visitor import (
    behavior_text,
    condition_text,
)

FEEL_DIR = "test/resources/feel"


def _edge(text, dest):
    edge = CwpEdge("1", "e1")
    edge.expression = _expr(text)
    edge.dest = dest
    return edge


def _expr(text):
    return parse_expression(text).unwrap()


def test_condition_text_keeps_strings():
    assert condition_text("x > 5") == Success("x > 5")


def test_condition_text_translates_feel():
    assert condition_text(_expr("x > 5 and true")) == Success("((x > 5) && true)")


def test_behavior_text_translates_feel():
    behavior = parse_behavior("(x, [x], x + 1)").unwrap()
    assert behavior_text(behavior) == Success("x = (x + 1)")
    assert behavior_text("x = x + 1") == Success("x = x + 1")


def test_cwp_visitor_uses_feel_edges():
    end = CwpState("e", "end")
    end.in_edges.append(_edge("x > 5", end))
    visitor = CwpPromelaVisitor()
    assert "(x > 5)" in repr(visitor._build_mapping_function(end))
    assert visitor.errors == []


def test_cwp_visitor_reports_unsupported_edge():
    end = CwpState("e", "end")
    end.in_edges.append(_edge("x > 1.5", end))
    visitor = CwpPromelaVisitor()
    assert "#error" in repr(visitor._build_mapping_function(end))
    assert len(visitor.errors) == 1


def test_bpmn_visitor_task_behavior():
    task = Task("t", "task", parse_behavior("(x, [x], choose [1, 2])").unwrap())
    visitor = PromelaGenVisitor()
    task.accept(visitor)
    text = repr(visitor.behaviors)
    assert "x = 1" in text and "x = 2" in text and "updateState()" in text
    assert visitor.errors == []


def test_bpmn_visitor_flow_condition():
    gateway = ExclusiveGatewayNode("g", "gw")
    flow = SequenceFlow("f", "f")
    flow.target_node = Task("t", "task", "")
    flow.expression = _expr("not (x > 5)")
    gateway.out_flows.append(flow)
    visitor = PromelaGenVisitor()
    ctx = Context(gateway)
    ctx.has_option = True
    assert visitor._get_expressions(ctx) == ["(!(x > 5))"]


def test_graph_visitor_label_for_feel_edge():
    end = CwpState("e", "end")
    edge = _edge("x > 5", end)
    visitor = CwpGraphVizVisitor()
    visitor.visit_edge(edge)
    assert "(x > 5)" in visitor.dot.source


def test_feel_workflow_verifies_with_spin():
    result = cli_verify(
        f"{FEEL_DIR}/state.txt",
        f"{FEEL_DIR}/test_cwp.xml",
        f"{FEEL_DIR}/test_bpmn.bpmn",
    )
    assert isinstance(result, IOSuccess), result
    assert "errors: 0" in result.unwrap()._inner_value.spin_report
