"""内置流程 spec_kit：按 spec-kit 方法编排，模板随流程保存，复制后可编辑。"""

import shutil
from pathlib import Path

import pytest

from geni_studio.config.context import ConfigError, factory_root
from geni_studio.config.registry import template_file_error
from geni_studio.config.workflow_defs import (
    copy_workflow,
    delete_workflow,
    get_workflow,
    list_workflows,
    save_workflow,
)
from geni_studio.workflows.executable import check_workflow

FLOW = "spec_kit"


def test_spec_kit_is_builtin_and_runnable():
    found = [item for item in list_workflows() if item["workflow_id"] == FLOW]
    assert found and found[0]["builtin"] is True
    loaded = get_workflow(FLOW)["workflow"]
    assert check_workflow(loaded, FLOW) == []
    names = [node["name"] for node in loaded["nodes"]]
    assert names == ["启动", "起草规格", "审规格", "制定方案", "拆分任务", "一致性分析", "审方案", "实现", "核对实现", "验收", "提交入库", "结束"]
    nodes = {node["id"]: node for node in loaded["nodes"]}
    assert nodes["review_spec"]["reject_to"] == "specify"
    assert nodes["analyze"]["returns_to"] == "plan"
    assert nodes["analyze"]["max_loops"] == 2
    assert nodes["review_plan"]["reject_to"] == "plan"
    assert nodes["converge"]["returns_to"] == "implement"
    assert nodes["accept"]["reject_to"] == "implement"
    assert nodes["land"]["commits_on_branch"] is True
    assert all(node.get("instruction") for node in loaded["nodes"] if node["kind"] == "activity" and not node.get("commits_on_branch"))

    with pytest.raises(ConfigError, match="先复制"):
        save_workflow(FLOW, loaded)
    with pytest.raises(ConfigError, match="不能删除"):
        delete_workflow(FLOW)


def test_spec_kit_templates_are_owned_and_attributed():
    folder = factory_root() / "workflows" / FLOW
    loaded = get_workflow(FLOW)["workflow"]
    templates = [
        output["template"]
        for node in loaded["nodes"]
        for output in node.get("outputs") or []
        if isinstance(output, dict)
    ]
    assert templates == [f"templates/{name}.md" for name in ("spec", "plan", "tasks", "analysis", "convergence")]
    for ref in templates:
        assert not template_file_error(str(folder / ref))
        text = (folder / ref).read_text(encoding="utf-8")
        assert "github/spec-kit" in text and "MIT License" in text


def test_copy_of_spec_kit_keeps_templates_and_instructions(tmp_path: Path):
    shutil.copytree(factory_root() / "workflows" / FLOW, tmp_path / "workflows" / FLOW)
    shutil.copytree(factory_root() / "roles", tmp_path / "roles")
    copied = copy_workflow(FLOW, "my_spec_kit", "我的 Spec Kit", root=tmp_path)["workflow"]
    assert "builtin" not in copied
    assert sorted(p.name for p in (tmp_path / "workflows" / "my_spec_kit" / "templates").iterdir()) == [
        "analysis.md", "convergence.md", "plan.md", "spec.md", "tasks.md",
    ]
    source = get_workflow(FLOW)["workflow"]["nodes"]
    assert [node.get("instruction") for node in copied["nodes"]] == [node.get("instruction") for node in source]
