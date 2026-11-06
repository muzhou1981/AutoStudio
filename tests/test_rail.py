"""节点轨道：位置只来自下一节点和场景裁剪。"""

from fastapi.testclient import TestClient

from auto_studio.hitl.rail import build_rail
from auto_studio.web.app import app


def _states(rail: dict) -> dict[str, str]:
    return {cell["id"]: cell["state"] for cell in rail["cells"]}


def test_gate_waiting_marks_earlier_done_and_later_pending():
    rail = build_rail(
        phase="awaiting_human",
        next_nodes=["gate_requirement_confirm"],
        awaiting={"kind": "gate", "gate_id": "gate_requirement_confirm"},
        skip_nodes=set(),
    )
    states = _states(rail)
    assert states["run_start"] == "done"
    assert states["project_manager_draft"] == "done"
    assert states["tester_testability"] == "done"
    assert states["gate_requirement_confirm"] == "waiting"
    assert states["developer"] == "pending"
    assert states["run_end"] == "pending"
    assert rail["current"] == "gate_requirement_confirm"
    assert rail["done"] == 3
    assert rail["total"] == len(rail["cells"])


def test_skip_nodes_stay_skipped_and_leave_the_count():
    rail = build_rail(
        phase="awaiting_human",
        next_nodes=["gate_requirement_confirm"],
        awaiting={"kind": "gate", "gate_id": "gate_requirement_confirm"},
        skip_nodes={"ux_designer", "ui_designer", "visual_designer"},
    )
    states = _states(rail)
    assert states["ux_designer"] == "skipped"
    assert states["ui_designer"] == "skipped"
    assert states["visual_designer"] == "skipped"
    assert rail["total"] == len(rail["cells"]) - 3


def test_rollback_reopens_the_current_node_and_clears_later_done():
    rail = build_rail(
        phase="running",
        next_nodes=["developer"],
        awaiting=None,
        skip_nodes=set(),
    )
    states = _states(rail)
    assert states["developer"] == "active"
    assert states["code_reviewer"] == "pending"
    assert states["architect"] == "done"


def test_completed_marks_every_runnable_node_done():
    rail = build_rail(
        phase="completed",
        next_nodes=[],
        awaiting=None,
        skip_nodes={"ux_designer"},
    )
    states = _states(rail)
    assert states["ux_designer"] == "skipped"
    assert states["run_start"] == "done"
    assert states["process_owner_retro"] == "done"
    assert states["run_end"] == "finished"
    assert rail["current"] == "run_end"
    assert rail["done"] == rail["total"] - 1


def test_unknown_skip_list_omits_the_count():
    rail = build_rail(
        phase="running",
        next_nodes=["developer"],
        awaiting=None,
        skip_nodes=None,
    )
    assert rail["done"] is None
    assert rail["total"] is None
    assert _states(rail)["developer"] == "active"


def test_stopped_marks_the_current_cell():
    rail = build_rail(
        phase="stopped",
        next_nodes=[],
        awaiting=None,
        skip_nodes=set(),
        stopped_at="developer",
    )
    assert rail["current"] == "developer"
    states = _states(rail)
    assert states["developer"] == "stopped"
    assert states["architect"] == "done"
    assert states["qa"] == "pending"


def test_paused_marks_the_current_cell_and_keeps_earlier_done():
    rail = build_rail(
        phase="paused",
        next_nodes=["tester_testability"],
        awaiting=None,
        skip_nodes=set(),
        paused_at="tester_testability",
    )
    assert rail["current"] == "tester_testability"
    states = _states(rail)
    assert states["run_start"] == "done"
    assert states["project_manager_draft"] == "done"
    assert states["tester_testability"] == "paused"
    assert states["gate_requirement_confirm"] == "pending"


def test_rejected_gate_stays_waiting():
    log = "[baseline:gate_architecture_review] decision=rejected at=2026-11-06T00:00:00Z"
    rail = build_rail(
        phase="rejected",
        next_nodes=[],
        awaiting=None,
        skip_nodes=set(),
        baseline_log=log,
    )
    assert _states(rail)["gate_architecture_review"] == "waiting"
    assert _states(rail)["developer"] == "pending"


def test_clarification_waits_on_the_draft_node():
    rail = build_rail(
        phase="awaiting_human",
        next_nodes=["hitl_pause"],
        awaiting={"kind": "pm_clarification", "gate_id": None},
        skip_nodes=set(),
    )
    assert rail["current"] == "project_manager_draft"
    assert _states(rail)["project_manager_draft"] == "waiting"


def test_idle_rail_api_marks_design_track_skipped():
    client = TestClient(app)
    body = client.get("/api/rail", params={"scenario_key": "npu_operator"}).json()
    states = _states(body)
    assert states["run_start"] == "initial"
    assert states["run_end"] == "pending"
    assert states["ux_designer"] == "skipped"
    assert states["developer"] == "pending"
    assert body["current"] == "run_start"
    assert body["done"] == 0


def test_started_run_rail_waits_at_requirement_gate():
    client = TestClient(app)
    started = client.post(
        "/api/runs",
        json={"human_request": "看节点轨道", "scenario_key": "npu_operator"},
    )
    assert started.status_code == 200
    rail = started.json()["rail"]
    states = _states(rail)
    assert states["run_start"] == "done"
    assert states["gate_requirement_confirm"] == "waiting"
    assert states["project_manager_draft"] == "done"
    assert states["ux_designer"] == "skipped"
    assert states["finance_budget_rough"] == "skipped"
    assert states["finance_budget_final"] == "skipped"
    assert states["finance_cost_snapshot"] == "skipped"
    assert rail["total"] == len(rail["cells"]) - 6


def test_idle_rail_is_all_pending_except_skips():
    rail = build_rail(
        phase="idle",
        next_nodes=[],
        awaiting=None,
        skip_nodes={"ux_designer"},
    )
    states = _states(rail)
    assert states["run_start"] == "initial"
    assert states["ux_designer"] == "skipped"
    assert states["developer"] == "pending"
    assert states["run_end"] == "pending"
    assert rail["done"] == 0
    assert rail["current"] == "run_start"
