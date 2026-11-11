import shutil
import subprocess
from pathlib import Path
from xml.etree.ElementTree import parse

import pytest
from returns.pipeline import is_successful
from returns.result import Failure

from bpmncwpverify.builder.cbmc_bound import compute_unwinding_bound
from bpmncwpverify.builder.cbmc_builder import CbmcBuilder
from bpmncwpverify.core.accessmethods import bpmnmethods
from bpmncwpverify.core.accessmethods.cwpmethods import CwpXmlParser
from bpmncwpverify.core.bpmn import (
    Bpmn,
    EndEvent,
    Process,
    SequenceFlow,
    StartEvent,
    Task,
)
from bpmncwpverify.core.error import (
    BpmnCbmcUnsupportedElementError,
    CbmcBuildError,
    NotInitializedError,
)
from bpmncwpverify.core.state import State

RESOURCES = Path(__file__).parent.parent / "resources"
needs_cbmc = pytest.mark.skipif(shutil.which("cbmc") is None, reason="cbmc missing")


def _load(folder: str, bpmn_file: str, cwp_file: str):
    base = RESOURCES / folder
    state = State.from_str((base / "state.txt").read_text()).unwrap()
    cwp = CwpXmlParser.from_xml(parse(base / cwp_file).getroot(), state).unwrap()
    bpmn = bpmnmethods.from_xml(parse(base / bpmn_file).getroot(), state).unwrap()
    return state, cwp, bpmn


def _simple():
    return _load("simple_example", "simple_open.bpmn", "test_cwp.xml")


def _builder(state, cwp, bpmn) -> CbmcBuilder:
    return CbmcBuilder().with_state(state).with_cwp(cwp).with_bpmn(bpmn)


def _line_index(lines: list[str], needle: str) -> int:
    return next(i for i, line in enumerate(lines) if needle in line)


def _run_cbmc(tmp_path: Path, c: str, unwind: int) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "model.c"
    path.write_text(c)
    return subprocess.run(
        ["cbmc", str(path), "--unwind", str(unwind)],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _linear_bpmn() -> Bpmn:
    """start -> task -> end"""
    start = StartEvent("s", "s", "", "")
    task = Task("t", "t", "")
    end = EndEvent("e", "e", "", "")
    for src, dst, fid in ((start, task, "f1"), (task, end, "f2")):
        flow = SequenceFlow(fid, fid)
        flow.source_node, flow.target_node = src, dst
        src.add_out_flow(flow)
        dst.add_in_flow(flow)
    process = Process("p", "p")
    for node in (start, task, end):
        process[node.id] = node
    bpmn = Bpmn()
    bpmn.processes["p"] = process
    return bpmn


def test_missing_inputs_give_errors():
    state, cwp, bpmn = _simple()
    for builder in (
        CbmcBuilder().with_cwp(cwp).with_bpmn(bpmn),
        CbmcBuilder().with_state(state).with_bpmn(bpmn),
        CbmcBuilder().with_state(state).with_cwp(cwp),
        CbmcBuilder(),
    ):
        result = builder.build()
        assert isinstance(result, Failure)
        assert isinstance(result.failure(), NotInitializedError)


def test_missing_bpmn_has_no_bound():
    assert isinstance(CbmcBuilder().bound(), Failure)


def test_state_declarations():
    state, cwp, bpmn = _simple()
    c = _builder(state, cwp, bpmn).build().unwrap()
    assert "int x = 0;" in c


def test_enums_consts_and_types():
    state = State.from_str(
        "enum E { a b }\nconst k: byte = 3\nvar v: E = a\nvar f: bool = false\n"
    ).unwrap()
    _, cwp, bpmn = _simple()
    # the CWP and BPMN are not about this state: only the declarations matter
    from bpmncwpverify.builder.cbmc_builder import _generate_state_c

    c = _generate_state_c(state).unwrap()
    assert "#define k 3" in c
    assert "typedef enum { a, b } E;" in c
    assert "E v = a;" in c
    assert "bool f = false;" in c


def test_unsupported_var_type_is_an_error(mocker):
    from bpmncwpverify.builder.cbmc_builder import _generate_state_c

    var = mocker.Mock(id="v", type_="weird")
    state = mocker.Mock(consts=(), enums=(), vars=(var,))
    result = _generate_state_c(state)
    assert isinstance(result.failure(), CbmcBuildError)


def test_main_sets_cwp_start_state_before_loop():
    c = _builder(*_simple()).build().unwrap()
    lines = c.splitlines()
    main = _line_index(lines, "int main(void)")
    init = _line_index(lines[main:], "cwp_init();") + main
    loop = _line_index(lines[main:], "for (") + main
    update = _line_index(lines[main:], "cwp_update();") + main
    assert main < init < loop < update


def test_loop_is_bounded_by_the_bound():
    state, cwp, bpmn = _simple()
    builder = _builder(state, cwp, bpmn)
    bound = builder.bound().unwrap()
    assert bound == compute_unwinding_bound(bpmn) > 0
    assert f"bpmn_step < {bound}u" in builder.build().unwrap()


def test_unsupported_bpmn_element_is_reported():
    # face2face needs parallel gateways
    result = _builder(*_load("face2face", "workflow.bpmn", "cwp.xml")).build()
    if not is_successful(result):
        assert isinstance(result.failure(), BpmnCbmcUnsupportedElementError)


@needs_cbmc
def test_simple_workflow_compiles_and_verifies(tmp_path):
    builder = _builder(*_simple())
    c = builder.build().unwrap()
    result = _run_cbmc(tmp_path, c, builder.bound().unwrap() + 1)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "VERIFICATION SUCCESSFUL" in result.stdout


@needs_cbmc
def test_linear_workflow_compiles_and_verifies(tmp_path):
    state, cwp, _ = _simple()
    builder = _builder(state, cwp, _linear_bpmn())
    c = builder.build().unwrap()
    assert builder.bound().unwrap() == 3
    result = _run_cbmc(tmp_path, c, 4)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "VERIFICATION SUCCESSFUL" in result.stdout
