# TODO: create a "match" function on Failure(Error) and create standard error messaging.
import builtins
import typing
from xml.etree.ElementTree import Element

import requests
from returns.maybe import Maybe, Nothing


class Error:
    def __init__(self) -> None:
        pass


class BpmnNoElementNameError(Error):
    __slots__ = ["ids"]

    def __init__(self, ids: list[str]) -> None:
        super().__init__()
        self.ids = ids


class BpmnNoSwimLaneNameError(Error):
    __slots__ = ["ids"]

    def __init__(self, ids: list[str]) -> None:
        super().__init__()
        self.ids = ids


class BpmnFlowIncomingError(Error):
    __slots__ = ["node_id"]

    def __init__(self, node_id: str) -> None:
        super().__init__()
        self.node_id = node_id


class BpmnFlowNoIdError(Error):
    __slots__ = ["element"]

    def __init__(self, element: Element) -> None:
        super().__init__()
        self.element = element


class BpmnFlowOutgoingError(Error):
    __slots__ = ["node_id"]

    def __init__(self, node_id: str) -> None:
        super().__init__()
        self.node_id = node_id


class BpmnFlowStartEventError(Error):
    __slots__ = ["node_id"]

    def __init__(self, node_id: str) -> None:
        super().__init__()
        self.node_id = node_id


class BpmnFlowTypeError(Error):
    __slots__ = ["flow_id"]

    def __init__(self, flow_id: str) -> None:
        super().__init__()
        self.flow_id = flow_id


class BpmnGraphConnError(Error):
    def __init__(self) -> None:
        super().__init__()


class BpmnInvalidIdError(Error):
    __slots__ = ["bpmn_id"]

    def __init__(self, bpmn_id: str) -> None:
        super().__init__()
        self.bpmn_id = bpmn_id


class BpmnMissingEventsError(Error):
    __slots__ = ["start_events", "end_events"]

    def __init__(self, start_events: int, end_events: int) -> None:
        super().__init__()
        self.start_events = start_events
        self.end_events = end_events


class BpmnMsgEndEventError(Error):
    __slots__ = ["event_id"]

    def __init__(self, event_id: str) -> None:
        super().__init__()
        self.event_id = event_id


class BpmnMsgFlowSamePoolError(Error):
    __slots__ = ["msg_id"]

    def __init__(self, msg_id: str) -> None:
        super().__init__()
        self.msg_id = msg_id


class BpmnMsgGatewayError(Error):
    __slots__ = ["gateway_type", "gateway_id"]

    def __init__(self, gateway_type: str, gateway_id: str) -> None:
        super().__init__()
        self.gateway_type = gateway_type
        self.gateway_id = gateway_id


class BpmnMsgMissingRefError(Error):
    __slots__ = ["msg_id"]

    def __init__(self, msg_id: str) -> None:
        super().__init__()
        self.msg_id = msg_id


class BpmnMsgNodeTypeError(Error):
    __slots__ = ["msg_id"]

    def __init__(self, msg_id: str) -> None:
        super().__init__()
        self.msg_id = msg_id


class BpmnMsgSrcError(Error):
    __slots__ = ["obj_type", "node_id"]

    def __init__(self, obj_type: str, node_id: str) -> None:
        super().__init__()
        self.obj_type = obj_type
        self.node_id = node_id


class BpmnMsgStartEventError(Error):
    __slots__ = ["node_id"]

    def __init__(self, node_id: str) -> None:
        super().__init__()
        self.node_id = node_id


class BpmnMsgTargetError(Error):
    __slots__ = ["obj_type", "node_id"]

    def __init__(self, obj_type: str, node_id: str) -> None:
        super().__init__()
        self.obj_type = obj_type
        self.node_id = node_id


class BpmnNodeTypeError(Error):
    __slots__ = ["flow_id"]

    def __init__(self, flow_id: str) -> None:
        super().__init__()
        self.flow_id = flow_id


class BpmnSeqFlowEndEventError(Error):
    __slots__ = ["event_id"]

    def __init__(self, event_id: str) -> None:
        super().__init__()
        self.event_id = event_id


class BpmnSeqFlowNoExprError(Error):
    __slots__ = ["gateway_id", "out_flow_id"]

    def __init__(self, gateway_id: str, out_flow_id: str) -> None:
        super().__init__()
        self.gateway_id = gateway_id
        self.out_flow_id = out_flow_id


class BpmnStructureError(Error):
    __slots__ = ["node_id", "error_msg"]

    def __init__(self, node_id: str, error_msg: str) -> None:
        super().__init__()
        self.node_id = node_id
        self.error_msg = error_msg


class BpmnTaskFlowError(Error):
    __slots__ = ["task_id"]

    def __init__(self, task_id: str) -> None:
        super().__init__()
        self.task_id = task_id


class BpmnUnrecognizedElement(Error):
    __slots__ = ["element_name"]

    def __init__(self, element_name: str) -> None:
        super().__init__()
        self.element_name = element_name


class CwpEdgeNoParentExprError(Error):
    __slots__ = ["edge"]

    def __init__(self, edge: Element) -> None:
        super().__init__()
        self.edge = edge


class CwpEdgeNoStateError(Error):
    __slots__ = ["edge"]

    def __init__(self, edge: Element) -> None:
        super().__init__()
        self.edge = edge


class CwpUnsupportedElementError(Error):
    __slots__ = ["number_of_elements", "element"]

    def __init__(self, number_of_elements: int, element: str) -> None:
        super().__init__()
        self.number_of_elements = number_of_elements
        self.element = element


class CwpFileStructureError(Error):
    __slots__ = ["element"]

    def __init__(self, element: str) -> None:
        super().__init__()
        self.element = element


class CwpGraphConnError(Error):
    def __init__(self) -> None:
        super().__init__()


class CwpMultStartStateError(Error):
    __slots__ = ["start_states"]

    def __init__(self, start_states: list[str]) -> None:
        super().__init__()
        self.start_states = start_states


class CwpNoEndStatesError(Error):
    def __init__(self) -> None:
        super().__init__()


class CwpNoParentEdgeError(Error):
    __slots__ = ["parent_edge"]

    def __init__(self, parent_edge: str) -> None:
        super().__init__()
        self.parent_edge = parent_edge


class CwpNoStartStateError(Error):
    def __init__(self) -> None:
        super().__init__()


class ExpressionComputationCompatabilityError(Error):
    __slots__ = ["ltype", "rtype"]

    def __init__(self, ltype: str, rtype: str) -> None:
        super().__init__()
        self.ltype = ltype
        self.rtype = rtype

    def __eq__(self, other: typing.Any) -> bool:
        if isinstance(other, ExpressionComputationCompatabilityError):
            return self.ltype == other.ltype and self.rtype == other.rtype
        return False


class ExpressionNegatorError(Error):
    __slots__ = ["_type"]

    def __init__(self, type: str) -> None:
        super().__init__()
        self._type = type

    def __eq__(self, other: typing.Any) -> bool:
        if isinstance(other, ExpressionNegatorError):
            return self._type == other._type
        return False


class ExpressionParseError(Error):
    __slots__ = ["exception_str"]

    def __init__(self, exception_str: str):
        super().__init__()
        self.exception_str = exception_str


class ExpressionRelationCompatabilityError(Error):
    __slots__ = ["ltype", "rtype"]

    def __init__(self, ltype: str, rtype: str) -> None:
        super().__init__()
        self.ltype = ltype
        self.rtype = rtype

    def __eq__(self, other: typing.Any) -> bool:
        if isinstance(other, ExpressionComputationCompatabilityError):
            return self.ltype == other.ltype and self.rtype == other.rtype
        return False


class ExpressionRelationalNotError(Error):
    __slots__ = ["_type"]

    def __init__(self, type: str) -> None:
        super().__init__()
        self._type = type

    def __eq__(self, other: typing.Any) -> bool:
        if isinstance(other, ExpressionRelationalNotError):
            return self._type == other._type
        return False


class ExpressionUnrecognizedID(Error):
    __slots__ = ["_id"]

    def __init__(self, id: str) -> None:
        super().__init__()
        self._id = id

    def __eq__(self, other: typing.Any) -> bool:
        if isinstance(other, ExpressionUnrecognizedID):
            return self._id == other._id
        return False


class FileReadFileError(Error):
    __slots__ = ["msg"]

    def __init__(self, msg: str) -> None:
        super().__init__()
        self.msg = msg


class FileWriteFileError(Error):
    __slots__ = ["msg"]

    def __init__(self, msg: str):
        super().__init__()
        self.msg = msg


class FileXmlParseError(Error):
    __slots__ = ["msg"]

    def __init__(self, msg: str):
        super().__init__()
        self.msg = msg


class FlowExpressionError(Error):
    __slots__ = ["flow_id", "expression", "exception_str"]

    def __init__(self, flow_id: str, expression: str, exception_str: str):
        super().__init__()
        self.flow_id = flow_id
        self.expression = expression
        self.exception_str = exception_str


class HttpError(Error):
    __slots__ = ["status", "reason", "body"]

    def __init__(self, status: int, reason: str, body: str):
        super().__init__()
        self.status = status
        self.reason = reason
        self.body = body


class JsonDecodeError(Error):
    __slots__ = ["body"]

    def __init__(self, body: str):
        super().__init__()
        self.body = body


class LambdaVerificationError(Error):
    __slots__ = ["description"]

    def __init__(self, description: str):
        super().__init__()
        self.description = description


class MessageError(Error):
    __slots__ = ["node_id", "error_msg"]

    def __init__(self, node_id: str, error_msg: str) -> None:
        super().__init__()
        self.node_id = node_id
        self.error_msg = error_msg


class NotImplementedError(Error):
    __slots__ = ["function"]

    def __init__(self, function: str) -> None:
        super().__init__()
        self.function = function


class NotInitializedError(Error):
    __slots__ = ["var_name"]

    def __init__(self, var_name: str):
        super().__init__()
        self.var_name = var_name


class CounterExampleError(Error):
    __slots__ = ["counter_example"]

    def __init__(self, counter_example: str) -> None:
        super().__init__()
        self.counter_example = counter_example

    def get_counter_example(self) -> str:
        return self.counter_example


class RequestError(Error):
    __slots__ = ["err"]

    def __init__(self, err: requests.exceptions.RequestException) -> None:
        super().__init__()
        self.err = err


class SpinAssertionError(CounterExampleError):
    __slots__ = ["list_of_error_maps"]

    def __init__(
        self,
        counter_example: str,
        list_of_error_maps: list[dict[str, str]],
    ):
        super().__init__(counter_example)
        self.list_of_error_maps = list_of_error_maps
        self.counter_example = counter_example


class SpinCoverageError(Error):
    __slots__ = ["coverage_errors"]

    def __init__(self, coverage_errors: list[dict[str, str]]) -> None:
        self.coverage_errors = coverage_errors


class SpinInvalidEndStateError(CounterExampleError):
    __slots__ = ["list_of_error_maps"]

    def __init__(
        self,
        counter_example: str,
        list_of_error_maps: list[dict[str, str]],
    ):
        super().__init__(counter_example)
        self.list_of_error_maps = list_of_error_maps


class SpinSyntaxError(Error):
    __slots__ = ["list_of_error_maps"]

    def __init__(
        self,
        list_of_error_maps: list[dict[str, str]],
    ):
        self.list_of_error_maps = list_of_error_maps


class StateInitNotInValues(Error):
    __slots__ = ["id", "line", "column", "values"]

    def __init__(
        self, id: str, line: Maybe[int], column: Maybe[int], values: set[str]
    ) -> None:
        super().__init__()
        self.id = id
        self.line = line
        self.column = column
        self.values = values

    def __eq__(self, other: typing.Any) -> bool:
        if isinstance(other, StateInitNotInValues):
            return (
                self.id == other.id
                and self.line == other.line
                and self.column == other.column
                and self.values == other.values
            )
        return False


class StateMultipleDefinitionError(Error):
    __slots__ = ("id", "line", "column", "prev_line", "prev_column")

    def __init__(
        self,
        id: str,
        line: Maybe[int],
        column: Maybe[int],
        prev_line: Maybe[int],
        prev_column: Maybe[int],
    ) -> None:
        super().__init__()
        self.id = id
        self.line = line
        self.column = column
        self.prev_line = prev_line
        self.prev_column = prev_column

    def __eq__(self, other: typing.Any) -> bool:
        if isinstance(other, StateMultipleDefinitionError):
            return (
                self.id == other.id
                and self.line == other.line
                and self.column == other.column
                and self.prev_line == other.prev_line
                and self.prev_column == other.prev_column
            )
        return False


class StateSyntaxError(Error):
    __slots__ = "msg"

    def __init__(self, msg: str) -> None:
        self.msg = msg
        super().__init__()


class StateAntlrWalkerError(Error):
    __slots__ = "msg"

    def __init__(self, msg: str) -> None:
        self.msg = msg
        super().__init__()


class SubProcessRunError(Error):
    __slots__ = "process_name"

    def __init__(self, process_name: str) -> None:
        super().__init__()
        self.process_name = process_name


class TypingAssignCompatabilityError(Error):
    __slots__ = ["ltype", "rtype"]

    def __init__(self, ltype: str, rtype: str) -> None:
        super().__init__()
        self.ltype = ltype
        self.rtype = rtype

    def __eq__(self, other: typing.Any) -> bool:
        if isinstance(other, TypingAssignCompatabilityError):
            return self.ltype == other.ltype and self.rtype == other.rtype
        return False


class TypingNegateBoolError(Error):
    __slots__ = ["expr_type"]

    def __init__(self, expr_type: str) -> None:
        super().__init__()
        self.expr_type = expr_type


class TypingNoTypeError(Error):
    __slots__ = ["id"]

    def __init__(self, id: str) -> None:
        super().__init__()
        self.id = id

    def __eq__(self, other: typing.Any) -> bool:
        if isinstance(other, TypingNoTypeError):
            return self.id == other.id
        return False


class TypingNotNonBoolError(Error):
    __slots__ = ["expr_type"]

    def __init__(self, expr_type: str) -> None:
        super().__init__()
        self.expr_type = expr_type


def get_error_message(error: Error) -> str:
    match error:
        case BpmnNoElementNameError(ids=ids):
            return (
                f"Bpmn error: {ids} must have a name that is different from their ID."
            )
        case BpmnNoSwimLaneNameError(ids=ids):
            return f"Bpmn error: {ids} must have a swimlane with a name that is different from their ID"
        case BpmnFlowIncomingError(node_id=node_id):
            return f"Flow error: All flow objects other than start events, boundary events, and compensating activities must have an incoming sequence flow, if the process level includes any start or end events. node: {node_id}."
        case BpmnFlowNoIdError(element=element):
            return f"Flow error: Flow_id does not exist. Occurred at tree element with following attributes: {element.attrib}."
        case BpmnFlowOutgoingError(node_id=node_id):
            return f"Flow error: All flow objects other than end events and compensating activities must have an outgoing sequence flow, if the process level includes any start or end events. node: {node_id}"
        case BpmnFlowStartEventError(node_id=node_id):
            return f"Flow error: A start event cannot have an incoming sequence flow and cannot have an outgoing message flow. node: {node_id}"
        case BpmnFlowTypeError(flow_id=flow_id):
            return f"Flow error: Flow '{flow_id}' is not a sequence flow when it should be."
        case BpmnGraphConnError():
            return "Bpmn Process graph error: Process graph is not fully connected."
        case BpmnInvalidIdError(bpmn_id=bpmn_id):
            return f"Bpmn id error: the bpmn element with id:{bpmn_id} contains an unsupported character (probably white space)."
        case BpmnMissingEventsError(start_events=start_events, end_events=end_events):
            return f"Event error: Start events = {start_events}, End events = {end_events}. Missing required start or end events."
        case BpmnMsgEndEventError(event_id=event_id):
            return f"Message flow error: End events cannot have incoming messages. Event ID: {event_id}."
        case BpmnMsgFlowSamePoolError(msg_id=msg_id):
            return f"Message flow error: {msg_id} connects nodes in the same pool."
        case BpmnMsgGatewayError(gateway_type=gateway_type, gateway_id=gateway_id):
            return f"Gateway error: {gateway_type} gateways cannot have incoming or outgoing messages. Gateway ID: {gateway_id}."
        case BpmnMsgMissingRefError(msg_id=msg_id):
            return f"Message flow error: Source ref or target ref is missing for message '{msg_id}'."
        case BpmnMsgNodeTypeError(msg_id=msg_id):
            return f"Message flow error: 'From' node and 'To' node of message are not of type Node. Message flow id: {msg_id}."
        case BpmnMsgSrcError(obj_type=obj_type, node_id=node_id):
            return f"Message flow source error while visiting {obj_type}. A message flow can only come from specific sources. Node ID: {node_id}."
        case BpmnMsgStartEventError(node_id=node_id):
            return f"Message flow error: A start event with incoming message flow must have a Message trigger. node: {node_id}"
        case BpmnMsgTargetError(obj_type=obj_type, node_id=node_id):
            return f"Message flow target error while visiting {obj_type}. A message flow can only go to a Message start or intermediate event; Receive, User, or Service task; Subprocess; or black box pool. Node ID: {node_id}."
        case BpmnNodeTypeError(flow_id=flow_id):
            return f"Node type error: Source or target node of flow is not of type node. Flow details: {flow_id}."
        case BpmnSeqFlowEndEventError(event_id=event_id):
            return f"Sequence flow error: End event '{event_id}' cannot have outgoing sequence flows."
        case BpmnSeqFlowNoExprError(gateway_id=gateway_id, out_flow_id=out_flow_id):
            return f"Flow: `{out_flow_id}` does not have an expression. All flows coming out of gateways must have expressions. Gateway id: {gateway_id}"
        case BpmnStructureError(node_id=node_id, error_msg=error_msg):
            return f"BPMN ERROR at node: {node_id}. {error_msg}"
        case BpmnTaskFlowError(task_id=task_id):
            return f"Task flow error: Task '{task_id}' should have at least one incoming and one outgoing flow."
        case BpmnUnrecognizedElement(element_name=element_name):
            return f"BPMN ERROR: Unrecognized bpmn element type in workflow: {element_name}"
        case CwpEdgeNoParentExprError(edge=edge):
            return f"CWP ERROR: Expression or parent node not found in edge. Edge details: {edge.attrib}."
        case CwpEdgeNoStateError(edge=edge):
            return f"CWP ERROR: Edge does not have a source or a target. Edge details: {edge.attrib}."
        case CwpUnsupportedElementError(
            number_of_elements=number_of_elements, element=element
        ):
            return f"CWP ERROR: {element} is/are not supported and there exists {number_of_elements}"
        case CwpFileStructureError(element=element):
            return f"A {element} element is missing from your cwp file."
        case CwpGraphConnError():
            return "CWP ERROR: Graph is not connected."
        case CwpMultStartStateError(start_states=start_states):
            return f"CWP ERROR: More than one start state found. Start state IDs: {start_states}."
        case CwpNoEndStatesError():
            return "CWP ERROR: No end states found."
        case CwpNoParentEdgeError(parent_edge=parent_edge):
            return f"CWP ERROR: Parent edge not found or no parent ID reference. Edge details: {parent_edge}."
        case CwpNoStartStateError():
            return "CWP ERROR: No start states found."
        case ExpressionComputationCompatabilityError(ltype=ltype, rtype=rtype):
            return f"EXPR ERROR: sometion of type '{rtype}' cannot be computed with something of type '{ltype}'"
        case ExpressionNegatorError(_type=_type):
            return f"EXPR ERROR: sometiong of type '{_type}' cannot be used with a mathmatical negator"
        case ExpressionParseError(exception_str=exception_str):
            return f"Error while parsing expression: {exception_str}"
        case ExpressionRelationCompatabilityError(ltype=ltype, rtype=rtype):
            return f"EXPR ERROR: sometion of type '{rtype}' cannot be related with something of type '{ltype}'"
        case ExpressionRelationalNotError(_type=_type):
            return f"EXPR ERROR: sometiong of type '{_type}' cannot be used with a relational not"
        case ExpressionUnrecognizedID(_id=_id):
            return f"EXPR ERROR: '{_id}' is not recognized as a literal or something stored in the symbol table"
        case FileReadFileError(msg=msg):
            return f"FILE ERROR: '{msg}'"
        case FileWriteFileError(msg=msg):
            return f"FILE ERROR: '{msg}'"
        case FileXmlParseError(msg=msg):
            return f"FILE ERROR: '{msg}'"
        case FlowExpressionError(
            flow_id=flow_id, expression=expression, exception_str=exception_str
        ):
            return f"Error occurred while parsing the expression on flow: '{flow_id}' with expression: '{expression}':\n\t'{exception_str}'"
        case HttpError(status=status, reason=reason):
            return f"ERROR: HTTP Error received as response: {status} {reason}"
        case JsonDecodeError(body=body):
            return f"ERROR: Failed to decode JSON of lamdba response: {body}"
        case LambdaVerificationError(description=description):
            return f"ERROR: Lambda encountered an error in the verification process: {description}"
        case MessageError(node_id=node_id, error_msg=error_msg):
            return f"Inter-process message error at node: {node_id}. {error_msg}"
        case NotImplementedError(function=function):
            return f"ERROR: not implemented '{function}'"
        case NotInitializedError(var_name=var_name):
            return f"ERROR: '{var_name}' is not initialized"
        case RequestError(err=err):
            return (
                f"ERROR: Unknown error occurred while sending request to lambda: {err}"
            )
        case SpinAssertionError(
            counter_example=counter_example, list_of_error_maps=list_of_error_maps
        ):
            errors: list[str] = []
            errors.append("Assertion Error:")
            errors.append(f"{len(list_of_error_maps)} error(s) occurred:")
            for idx, map in enumerate(list_of_error_maps):
                errors.append(
                    f"{idx + 1}: Assertion: {map['assertion']}, Depth info: {map['depth']}"
                )

            errors.append(counter_example)
            return "\n".join(errors)
        case SpinCoverageError(coverage_errors=coverage_errors):
            return "\n".join(
                [
                    f"Proctype: {error['proctype']}, File: {error['file']}, Line: {str(error['line'])}, Message: {error['message']}"
                    for error in coverage_errors
                ]
            )
        case SpinInvalidEndStateError(list_of_error_maps=list_of_error_maps):
            errors = []
            errors.append("Invalid end state")
            errors.append(f"{len(list_of_error_maps)} error(s) occurred:")
            for idx, map in enumerate(list_of_error_maps):
                errors.append(f"{idx + 1}: {map['info']}")
            return "\n".join(errors)
        case SpinSyntaxError(list_of_error_maps=list_of_error_maps):
            errors = []
            errors.append("Syntax Error in generated promela:")
            errors.append(f"{len(list_of_error_maps)} error(s) occurred:")
            for idx, map in enumerate(list_of_error_maps):
                errors.append(
                    f"{idx + 1}: On line {map['line_number']} in the file '{map['file_path']}': {map['error_msg']}"
                )
            return "\n".join(errors)
        case StateAntlrWalkerError(msg=msg):
            return f"STATE ERROR: {msg}"
        case StateInitNotInValues(id=id, line=line, column=column, values=values):
            location: str = " "
            if line != Nothing and column != Nothing:
                location = f" at line {line.unwrap()}:{column.unwrap()} "
            return f"STATE ERROR: init value '{id}'{location}not in allowed values {sorted(values)}"
        case StateMultipleDefinitionError(
            id=id,
            line=line,
            column=column,
            prev_line=prev_line,
            prev_column=prev_column,
        ):
            location_first: str = ""
            if line != Nothing and column != Nothing:
                location_first = f" at line {line.unwrap()}:{column.unwrap()}"

            location_second: str = ""
            if prev_line != Nothing and prev_column != Nothing:
                location_second = f", previously defined at line {prev_line.unwrap()}:{prev_column.unwrap()}"

            return f"STATE ERROR: multiple definition of '{id}'{location_first}{location_second}"
        case StateSyntaxError(msg=msg):
            return f"STATE SYNTAX ERROR: {msg}"
        case SubProcessRunError(process_name=process_name):
            return f"ERROR: failed to run '{process_name}'"
        case TypingAssignCompatabilityError(ltype=ltype, rtype=rtype):
            return f"TYPING ERROR: something of type '{rtype}' cannot by assigned to something of type '{ltype}'"
        case TypingNoTypeError(id=id):
            return f"TYPING ERROR: literal '{id}' has an unknown type"

        case _:
            raise builtins.NotImplementedError
