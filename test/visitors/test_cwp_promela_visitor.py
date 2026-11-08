# type: ignore
import pytest

from bpmncwpverify.util.stringmanager import (
    NL_DOUBLE,
    NL_SINGLE,
    IndentAction,
)
from bpmncwpverify.visitors.cwp_promela_visitor import (
    END_STR,
    START_STR,
    CwpPromelaVisitor,
)


class TestCwpPromelaVisitor:
    @pytest.fixture
    def get_mock_write_str(self, mocker):
        return mocker.patch("bpmncwpverify.util.stringmanager.StringManager.write_str")

    def test_visit_cwp(self, get_mock_write_str, mocker):
        mock_write_str = get_mock_write_str
        CwpPromelaVisitor().visit_cwp(mocker.Mock())
        mock_write_str.assert_called_once_with(START_STR, 1)

    def test_create_update_state_inline(self, get_mock_write_str, mocker):
        mock_write_str = get_mock_write_str
        cpv = CwpPromelaVisitor()

        mocker.patch.object(cpv, "build_XOR_block", return_value="test_val")

        prime_vars = mocker.Mock()
        proper_path_block = mocker.Mock()
        var_reassignment = mocker.Mock()
        cpv.prime_vars = prime_vars
        cpv.proper_path_block = proper_path_block
        cpv.var_reassignment = var_reassignment

        cpv.create_update_state_inline()

        calls = [
            mocker.call("inline updateState() {", NL_SINGLE, IndentAction.INC),
            mocker.call(prime_vars),
            mocker.call("if", NL_SINGLE, IndentAction.INC),
            mocker.call(proper_path_block),
            mocker.call(
                ':: else -> printf("Assert: Not a valid CWP transition"); assert false',
                NL_SINGLE,
            ),
            mocker.call("fi", NL_SINGLE, IndentAction.DEC),
            mocker.call(var_reassignment),
            mocker.call("test_val"),
            mocker.call("}", NL_SINGLE, IndentAction.DEC),
        ]

        mock_write_str.assert_has_calls(calls)

    def test_end_visit_cwp(self, get_mock_write_str, mocker):
        mock_write_str = get_mock_write_str

        visitor = CwpPromelaVisitor()

        mock_create_update = mocker.patch.object(visitor, "create_update_state_inline")
        mock_create_update = mocker.patch.object(
            visitor, "create_caculate_state_inline"
        )

        visitor.end_visit_cwp(mocker.Mock())

        mock_write_str.assert_called_once_with(END_STR, NL_DOUBLE)
        mock_create_update.assert_called_once()

    def test_visit_state(self, get_mock_write_str, mocker):
        mock_state = mocker.Mock()
        mock_state.name = "test"
        mock_write_str = get_mock_write_str
        visitor = CwpPromelaVisitor()
        mocker.patch.object(visitor, "_build_prime_var")
        mocker.patch.object(visitor, "_build_vars")
        mocker.patch.object(visitor, "_build_proper_path_block")
        mocker.patch.object(visitor, "_reassign_vars_to_primes")
        mocker.patch.object(visitor, "_add_stationary_state")
        visitor.visit_state(mock_state)
        mock_write_str.assert_called_once_with("bool test = false", 1)

    def test_build_prime_var(self, get_mock_write_str, mocker):
        mock_write_str = get_mock_write_str

        mock_state = mocker.Mock()
        mock_state.name = "test_name"
        visitor = CwpPromelaVisitor()

        mock_build_mapping_function = mocker.patch.object(
            visitor, "_build_mapping_function", return_value="test_val"
        )
        visitor._build_prime_var(mock_state)

        mock_build_mapping_function.assert_called_once()

        calls = [
            mocker.call("bool test_name_prime = test_val", NL_SINGLE),
        ]

        mock_write_str.assert_has_calls(calls)

    def test_build_mapping_function(self, get_mock_write_str, mocker):
        mock_write_str = get_mock_write_str

        mock_state = mocker.Mock()
        mock_state.in_edges = [
            mocker.Mock(expression="in_edge1"),
            mocker.Mock(expression="in_edge2"),
        ]
        mock_state.out_edges = [
            mocker.Mock(expression="out_edge1"),
            mocker.Mock(expression="out_edge2"),
        ]
        visitor = CwpPromelaVisitor()

        visitor._build_mapping_function(mock_state)

        calls = [
            mocker.call("("),
            mocker.call("in_edge1 && in_edge2"),
            mocker.call(") && !("),
            mocker.call("out_edge1 || out_edge2"),
            mocker.call(")"),
        ]

        mock_write_str.assert_has_calls(calls)

    def test_build_mapping_function_no_in_or_out_edges(
        self, get_mock_write_str, mocker
    ):
        mock_write_str = get_mock_write_str

        mock_state = mocker.Mock()
        mock_state.in_edges = []
        mock_state.out_edges = []
        visitor = CwpPromelaVisitor()

        visitor._build_mapping_function(mock_state)

        calls = [
            mocker.call("("),
            mocker.call("true"),
            mocker.call(") && !("),
            mocker.call("false"),
            mocker.call(")"),
        ]

        mock_write_str.assert_has_calls(calls)

    def test_build_XOR_block(self, get_mock_write_str, mocker):
        mock_write_str = get_mock_write_str

        visitor = CwpPromelaVisitor()
        visitor.list_of_cwp_states = ["state1", "state2", "state3"]

        visitor.build_XOR_block()

        calls = [
            mocker.call(
                "// Verification of properties 1 & 2 (verifying that we are always in one state and only one state)",
                NL_SINGLE,
            ),
            mocker.call("int sumOfActiveStates = "),
            mocker.call("state1 + state2 + state3", NL_DOUBLE),
            mocker.call("if", NL_SINGLE, IndentAction.INC),
            mocker.call(
                ':: (sumOfActiveStates != 1) -> {printf("Assert: In more that one or no state"); assert false}',
                NL_SINGLE,
            ),
            mocker.call(":: else -> skip", NL_SINGLE),
            mocker.call("fi", NL_SINGLE, IndentAction.DEC),
        ]

        mock_write_str.assert_has_calls(calls)

    def test_build_proper_path_block(self, get_mock_write_str, mocker):
        mock_state = mocker.Mock()
        mock_state.in_edges = [1]
        mock_state.name = "node1"

        mock_edge1 = mocker.Mock()
        mock_edge1.dest.name = "node2"

        mock_edge2 = mocker.Mock()
        mock_edge2.dest.name = "node3"

        mock_state.out_edges = [mock_edge1, mock_edge2]

        mock_write_str = get_mock_write_str

        visitor = CwpPromelaVisitor()

        visitor._build_proper_path_block(mock_state)

        calls = [
            mocker.call(":: node1 && node2_prime", NL_SINGLE),
            mocker.call(":: node1 && node3_prime", NL_SINGLE),
        ]

        mock_write_str.assert_has_calls(calls)

    def test_build_proper_path_block_with_start_state(self, get_mock_write_str, mocker):
        mock_state = mocker.Mock()
        mock_state.name = "node1"
        mock_state.in_edges = []
        mock_state.out_edges = []

        mock_write_str = get_mock_write_str

        visitor = CwpPromelaVisitor()

        visitor._build_proper_path_block(mock_state)

        mock_write_str.assert_not_called()

    def test_reassign_vars_to_primes(self, get_mock_write_str, mocker):
        mock_write_str = get_mock_write_str

        mock_state = mocker.Mock()
        mock_state.name = "test_name"
        CwpPromelaVisitor()._reassign_vars_to_primes(mock_state)

        mock_write_str.assert_called_once_with("test_name = test_name_prime", NL_SINGLE)

    def test_add_stationary_state(self, get_mock_write_str, mocker):
        mock_write_str = get_mock_write_str

        mock_state = mocker.Mock()
        mock_state.name = "test_name"

        CwpPromelaVisitor()._add_stationary_state(mock_state)
        mock_write_str.assert_called_once_with(
            ":: test_name && test_name_prime", NL_SINGLE
        )
