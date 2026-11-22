from bpmncwpverify.core.bpmn import (
    Bpmn,
    BpmnVisitor,
    EndEvent,
    ExclusiveGatewayNode,
    Flow,
    IntermediateEvent,
    MessageFlow,
    Node,
    ParallelGatewayNode,
    Process,
    StartEvent,
    Task,
)
from bpmncwpverify.util.stringmanager import IndentAction, StringManager

##############
# Constants
##############
HELPER_FUNCS_STR = '#define hasToken(place) (place != 0)\n\ninline putToken(place) {\n\tif\n\t\t:: place != 1 -> place = 1\n\t\t:: else -> {\n\t\t\tprintf("Assert: Attempting to place token in already-occupied place\\n")\n\t\t\tassert false\n\t\t}\n\tfi\n}\n\n#define consumeToken(place) place = 0\n'
NL_NONE = 0
NL_SINGLE = 1
NL_DOUBLE = 2


##############


class Context:
    __slots__ = [
        "_element",
        "_is_parallel",
        "_behavior_model",
        "_has_option",
        "_behavior",
        "_end_event",
        "_boundary_events",
        "_boundary_event_consume_locations",
    ]

    def __init__(self, element: Node) -> None:
        self._element = element
        self._is_parallel = False
        self._has_option = False
        self._behavior_model = True
        self._behavior = ""
        self._end_event = False
        self._boundary_events: list[Task.BoundaryEvent] = []

    @property
    def has_option(self) -> bool:
        return self._has_option

    @has_option.setter
    def has_option(self, new_val: bool) -> None:
        assert isinstance(self._element, ExclusiveGatewayNode)
        self._has_option = new_val

    @property
    def behavior_model(self) -> bool:
        return self._behavior_model

    @behavior_model.setter
    def behavior_model(self, new_val: bool) -> None:
        self._behavior_model = new_val

    @property
    def is_parallel(self) -> bool:
        return self._is_parallel

    @is_parallel.setter
    def is_parallel(self, new_val: bool) -> None:
        assert isinstance(self._element, ParallelGatewayNode), (
            "is_parallel can only be set if element is of type ParallelGatewayNode"
        )
        self._is_parallel = new_val

    @property
    def behavior(self) -> str:
        return self._behavior

    @behavior.setter
    def behavior(self, new_val: str) -> None:
        assert isinstance(self._element, Task), (
            "only tasks can have a behavior associated with them."
        )
        self._behavior = new_val

    @property
    def end_event(self) -> bool:
        return self._end_event

    @end_event.setter
    def end_event(self, new_val: bool) -> None:
        assert isinstance(self._element, EndEvent), (
            "end_event can only be set if element is of type EndEvent"
        )
        self._end_event = new_val

    @property
    def boundary_events(self) -> list[Task.BoundaryEvent]:
        return self._boundary_events

    @boundary_events.setter
    def boundary_events(self, new_val: list[Task.BoundaryEvent]) -> None:
        assert isinstance(self._element, Task), (
            "Only allowed to set boundary_events on a task."
        )
        self._boundary_events = new_val

    @property
    def element(self) -> Node:
        return self._element


class TokenPositions:
    """
    This class is simply a way to separate out the sequence flows and the message
    flows so that when building the guard in the atomic block, we can make
    sure that the triggerable event has a token from one of its incoming sequence
    flows and one of its incoming message flows.
    """

    __slots__ = ["seq_flows", "msg_flows", "standalone"]

    def __init__(
        self,
        seq_flows: list[str] | None = None,
        msg_flows: list[str] | None = None,
        standalone: str = "",
    ) -> None:
        self.seq_flows = seq_flows if seq_flows is not None else []
        self.msg_flows = msg_flows if msg_flows is not None else []
        self.standalone = standalone

        # Ensure that either seq/msg flows are provided or a standalone position, but not both.
        if (self.seq_flows or self.msg_flows) and self.standalone:
            raise ValueError(
                "Cannot have both sequence/message flows and a standalone position."
            )
        if not ((self.seq_flows or self.msg_flows) or self.standalone):
            raise ValueError(
                "Either sequence/message flows or a standalone position must be provided."
            )

    def get_all_positions(self) -> list[str]:
        return (
            self.seq_flows + self.msg_flows
            if (self.seq_flows or self.msg_flows)
            else [self.standalone]
        )

    def get_in_process_positions(self) -> list[str]:
        if self.seq_flows:
            return self.seq_flows
        elif self.standalone:
            return [self.standalone]
        else:
            return []


class PromelaGenVisitor(BpmnVisitor):
    __slots__ = ["defs", "var_defs", "behaviors", "init_proc_contents", "promela"]

    def __init__(self) -> None:
        self.defs = StringManager()
        self.var_defs = StringManager()
        self.behaviors = StringManager()
        self.init_proc_contents = StringManager()
        self.promela = StringManager()

    def _generate_location_label(
        self, element: Node, flow_or_message: Flow | None = None
    ) -> str:
        """
        Should only be called from _get_consume_locations and _get_put_locations.
        Generates a unique label for a node, indicating the source of flow.
        If multiple flows lead into the node, the label specifies the source element
        (e.g., 'Node1_FROM_Start'). If the node is a Task, the label ends with '_END'.
        """
        if flow_or_message:
            return f"{element.id}_FROM_{flow_or_message.source_node.id}"
        return element.id

    def _get_consume_locations(self, element: Node) -> TokenPositions:
        """
        Returns a list of labels representing all incoming flows to a node.
        If there are no incoming flows, the node itself is returned as a label.
        Example: ['Node2_FROM_Start', 'Node2_FROM_Node1']
        """
        if not (element.in_flows or element.in_msgs):
            return TokenPositions(standalone=self._generate_location_label(element))
        return TokenPositions(
            seq_flows=[
                self._generate_location_label(element, flow)
                for flow in element.in_flows
            ],
            msg_flows=[
                self._generate_location_label(element, flow) for flow in element.in_msgs
            ],
        )

    def _get_expressions(self, ctx: Context) -> list[str]:
        """
        Returns a list of the expressions that lie on the flows leaving a specific
        node. Example: ["x > 5"]
        """
        return [flow.expression for flow in ctx.element.out_flows if flow.expression]

    def _build_expr_conditional(self, ctx: Context) -> StringManager:
        """
        This function builds and returns a conditional block. This should be called
        only by the _build_atomic_block function.
        example:
        if
            :: x > 5 -> putToken(...)
            :: ...
        fi
        """
        sm = StringManager()
        sm.write_str("if", NL_SINGLE)

        if ctx.has_option:
            # This zip works because the out_flows is an array, which holds its order
            for expression, location in zip(
                self._get_expressions(ctx), self._get_put_locations(ctx.element)
            ):
                sm.write_str(
                    f":: {expression.replace('\n', '')} -> putToken({location})",
                    NL_SINGLE,
                )
        if ctx.boundary_events:
            # 1) get all of the put locations [[end_from_boundevent, ...], ...]
            # 2) get all of the consume locations for each boundevent [[end_from_boundevent, ...]]
            # (hastoken(boundevent1consume1) || hastoken(boundevent1consume2)) ->
            #     putToken(element1_from_boundevent1)
            #     putToken(element2_from_boundevent1)
            put_locations = [
                self._get_put_locations(boundary_event)
                for boundary_event in ctx.boundary_events
            ]
            consume_locations = [
                self._get_consume_locations(boundary_event).get_all_positions()
                for boundary_event in ctx.boundary_events
            ]

            # We can zip these two together, because it will return a list n = len(ctx.boundary_events)
            for put_locs, consume_locs in zip(put_locations, consume_locations):
                sm.write_str(":: (")
                sm.write_str(
                    " || ".join(
                        [f"hasToken({consume_loc})" for consume_loc in consume_locs]
                    )
                )
                sm.write_str(") ->", NL_SINGLE, IndentAction.INC)
                for consume_loc in consume_locs:
                    sm.write_str(f"consumeToken({consume_loc})", NL_SINGLE)
                for put_loc in put_locs:
                    sm.write_str(f"putToken({put_loc})", NL_SINGLE)
                sm.write_str("", indent_action=IndentAction.DEC)

        sm.write_str(
            ':: atomic{else -> printf("Assert: No viable path to take"); assert false}',
            NL_SINGLE,
        )
        sm.write_str("fi", NL_SINGLE)
        return sm

    def _get_put_locations(self, element: Node) -> list[str]:
        """
        Returns a list of labels representing all outgoing flows from a node.
        Each label indicates the target node and the current node as the source.
        Example: ['Node2_FROM_Node1']
        """
        return [
            self._generate_location_label(flow.target_node, flow)
            for flow in element.out_flows + element.out_msgs
        ]

    def _build_guard(self, ctx: Context) -> StringManager:
        """
        Constructs a guard condition for an atomic block in a process.
        The guard checks whether a token exists at the current node, based on incoming flows.
        Example: (hasToken(Node2_FROM_Start) || hasToken(Node2_FROM_Node1)).
        If the element of interest here is a triggerable event, then we make sure that it
        has a token from one of its incoming sequence flows and one of its incoming message
        flows.
        Example: ((hasToken(Node2_FROM_Start) || hasToken(Node2_FROM_Node1)) && (hasToken(Node2_From_NodeInOtherProcess))).
        """

        guard: StringManager = StringManager()

        # Store the consume locations to avoid multiple calls.
        consume_locations: TokenPositions = self._get_consume_locations(ctx.element)
        inner_process_positions: list[str] = (
            consume_locations.get_in_process_positions()
        )
        msg_positions: list[str] = consume_locations.msg_flows

        if inner_process_positions:
            guard.write_str("(")
            tokens: list[str] = [f"hasToken({pos})" for pos in inner_process_positions]
            if ctx.is_parallel:
                guard.write_str(" && ".join(tokens))
            else:
                guard.write_str(" || ".join(tokens))
            guard.write_str(")")

        if msg_positions:
            guard.write_str(" && (" if inner_process_positions else "(")
            tokens_msg: list[str] = [f"hasToken({pos})" for pos in msg_positions]
            guard.write_str(" && ".join(tokens_msg))
            guard.write_str(")")

        if ctx.boundary_events:
            guard.write_str(" && (")

            guard.write_str(
                " || ".join(
                    [
                        f"hasToken({loc})"
                        for boundary_event in ctx.boundary_events
                        for loc in self._get_consume_locations(
                            boundary_event
                        ).get_all_positions()
                    ]
                )
            )
            guard.write_str(")")

        return guard

    def _build_atomic_block(self, ctx: Context) -> StringManager:
        """
        This function builds an atomic block to execute the element's behavior,
        consume the token and move the token forward.
        """

        atomic_block = StringManager()
        atomic_block.write_str(":: atomic { (")

        guard = self._build_guard(ctx)

        atomic_block.write_str(guard)
        atomic_block.write_str(") ->", NL_SINGLE, IndentAction.INC)
        if ctx.behavior_model:
            atomic_block.write_str(f"{ctx.element.id}_BehaviorModel()", NL_SINGLE)

        atomic_block.write_str("d_step {", NL_SINGLE, IndentAction.INC)

        atomic_block.write_str(f'printf("ID: {ctx.element.id}\\n")', NL_SINGLE)
        atomic_block.write_str("stateLogger()", NL_SINGLE)

        for location in self._get_consume_locations(ctx.element).get_all_positions():
            atomic_block.write_str(f"consumeToken({location})", NL_SINGLE)

        if ctx.has_option or ctx.boundary_events:
            atomic_block.write_str(self._build_expr_conditional(ctx))
        else:
            for location in self._get_put_locations(ctx.element):
                atomic_block.write_str(f"putToken({location})", NL_SINGLE)

        atomic_block.write_str("}", NL_SINGLE, IndentAction.DEC)

        if ctx.end_event:
            atomic_block.write_str("break", NL_SINGLE)

        atomic_block.write_str("}", NL_SINGLE, IndentAction.DEC)

        return atomic_block

    def _gen_behavior_model(self, ctx: Context) -> None:
        """
        Writes to the behaviors field to make an inline behavior model for the
        passed element.
        """
        start_block_key_words = {"if"}
        end_block_key_words = {"fi"}
        self.behaviors.write_str(
            f"inline {ctx.element.id}_BehaviorModel() {{", NL_SINGLE, IndentAction.INC
        )
        processed_str_list = [
            line.strip() for line in ctx.behavior.split("\n") if line.strip()
        ]

        for line in processed_str_list:
            if line in start_block_key_words:
                self.behaviors.write_str(line, NL_SINGLE, IndentAction.INC)
            elif line in end_block_key_words:
                self.behaviors.write_str(line, NL_SINGLE, IndentAction.DEC)
            else:
                self.behaviors.write_str(line, NL_SINGLE)

        if ctx.behavior:
            self.behaviors.write_str("updateState()", NL_SINGLE)
        else:
            self.behaviors.write_str("skip", NL_SINGLE)

        self.behaviors.write_str("}", NL_DOUBLE, IndentAction.DEC)

    def _gen_var_defs(self, ctx: Context) -> None:
        for var in self._get_consume_locations(ctx.element).get_all_positions():
            self.var_defs.write_str(f"bit {var} = 0", NL_SINGLE)

    def __repr__(self) -> str:
        return f"{self.defs}{self.var_defs}{self.behaviors}{self.init_proc_contents}{self.promela}"

    ####################
    # Visitor Methods
    ####################

    def visit_start_event(self, event: StartEvent) -> bool:
        context = Context(event)
        self._gen_behavior_model(context)
        self._gen_var_defs(context)

        for loc in self._get_consume_locations(event).get_all_positions():
            self.promela.write_str(f"putToken({loc})", NL_SINGLE, IndentAction.NIL)
        # Close the d_step from the `visit_process`
        self.promela.write_str("}", NL_SINGLE, IndentAction.DEC)

        self.promela.write_str("do", NL_SINGLE, IndentAction.NIL)

        atomic_block = self._build_atomic_block(context)

        self.promela.write_str(atomic_block)
        return True

    def visit_end_event(self, event: EndEvent) -> bool:
        context = Context(event)
        context.end_event = True
        self._gen_behavior_model(context)
        self._gen_var_defs(context)

        atomic_block = self._build_atomic_block(context)

        self.promela.write_str(atomic_block)
        return True

    def visit_intermediate_event(self, event: IntermediateEvent) -> bool:
        context = Context(event)
        self._gen_behavior_model(context)
        self._gen_var_defs(context)

        atomic_block = self._build_atomic_block(context)

        self.promela.write_str(atomic_block)
        return True

    def visit_task(self, task: Task) -> bool:
        context = Context(task)
        context.behavior = task.behavior
        context.boundary_events = task.msg_boundary_events
        self._gen_behavior_model(context)
        self._gen_var_defs(context)

        atomic_block = self._build_atomic_block(context)

        self.promela.write_str(atomic_block)
        return True

    def visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> bool:
        context = Context(gateway)
        context.has_option = True
        context.behavior_model = False
        self._gen_var_defs(context)

        atomic_block = self._build_atomic_block(context)
        self.promela.write_str(atomic_block)
        return True

    def end_visit_exclusive_gateway(self, gateway: ExclusiveGatewayNode) -> None:
        pass

    def visit_parallel_gateway(self, gateway: ParallelGatewayNode) -> bool:
        context = Context(gateway)
        context.behavior_model = False
        if not gateway.is_fork:
            context.is_parallel = True
        self._gen_var_defs(context)

        atomic_block = self._build_atomic_block(context)
        self.promela.write_str(atomic_block)
        return True

    def visit_message_flow(self, flow: MessageFlow) -> bool:
        return True

    def visit_process(self, process: Process) -> bool:
        self.init_proc_contents.write_str(
            f"run {process.id}()", NL_SINGLE, IndentAction.NIL
        )
        self.promela.write_str(
            f"proctype {process.id}() {{", NL_SINGLE, IndentAction.INC
        )
        self.promela.write_str("d_step {", NL_SINGLE, IndentAction.INC)
        self.promela.write_str(f'printf("ID: {process.id}\\n")', NL_SINGLE)
        self.promela.write_str("stateLogger()", NL_SINGLE)
        self.promela.write_str("pid me = _pid", NL_SINGLE, IndentAction.NIL)
        return True

    def end_visit_process(self, process: Process) -> None:
        self.promela.write_str("od", NL_SINGLE)
        self.promela.write_str("}", NL_SINGLE, IndentAction.DEC)

    def visit_bpmn(self, bpmn: Bpmn) -> bool:
        self.defs.write_str(HELPER_FUNCS_STR, NL_DOUBLE)
        self.init_proc_contents.write_str("init {", NL_SINGLE, IndentAction.INC)
        self.init_proc_contents.write_str("atomic {", NL_SINGLE, IndentAction.INC)
        self.init_proc_contents.write_str("stateDump()", NL_SINGLE)
        self.init_proc_contents.write_str("caculateState()", NL_SINGLE)
        return True

    def end_visit_bpmn(self, bpmn: Bpmn) -> None:
        self.init_proc_contents.write_str("}", NL_SINGLE, IndentAction.DEC)
        self.init_proc_contents.write_str("}", NL_DOUBLE, IndentAction.DEC)
