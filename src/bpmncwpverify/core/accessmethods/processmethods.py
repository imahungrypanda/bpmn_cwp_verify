from xml.etree.ElementTree import Element

from returns.functions import not_
from returns.pipeline import is_successful
from returns.result import Failure, Result

from bpmncwpverify.builder.process_builder import ProcessBuilder
from bpmncwpverify.core.bpmn import (
    BPMN_XML_NAMESPACE,
    Node,
    Process,
    SequenceFlow,
    get_element_type,
)
from bpmncwpverify.core.error import Error
from bpmncwpverify.core.state import State


def get_process_name(id: str, parts: list[Element]) -> str:
    for part in parts:
        if id == part.attrib.get("processRef"):
            return part.attrib.get("name", id)

    return id


def from_xml(
    element: Element, participants: list[Element], state: State
) -> Result["Process", Error]:
    id = element.attrib.get("id")
    if not id:
        raise Exception("Id cannot be None")

    name: str = get_process_name(id, participants)

    builder = ProcessBuilder(id, name, state)

    for sub_element in element:
        tag = sub_element.tag.partition("}")[2]

        result = get_element_type(tag)
        if not_(is_successful)(result):
            return Failure(result.failure())
        element_type: type[SequenceFlow] | type[Node] = result.unwrap()

        class_object = element_type.from_xml(sub_element)
        builder = builder.with_element(class_object)

    for seq_flow in element.findall("bpmn:sequenceFlow", BPMN_XML_NAMESPACE):
        result_builder: Result[ProcessBuilder, Error] = builder.with_process_flow(
            seq_flow.attrib["id"],
            seq_flow.attrib["sourceRef"],
            seq_flow.attrib["targetRef"],
            seq_flow.attrib.get("name", ""),
        )
        if is_successful(result_builder):
            builder = result_builder.unwrap()
        else:
            return Failure(result_builder.failure())

    builder = builder.with_boundary_events()

    builder = builder.with_boundary_events()

    return builder.build()
