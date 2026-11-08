from typing import cast
from xml.etree.ElementTree import Element

from returns.functions import not_
from returns.pipeline import is_successful
from returns.result import Result

from bpmncwpverify.builder.bpmn_builder import BpmnBuilder
from bpmncwpverify.core.accessmethods.processmethods import from_xml as process_from_xml
from bpmncwpverify.core.bpmn import (
    BPMN_XML_NAMESPACE,
    Bpmn,
    MessageFlow,
)
from bpmncwpverify.core.error import Error
from bpmncwpverify.core.state import State
from bpmncwpverify.visitors.bpmn_graph_visitor import GraphVizVisitor


def from_xml(root: Element, state: State) -> Result["Bpmn", Error]:
    ##############
    # Build and add processes
    ##############
    processes = root.findall("bpmn:process", BPMN_XML_NAMESPACE)
    collab = root.find("bpmn:collaboration", BPMN_XML_NAMESPACE)

    if collab is not None:
        participants = collab.findall("bpmn:participant", BPMN_XML_NAMESPACE)
    else:
        participants = []

    bpmn_builder = BpmnBuilder()
    for process_element in processes:
        # This is for filtering out dummy processes that some tools add
        if process_element.attrib.get("processType", "Private") == "Public":
            continue

        process = process_from_xml(process_element, participants, state)
        if not_(is_successful)(process):
            return cast(Result[Bpmn, Error], process)
        bpmn_builder = bpmn_builder.with_process(process.unwrap())

    ##############
    # Build and add messages
    ##############
    if collab is not None:
        # TODO: write test for messages in the bpmn diagram
        bpmn_builder = bpmn_builder.with_process_elements()
        for msg_flow in collab.findall("bpmn:messageFlow", BPMN_XML_NAMESPACE):
            source_ref, target_ref = (
                msg_flow.get("sourceRef"),
                msg_flow.get("targetRef"),
            )

            message = MessageFlow.from_xml(msg_flow)

            assert source_ref and target_ref

            bpmn_builder = bpmn_builder.with_message(message, source_ref, target_ref)

    return bpmn_builder.build()


def generate_graph_viz(bpmn: Bpmn) -> None:
    for process in range(len(bpmn.processes)):
        graph_viz_visitor = GraphVizVisitor(process + 1)

        bpmn.accept(graph_viz_visitor)

        graph_viz_visitor.dot.render("graphs/bpmn_graph.gv", format="png")  # type: ignore[unused-ignore]
