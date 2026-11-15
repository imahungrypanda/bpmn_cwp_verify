import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest
from returns.pipeline import is_successful
from returns.result import Success

from bpmncwpverify.builder.cbmc_bound import compute_unwinding_bound
from bpmncwpverify.builder.cbmc_builder import CbmcBuilder
from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.bpmn import (
    Bpmn,
    EndEvent,
    ExclusiveGatewayNode,
    Node,
    Process,
    SequenceFlow,
    StartEvent,
    Task,
)
from bpmncwpverify.core.cwp import Cwp
from bpmncwpverify.core.error import CbmcBuildError, NotInitializedError
from bpmncwpverify.core.state import State

FACE2FACE = "./test/resources/face2face/"
CBMC = shutil.which("cbmc")


def _state() -> State:
    with open(FACE2FACE + "state.txt") as f:
        return State.from_str(f.read()).unwrap()


def _cwp(state: State) -> Cwp:
    with open(FACE2FACE + "cwp.xml") as f:
        return CwpXmlParser.from_xml(ET.fromstring(f.read()), state).unwrap()


def _bpmn(
    kinds: dict[str, str],
    edges: list[tuple[str, str]],
    expressions: dict[tuple[str, str], str] | None = None,
) -> Bpmn:
    make = {
        "start": lambda i: StartEvent(i, i, "", ""),
        "end": lambda i: EndEvent(i, i, "", ""),
        "task": lambda i: Task(i, i, ""),
        "xor": lambda i: ExclusiveGatewayNode(i, i),
    }
    process = Process("p", "p")
    nodes: dict[str, Node] = {}
    for id, kind in kinds.items():
        nodes[id] = make[kind](id)
        process[id] = nodes[id]
    for source, target in edges:
        flow = SequenceFlow(
            f"{source}_{target}", (expressions or {}).get((source, target), "")
        )
        flow.source_node = nodes[source]
        flow.target_node = nodes[target]
        nodes[source].add_out_flow(flow)
        nodes[target].add_in_flow(flow)
        process[flow.id] = flow
    bpmn = Bpmn()
    bpmn.processes["p"] = process
    return bpmn


STRAIGHT = ({"s": "start", "a": "task", "e": "end"}, [("s", "a"), ("a", "e")])
BRANCH = (
    {"s": "start", "x": "xor", "a": "task", "b": "task", "e": "end"},
    [("s", "x"), ("x", "a"), ("x", "b"), ("a", "e"), ("b", "e")],
    {("x", "a"): "terms == pending", ("x", "b"): "terms != pending"},
)
LOOP = (
    {"s": "start", "t": "task", "x": "xor", "e": "end"},
    [("s", "t"), ("t", "x"), ("x", "t"), ("x", "e")],
    {("x", "t"): "terms == pending", ("x", "e"): "terms != pending"},
)
WORKFLOWS = [STRAIGHT, BRANCH, LOOP]
IDS = ["straight", "branch", "loop"]


def _build(workflow: tuple) -> tuple[str, int]:
    state = _state()
    result = (
        CbmcBuilder()
        .with_state(state)
        .with_cwp(_cwp(state))
        .with_bpmn(_bpmn(*workflow))
        .build()
    )
    assert is_successful(result)
    out = result.unwrap()
    return out.c, out.bound


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=IDS)
def test_bound_is_the_bound_of_the_bpmn(workflow):
    state = _state()
    bpmn = _bpmn(*workflow)
    out = (
        CbmcBuilder()
        .with_state(state)
        .with_cwp(_cwp(state))
        .with_bpmn(bpmn)
        .build()
        .unwrap()
    )
    assert out.bound == compute_unwinding_bound(bpmn)
    assert out.unwind == out.bound + 1
    assert f"#define MAX_PASSES {out.bound}u" in out.c


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=IDS)
def test_declares_state(workflow):
    c, _ = _build(workflow)
    assert "#define paymentAmount 253" in c
    assert "enum TermsType {agreed, failed, pending, noRetry};" in c
    assert "static enum TermsType terms = pending;" in c
    assert "static unsigned char paymentOffered = pendingPayment;" in c


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=IDS)
def test_main_sets_cwp_state_before_loop(workflow):
    c, _ = _build(workflow)
    main = c[c.index("int main(void)") :]
    assert main.index("cwp_init();") < main.index("for (")
    assert main.index("for (") < main.index("bpmn_step();")
    assert main.index("bpmn_step();") < main.index("cwp_update();")
    assert "pass_count < MAX_PASSES" in main
    # the CWP moves once per pass, not once per variable
    assert main.count("cwp_update();") == 1


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=IDS)
def test_c_compiles(workflow, tmp_path):
    gcc = shutil.which("gcc")
    if gcc is None:
        pytest.skip("no C compiler")
    c, _ = _build(workflow)
    src = tmp_path / "model.c"
    # CBMC built-ins stand in for the real ones
    src.write_text(
        "#define __CPROVER_assume(x) ((void)(x))\n"
        "#define __CPROVER_assert(x, m) assert(x)\n" + c
    )
    done = subprocess.run(
        [gcc, "-fsyntax-only", "-Wall", "-Werror", str(src)],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr


@pytest.mark.skipif(CBMC is None, reason="cbmc is not installed")
@pytest.mark.parametrize("workflow", WORKFLOWS, ids=IDS)
def test_cbmc_parses_and_stops_within_bound(workflow, tmp_path):
    c, bound = _build(workflow)
    src = tmp_path / "model.c"
    src.write_text(c)
    done = subprocess.run(
        [CBMC, str(src), "--unwind", str(bound + 1), "--unwinding-assertions"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "CONVERSION ERROR" not in done.stdout + done.stderr
    # no assertion fails, including the loop's unwinding assertion
    assert done.returncode == 0, done.stdout
    assert "VERIFICATION SUCCESSFUL" in done.stdout


@pytest.mark.parametrize(
    "missing", ["state", "cwp", "bpmn"], ids=["state", "cwp", "bpmn"]
)
def test_missing_input_is_an_error(missing):
    state = _state()
    builder = CbmcBuilder()
    if missing != "state":
        builder.with_state(state)
    if missing != "cwp":
        builder.with_cwp(_cwp(state))
    if missing != "bpmn":
        builder.with_bpmn(_bpmn(*STRAIGHT))
    result = builder.build()
    assert not is_successful(result)
    error = result.failure()
    assert isinstance(error, NotInitializedError)
    assert error.var_name == f"CbmcBuilder.{missing}"


def test_cwp_without_states_is_a_build_error():
    state = _state()
    result = (
        CbmcBuilder()
        .with_state(state)
        .with_cwp(Cwp())
        .with_bpmn(_bpmn(*STRAIGHT))
        .build()
    )
    assert isinstance(result.failure(), CbmcBuildError)


def test_unsupported_bpmn_element_fails_the_build():
    state = _state()
    bpmn = _bpmn(*STRAIGHT)
    bpmn.processes["p"]["a"].msg_boundary_events = [
        Task.BoundaryEvent("be", "be", "", "", "a")
    ]
    result = (
        CbmcBuilder().with_state(state).with_cwp(_cwp(state)).with_bpmn(bpmn).build()
    )
    assert not is_successful(result)


def test_with_setters_return_the_builder():
    builder = CbmcBuilder()
    state = _state()
    assert builder.with_state(state) is builder
    assert builder.with_cwp(_cwp(state)) is builder
    assert builder.with_bpmn(_bpmn(*STRAIGHT)) is builder
    assert isinstance(builder.state, Success)
