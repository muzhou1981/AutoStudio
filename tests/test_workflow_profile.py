"""流程承载运行档案；场景降为兼容层（D6）。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from langgraph.checkpoint.memory import MemorySaver

from geni_studio.config.context import (
    ConfigError,
    build_run_context,
    build_run_context_from_state,
    factory_root,
)
from geni_studio.config.registry import effective_config_summary
from geni_studio.config.workflow_defs import validate_workflow, workflow_exists
from geni_studio.hitl.service import GraphRunService
from geni_studio.workflows.default import compile_graph

_FLOW = """workflow_id: profiled
title: 带档案的流程
profile:
  features:
    design_track: true
  limits:
    max_dev_retries: 7
  verification:
    command: "true"
nodes:
- {id: start, kind: start, name: start, role: human}
- {id: draft, kind: activity, name: 起草, role: project_manager}
- {id: end, kind: end, name: end, role: human}
"""


def _root(tmp_path: Path, project: str) -> Path:
    (tmp_path / "workflows" / "profiled").mkdir(parents=True)
    (tmp_path / "workflows" / "profiled" / "workflow.yaml").write_text(_FLOW, encoding="utf-8")
    (tmp_path / "scenarios" / "legacy").mkdir(parents=True)
    (tmp_path / "scenarios" / "legacy" / "scenario.yaml").write_text(
        "scenario_key: legacy\nmigrate_to: profiled\nworkflow:\n  features:\n    design_track: false\n",
        encoding="utf-8",
    )
    (tmp_path / "projects" / "p").mkdir(parents=True)
    (tmp_path / "projects" / "p" / "project.yaml").write_text(project, encoding="utf-8")
    return tmp_path


def test_project_without_scenario_takes_the_workflow_profile(tmp_path):
    root = _root(tmp_path, "project_id: p\ntitle: p\nworkflow:\n  profile_id: profiled\n")
    ctx = build_run_context(project_id="p", root=root)
    assert ctx.scenario_key == ""
    assert ctx.feature_design_track_default() is True
    assert ctx.max_dev_retries == 7
    assert ctx.merged["verification"] == {"command": "true"}
    assert ctx.notices == []


def test_project_overrides_workflow_profile(tmp_path):
    root = _root(
        tmp_path,
        "project_id: p\ntitle: p\nworkflow:\n  profile_id: profiled\n  limits:\n    max_dev_retries: 2\n",
    )
    ctx = build_run_context(project_id="p", root=root)
    assert ctx.max_dev_retries == 2
    assert ctx.feature_design_track_default() is True


def test_legacy_scenario_still_runs_and_reports_migration(tmp_path):
    root = _root(tmp_path, "project_id: p\ntitle: p\nscenario_key: legacy\nworkflow:\n  profile_id: profiled\n")
    ctx = build_run_context(project_id="p", root=root)
    assert ctx.feature_design_track_default() is False
    assert ctx.max_dev_retries == 7
    summary = effective_config_summary(project_id="p", root=root)
    assert any("场景“legacy”" in note and "profiled" in note for note in summary["notices"])


def test_unknown_profile_id_is_reported(tmp_path):
    root = _root(tmp_path, "project_id: p\ntitle: p\nworkflow:\n  profile_id: missing_v1\n")
    assert any("missing_v1" in note for note in build_run_context(project_id="p", root=root).notices)


def test_run_freezes_the_workflow_profile(tmp_path, monkeypatch):
    root = _root(tmp_path, "project_id: p\ntitle: p\nworkflow:\n  profile_id: profiled\n")
    for target in (
        "geni_studio.config.context.factory_root",
        "geni_studio.config.registry.factory_root",
        "geni_studio.config.workflow_defs.factory_root",
    ):
        monkeypatch.setattr(target, lambda: root)
    monkeypatch.setattr("geni_studio.config.precheck.precheck_scenario_materials", lambda *a, **k: None)
    monkeypatch.setattr("geni_studio.hitl.service.workspace_enabled", lambda: False)
    (root / "roles").symlink_to(Path(__file__).resolve().parents[1] / "roles")
    svc = GraphRunService(compile_graph(MemorySaver()))
    st = svc.start(human_request="档案", project_id="p")
    frozen = build_run_context_from_state(st.values)
    assert frozen.feature_design_track_default() is True
    assert frozen.max_dev_retries == 7
    assert st.values["config_snapshot_effective"]["verification"] == {"command": "true"}


def test_invalid_profile_is_rejected():
    flow = yaml.safe_load(_FLOW)
    flow["profile"]["limits"]["max_dev_retries"] = "three"
    with pytest.raises(ConfigError, match="非负整数"):
        validate_workflow(flow)
    flow["profile"] = {"budget": 1}
    with pytest.raises(ConfigError, match="无法识别"):
        validate_workflow(flow)


def test_builtin_scenarios_point_to_existing_workflows():
    root = factory_root()
    for path in sorted((root / "scenarios").glob("*/scenario.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "profile_id" not in (data.get("workflow") or {}), path
        assert workflow_exists(str(data["migrate_to"]), root), path
    npu = yaml.safe_load((root / "scenarios" / "npu_operator" / "scenario.yaml").read_text(encoding="utf-8"))
    assert npu["migrate_to"] == "npu_operator_dev"
