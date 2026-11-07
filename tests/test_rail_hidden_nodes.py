"""未启用的节点不进入轨道，启用的节点仍按主路径接上。"""

from fastapi.testclient import TestClient

from auto_studio.config.workflow_nodes import FINANCE_NODES, nodes_hidden_from_rail
from auto_studio.hitl.rail import RAIL_NODES, build_rail
from auto_studio.web.app import app

DESIGN = frozenset({"ux_designer", "ui_designer", "visual_designer"})


def _ids(rail: dict) -> list[str]:
    return [cell["id"] for cell in rail["cells"]]


def test_closed_finance_is_hidden_with_the_scenario_skips() -> None:
    hidden = nodes_hidden_from_rail(skip_nodes=DESIGN, finance_enabled=False)
    assert DESIGN <= hidden
    assert FINANCE_NODES <= hidden


def test_open_finance_stays_on_the_rail_between_its_neighbors() -> None:
    hidden = nodes_hidden_from_rail(skip_nodes=DESIGN, finance_enabled=True)
    rail = build_rail(phase="idle", next_nodes=[], awaiting=None, skip_nodes=hidden)
    ids = _ids(rail)
    assert hidden.isdisjoint(ids)
    assert FINANCE_NODES <= set(ids)
    assert ids == [name for name, _label in RAIL_NODES if name not in hidden]
    assert ids[ids.index("config_manager_plan") + 1] == "finance_budget_rough"
    assert ids[ids.index("architect") + 1] == "finance_budget_final"
    assert ids[ids.index("qa") + 1] == "finance_cost_snapshot"
    assert all(cell["state"] != "skipped" for cell in rail["cells"])
    assert rail["total"] == len(ids)


def test_disabled_nodes_drop_out_and_the_neighbors_meet() -> None:
    hidden = nodes_hidden_from_rail(skip_nodes=DESIGN, finance_enabled=False)
    rail = build_rail(
        phase="running",
        next_nodes=["architect"],
        awaiting=None,
        skip_nodes=hidden,
    )
    ids = _ids(rail)
    states = {cell["id"]: cell["state"] for cell in rail["cells"]}
    assert DESIGN.isdisjoint(ids)
    assert FINANCE_NODES.isdisjoint(ids)
    assert ids[ids.index("config_manager_plan") + 1] == "project_manager_scope"
    assert ids[ids.index("architect") + 1] == "gate_architecture_review"
    assert ids[ids.index("qa") + 1] == "project_manager_delivery"
    assert states["project_manager_scope"] == "done"
    assert states["architect"] == "active"
    assert states["gate_architecture_review"] == "pending"
    assert rail["done"] == ids.index("architect")
    assert rail["total"] == len(ids)
    assert all(cell["state"] != "skipped" for cell in rail["cells"])


def test_start_and_end_stay_even_when_named_in_the_skip_list() -> None:
    rail = build_rail(
        phase="idle",
        next_nodes=[],
        awaiting=None,
        skip_nodes={"run_start", "run_end", "developer"},
    )
    ids = _ids(rail)
    assert ids[0] == "run_start"
    assert ids[-1] == "run_end"
    assert "developer" not in ids
    assert rail["current"] == "run_start"


def test_unknown_scenario_still_lists_every_node() -> None:
    rail = build_rail(phase="idle", next_nodes=[], awaiting=None, skip_nodes=None)
    assert _ids(rail) == [name for name, _label in RAIL_NODES]
    assert rail["done"] is None
    assert rail["total"] is None


def test_idle_rail_without_project_hides_finance() -> None:
    client = TestClient(app)
    ids = _ids(client.get("/api/rail").json())
    assert FINANCE_NODES.isdisjoint(ids)
    assert ids[0] == "run_start"
    assert ids[-1] == "run_end"


def test_npu_and_general_software_hide_only_what_is_off() -> None:
    client = TestClient(app)
    npu = _ids(client.get("/api/rail", params={"scenario_key": "npu_operator"}).json())
    assert DESIGN.isdisjoint(npu)
    assert FINANCE_NODES.isdisjoint(npu)
    assert npu[npu.index("config_manager_plan") + 1] == "project_manager_scope"
    assert npu[0] == "run_start"
    assert npu[-1] == "run_end"

    general = client.get("/api/rail", params={"scenario_key": "general_software"}).json()
    general_ids = _ids(general)
    assert DESIGN <= set(general_ids)
    assert FINANCE_NODES.isdisjoint(general_ids)
    assert general_ids[general_ids.index("visual_designer") + 1] == "project_manager_scope"
    assert all(cell["state"] != "skipped" for cell in general["cells"])


def test_started_npu_run_omits_disabled_nodes() -> None:
    client = TestClient(app)
    started = client.post(
        "/api/runs",
        json={"human_request": "轨道不显示未启用节点", "scenario_key": "npu_operator"},
    )
    assert started.status_code == 200
    rail = started.json()["rail"]
    ids = _ids(rail)
    assert DESIGN.isdisjoint(ids)
    assert FINANCE_NODES.isdisjoint(ids)
    assert ids[ids.index("config_manager_plan") + 1] == "project_manager_scope"
    assert all(cell["state"] != "skipped" for cell in rail["cells"])
    assert rail["total"] == len(ids)
