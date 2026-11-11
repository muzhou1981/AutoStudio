"""内容寻址快照：状态只存引用，旧运行的内联字段仍可读取。"""

from __future__ import annotations

import json

import pytest
from langgraph.checkpoint.memory import MemorySaver

from geni_studio.config.context import factory_root
from geni_studio.hitl.service import GraphRunService, workflow_definition_of
from geni_studio.runtime import snapshots
from geni_studio.workflows.default import compile_graph


def test_start_stores_role_texts_by_reference():
    from geni_studio.backends.runtime import use_config
    from geni_studio.roles.loader import load_role_system_prompt

    svc = GraphRunService(compile_graph(checkpointer=MemorySaver()))
    st = svc.start(human_request="快照引用", scenario_key="npu_operator")
    effective = st.values["config_snapshot_effective"]
    assert "_roles" not in effective
    assert snapshots.is_ref(effective["_roles_ref"])
    role_text = (factory_root() / "roles" / "developer" / "role.md").read_text(encoding="utf-8")
    assert role_text[:200] not in json.dumps(st.values, ensure_ascii=False, default=str)
    with use_config(effective):
        assert load_role_system_prompt("developer") == role_text


def test_old_inline_snapshots_are_still_read():
    from geni_studio.backends.runtime import use_config
    from geni_studio.roles.loader import load_role_system_prompt

    with use_config({"_roles": {"developer": "旧运行内联的角色正文"}}):
        assert load_role_system_prompt("developer") == "旧运行内联的角色正文"
    assert workflow_definition_of({"workflow_definition": {"nodes": []}}) == {"nodes": []}
    ref = snapshots.put({"nodes": [{"id": "x"}]})
    assert workflow_definition_of({"workflow_definition_ref": ref}) == {"nodes": [{"id": "x"}]}
    assert workflow_definition_of({"workflow_definition_ref": "sha256:" + "0" * 64}) is None


def test_file_snapshots_are_written_once_and_verified(tmp_path, monkeypatch):
    monkeypatch.setenv("GENI_STUDIO_CHECKPOINT", "sqlite")
    monkeypatch.setenv("GENI_STUDIO_CHECKPOINT_PATH", str(tmp_path / "checkpoints.sqlite"))
    first = snapshots.put({"b": 2, "a": "角色"})
    again = snapshots.put({"a": "角色", "b": 2})
    assert first == again
    files = list((tmp_path / "snapshots").glob("*.json"))
    assert len(files) == 1
    assert snapshots.get(first) == {"a": "角色", "b": 2}

    other = snapshots.put({"c": 3})
    target = tmp_path / "snapshots" / f"{other.removeprefix('sha256:')}.json"
    target.write_text('{"c": 4}', encoding="utf-8")
    with pytest.raises(snapshots.SnapshotMissing):
        snapshots.get(other)


def test_compiled_workflow_state_keeps_only_the_definition_reference(tmp_path, monkeypatch):
    from test_subgraph_parallel import _patch, _root

    _root(tmp_path)
    _patch(monkeypatch, tmp_path)
    folder = tmp_path / "workflows" / "sample"
    folder.mkdir(parents=True)
    (folder / "workflow.yaml").write_text("""workflow_id: sample
title: snapshot
nodes:
- {id: start, kind: start, name: start, role: human}
- {id: draft, kind: activity, name: draft, role: project_manager}
- {id: gate, kind: gate, name: approve, role: human, decision: approve}
- {id: end, kind: end, name: end, role: human}
""")
    svc = GraphRunService(compile_graph(MemorySaver()))
    st = svc.start(human_request="引用", scenario_key="demo", project_id="bound")
    assert "workflow_definition" not in st.values
    assert snapshots.is_ref(st.values["workflow_definition_ref"])
    assert workflow_definition_of(st.values)["workflow_id"] == "sample"
