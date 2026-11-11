"""配置栈与模板决议单元测试。"""

import pytest

# L0 须存在的产物名：各角色 outputs 并集 + 引擎 cost_ledger / run_record（不含 human_request）
L0_ARTIFACT_NAMES = frozenset(
    {
        "requirement_spec",
        "delivery_report",
        "testability_review",
        "test_cases",
        "test_report",
        "ux_spec",
        "ui_spec",
        "visual_assets",
        "architecture_design",
        "task_plan",
        "code_change",
        "change_request",
        "review_report",
        "qa_report",
        "budget_plan",
        "cost_report",
        "config_plan",
        "baseline_log",
        "config_baseline",
        "config_retro",
        "config_proposals",
        "retro_report",
        "process_proposals",
        "cost_ledger",
        "run_record",
    }
)

from geni_studio.config.context import (
    ConfigError,
    apply_omit_sections,
    build_run_context,
    factory_root,
    resolve_design_track,
    resolve_template,
)
from geni_studio.workflows.default import resolve_design_track_enabled


def test_l0_templates_cover_all_registered_artifacts():
    root = factory_root()
    ctx = build_run_context()
    artifacts_dir = root / "templates" / "artifacts"
    missing_files = [
        name for name in sorted(L0_ARTIFACT_NAMES) if not (artifacts_dir / f"{name}.md").is_file()
    ]
    assert not missing_files, f"L0 缺少模板文件: {missing_files}"
    for name in L0_ARTIFACT_NAMES:
        resolved = resolve_template(name, ctx)
        assert resolved.template_path == artifacts_dir / f"{name}.md"


def test_resolve_template_l0_default():
    root = factory_root()
    ctx = build_run_context(scenario_key="npu_operator")
    resolved = resolve_template("requirement_spec", ctx)
    assert resolved.template_path == root / "templates/artifacts/requirement_spec.md"


def test_npu_operator_skip_nodes_and_design_track():
    ctx = build_run_context(scenario_key="npu_operator")
    assert "ux_designer" in ctx.skip_nodes
    assert ctx.feature_design_track_default() is False


def test_web_app_design_track_enabled():
    ctx = build_run_context(scenario_key="web_app")
    assert ctx.feature_design_track_default() is True
    assert ctx.skip_nodes == frozenset()


def test_general_software_enables_design_track():
    ctx = build_run_context(scenario_key="general_software")
    assert ctx.feature_design_track_default() is True
    assert ctx.skip_nodes == frozenset()


def test_middleware_skips_design_nodes():
    ctx = build_run_context(scenario_key="middleware")
    assert ctx.feature_design_track_default() is False
    assert {"ux_designer", "ui_designer", "visual_designer"} <= ctx.skip_nodes


def test_project_inherits_scenario_from_project_yaml(example_retry_limit):
    ctx = build_run_context(project_id="_example")
    assert ctx.scenario_key == "npu_operator"
    assert ctx.max_dev_retries == example_retry_limit


def test_unknown_scenario_rejected():
    with pytest.raises(ConfigError, match="未知 scenario_key"):
        build_run_context(scenario_key="no_such_scenario")


def test_unknown_project_rejected():
    with pytest.raises(ConfigError, match="未知 project_id"):
        build_run_context(project_id="no_such_project")


def test_invalid_skip_node_rejected():
    root = factory_root()
    import yaml

    bad = root / "projects" / "_tmp_bad"
    bad.mkdir(parents=True, exist_ok=True)
    proj = bad / "project.yaml"
    proj.write_text(
        yaml.dump({"workflow": {"skip_nodes": ["not_a_real_node"]}}),
        encoding="utf-8",
    )
    try:
        with pytest.raises(ConfigError, match="skip_nodes"):
            build_run_context(project_id="_tmp_bad", scenario_key="npu_operator")
    finally:
        proj.unlink(missing_ok=True)
        bad.rmdir()


def test_apply_omit_sections():
    md = "## 1. A\nline\n## 2. B\nsecret\n## 3. C\nok\n"
    out = apply_omit_sections(md, ["## 2. B"])
    assert "secret" not in out
    assert "## 1. A" in out
    assert "## 3. C" in out


def test_resolve_design_track_l3_overrides_profile():
    ctx = build_run_context(scenario_key="npu_operator")
    state = {"design_track_enabled": True}
    assert resolve_design_track(state, ctx) is True


def test_resolve_design_track_enabled_from_web_app_scenario():
    state = {"scenario_key": "web_app"}
    assert resolve_design_track_enabled(state) is True


def test_resolve_design_track_enabled_from_example_project():
    state = {"project_id": "_example"}
    assert resolve_design_track_enabled(state) is False
