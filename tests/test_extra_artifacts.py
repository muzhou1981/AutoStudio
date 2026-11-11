"""流程可以声明图状态里没有的自定义产物：编译、运行、落盘并经接口查看。"""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver
from test_subgraph_parallel import _patch, _root

from geni_studio.config.context import ConfigError
from geni_studio.hitl.service import GraphRunService
from geni_studio.workflows.default import compile_graph
from geni_studio.workflows.executable import compile_for_project

_WORKFLOW = """workflow_id: sample
title: 自定义产物
nodes:
- {id: start, kind: start, name: start, role: human}
- id: spec
  kind: activity
  name: 写规格
  role: project_manager
  outputs:
  - {name: kernel_spec, source: link, template: "https://example.com/kernel-spec"}
- id: impl
  kind: activity
  name: 实现
  role: developer
  inputs: [kernel_spec]
  outputs:
  - {name: code_change, source: link, template: "https://example.com/code"}
- {id: gate, kind: gate, name: approve, role: human, decision: approve}
- {id: end, kind: end, name: end, role: human}
"""


def _write(tmp_path: Path, text: str) -> None:
    folder = tmp_path / "workflows" / "sample"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "workflow.yaml").write_text(text, encoding="utf-8")


def test_custom_artifact_flows_between_activities(tmp_path, monkeypatch):
    _root(tmp_path)
    _patch(monkeypatch, tmp_path)
    _write(tmp_path, _WORKFLOW)
    prompts: list[str] = []
    from geni_studio.backends import runner

    real = runner.invoke_role

    def spy(**kwargs):
        prompts.append(kwargs["user_prompt"])
        return real(**kwargs)

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", spy)
    svc = GraphRunService(compile_graph(MemorySaver()))
    st = svc.start(human_request="写一个 kernel", scenario_key="demo", project_id="bound")
    assert st.phase == "awaiting_human"
    spec = st.values["extra_artifacts"]["kernel_spec"]
    assert spec
    assert "kernel_spec" not in {key for key in st.values if key != "extra_artifacts"}
    assert any(f"kernel_spec：\n{spec}" in prompt for prompt in prompts)
    public = svc.status_dict(st.thread_id)["values"]
    assert public["kernel_spec"] == spec
    assert "extra_artifacts" not in public


def test_custom_artifact_is_persisted_and_served(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from geni_studio.web import app as web_app

    _root(tmp_path)
    _patch(monkeypatch, tmp_path)
    _write(tmp_path, _WORKFLOW)
    target = tmp_path / "target"
    monkeypatch.setattr("geni_studio.hitl.service.workspace_enabled", lambda: True)
    monkeypatch.setenv("GENI_STUDIO_TARGET_ROOT", str(target))
    svc = GraphRunService(compile_graph(MemorySaver()))
    st = svc.start(human_request="落盘", scenario_key="demo", project_id="bound")
    run_dir = target / ".geni_studio" / "runs" / st.thread_id
    assert (run_dir / "artifacts" / "kernel_spec.md").read_text(encoding="utf-8").strip() == st.values["extra_artifacts"]["kernel_spec"].strip()

    monkeypatch.setattr(web_app, "_service", svc)
    served = TestClient(web_app.app).get(f"/api/runs/{st.thread_id}/artifacts/kernel_spec")
    assert served.status_code == 200
    assert served.json()["text"].strip() == st.values["extra_artifacts"]["kernel_spec"].strip()
    assert TestClient(web_app.app).get(f"/api/runs/{st.thread_id}/artifacts/nope").status_code == 404


def test_invalid_or_unproduced_custom_artifacts_are_rejected(tmp_path, monkeypatch):
    _root(tmp_path)
    _patch(monkeypatch, tmp_path)
    _write(tmp_path, _WORKFLOW.replace("name: kernel_spec,", "name: Kernel-Spec,"))
    with pytest.raises(ConfigError, match="产物名不合法"):
        compile_for_project("sample", checkpointer=MemorySaver(), root=tmp_path)
    _write(tmp_path, _WORKFLOW.replace("inputs: [kernel_spec]", "inputs: [missing_doc]"))
    with pytest.raises(ConfigError, match="没有活动产出：missing_doc"):
        compile_for_project("sample", checkpointer=MemorySaver(), root=tmp_path)
