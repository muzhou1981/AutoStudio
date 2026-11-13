"""内置流程 npu_kernel_kda：按 KDA 循证迭代编排 NPU 算子开发，模板随流程保存。"""

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

FLOW = "npu_kernel_kda"
TEMPLATES = ("contract", "draft", "verification", "perf_evidence", "integration", "integration_check", "report")


def test_npu_kernel_kda_is_builtin_and_runnable():
    found = [item for item in list_workflows() if item["workflow_id"] == FLOW]
    assert found and found[0]["builtin"] is True
    assert found[0]["title"] == "NPU 算子开发（KDA）"
    loaded = get_workflow(FLOW)["workflow"]
    assert check_workflow(loaded, FLOW) == []
    names = [node["name"] for node in loaded["nodes"]]
    assert names == [
        "启动", "算子合同", "确认合同", "方案草案", "审方案", "实现候选", "分层验证",
        "诊断与取舍", "接入算子库", "集成核对", "算子报告", "晋升评审", "提交入库", "结束",
    ]
    nodes = {node["id"]: node for node in loaded["nodes"]}
    assert nodes["confirm_contract"]["reject_to"] == "contract"
    assert nodes["review_draft"]["reject_to"] == "draft"
    assert (nodes["verify"]["returns_to"], nodes["verify"]["max_loops"]) == ("implement", 3)
    assert (nodes["measure"]["returns_to"], nodes["measure"]["max_loops"]) == ("implement", 4)
    assert (nodes["integration_check"]["returns_to"], nodes["integration_check"]["max_loops"]) == ("integrate", 2)
    assert nodes["promote"]["reject_to"] == "implement"
    assert nodes["land"]["commits_on_branch"] is True
    assert all(node.get("instruction") for node in loaded["nodes"] if node["kind"] == "activity" and not node.get("commits_on_branch"))
    assert "SVB" in nodes["measure"]["instruction"]

    with pytest.raises(ConfigError, match="先复制"):
        save_workflow(FLOW, loaded)
    with pytest.raises(ConfigError, match="不能删除"):
        delete_workflow(FLOW)


def test_npu_kernel_kda_templates_are_owned_and_attributed():
    folder = factory_root() / "workflows" / FLOW
    loaded = get_workflow(FLOW)["workflow"]
    templates = [
        output["template"]
        for node in loaded["nodes"]
        for output in node.get("outputs") or []
        if isinstance(output, dict)
    ]
    assert templates == [f"templates/{name}.md" for name in TEMPLATES]
    for ref in templates:
        assert not template_file_error(str(folder / ref))
    for name in ("contract", "draft", "verification"):
        assert "CC BY 4.0" in (folder / "templates" / f"{name}.md").read_text(encoding="utf-8")
    for name in ("perf_evidence", "report"):
        assert "ncu-report-skill" in (folder / "templates" / f"{name}.md").read_text(encoding="utf-8")


def test_copy_of_npu_kernel_kda_keeps_templates_and_profile(tmp_path: Path):
    shutil.copytree(factory_root() / "workflows" / FLOW, tmp_path / "workflows" / FLOW)
    shutil.copytree(factory_root() / "roles", tmp_path / "roles")
    copied = copy_workflow(FLOW, "my_kernel_kda", "我的 NPU 算子开发（KDA）", root=tmp_path)["workflow"]
    assert "builtin" not in copied
    assert sorted(p.name for p in (tmp_path / "workflows" / "my_kernel_kda" / "templates").iterdir()) == sorted(
        f"{name}.md" for name in TEMPLATES
    )
    assert copied["profile"]["features"]["design_track"] is False
