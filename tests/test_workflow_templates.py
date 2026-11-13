"""随流程保存的输出模板：保存时收入、按流程目录解析、清理与复制。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geni_studio.config.registry import template_file_error
from geni_studio.config.workflow_defs import (
    copy_workflow,
    create_workflow,
    get_workflow,
    list_workflow_versions,
    save_as_subgraph,
    save_workflow,
)
from geni_studio.config.workflow_templates import MAX_TEMPLATE_BYTES, owned_name
from geni_studio.web.app import app
from geni_studio.workflows.executable import check_workflow


def _root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "roles" / "developer").mkdir(parents=True)
    (tmp_path / "roles" / "developer" / "role.md").write_text(
        "---\nname: developer\ntitle: 程序员\noutputs: [code_change]\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("geni_studio.config.workflow_defs.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.config.context.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.web.workflow_routes.factory_root", lambda: tmp_path)


def _nodes(template: str, **extra: str) -> list[dict]:
    output = {"name": "spec_doc", "source": "file", "template": template, **extra}
    return [
        {"id": "start", "kind": "start", "name": "启动", "role": "human", "returns_to": ""},
        {"id": "n1", "kind": "activity", "name": "起草", "role": "developer", "returns_to": "", "outputs": [output]},
        {"id": "end", "kind": "end", "name": "结束", "role": "human", "returns_to": ""},
    ]


def _template_of(workflow_id: str, root: Path) -> str:
    return get_workflow(workflow_id, root=root)["workflow"]["nodes"][1]["outputs"][0]["template"]


def _outside(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / "outside" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_save_copies_external_file_and_records_relative_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root(tmp_path, monkeypatch)
    create_workflow("demo", "演示", root=tmp_path)
    source = _outside(tmp_path, "spec.md", "# 规格\n")
    save_workflow("demo", {"title": "演示", "nodes": _nodes(str(source))}, root=tmp_path)
    assert _template_of("demo", tmp_path) == "templates/spec.md"
    owned = tmp_path / "workflows" / "demo" / "templates" / "spec.md"
    assert owned.read_text(encoding="utf-8") == "# 规格\n"
    source.write_text("# 改过\n", encoding="utf-8")
    assert owned.read_text(encoding="utf-8") == "# 规格\n"
    assert check_workflow(get_workflow("demo", root=tmp_path)["workflow"], "demo", root=tmp_path) == []


def test_same_name_reuses_or_renames(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _root(tmp_path, monkeypatch)
    create_workflow("demo", "演示", root=tmp_path)
    first = _outside(tmp_path, "spec.md", "一\n")
    save_workflow("demo", {"title": "演示", "nodes": _nodes(str(first))}, root=tmp_path)
    save_workflow("demo", {"title": "演示", "nodes": _nodes(str(first))}, root=tmp_path)
    assert _template_of("demo", tmp_path) == "templates/spec.md"
    other = _outside(tmp_path, "b/spec.md", "二\n")
    save_workflow("demo", {"title": "演示", "nodes": _nodes(str(other))}, root=tmp_path)
    assert _template_of("demo", tmp_path) == "templates/spec-2.md"
    folder = tmp_path / "workflows" / "demo" / "templates"
    assert (folder / "spec.md").read_text(encoding="utf-8") == "一\n"


def test_edited_content_becomes_new_file_and_versions_keep_old(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root(tmp_path, monkeypatch)
    create_workflow("demo", "演示", root=tmp_path)
    save_workflow("demo", {"title": "演示", "nodes": _nodes(str(_outside(tmp_path, "spec.md", "一\n")))}, root=tmp_path)
    save_workflow("demo", {"title": "演示", "nodes": _nodes("templates/spec.md", content="二\n")}, root=tmp_path)
    assert _template_of("demo", tmp_path) == "templates/spec-2.md"
    save_workflow("demo", {"title": "演示", "nodes": _nodes("templates/spec-2.md", content="三\n")}, root=tmp_path)
    assert _template_of("demo", tmp_path) == "templates/spec-3.md"
    folder = tmp_path / "workflows" / "demo" / "templates"
    assert sorted(path.name for path in folder.iterdir()) == ["spec-2.md", "spec-3.md", "spec.md"]
    latest = list_workflow_versions("demo", root=tmp_path)[0]
    assert latest["changes"]["templates"] == [{"activity": "起草", "output": "spec_doc"}]
    unchanged = save_workflow("demo", {"title": "演示", "nodes": _nodes("templates/spec-3.md", content="三\n")}, root=tmp_path)
    assert unchanged["workflow"]["nodes"][1]["outputs"][0]["template"] == "templates/spec-3.md"


def test_prune_removes_only_unreferenced_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _root(tmp_path, monkeypatch)
    create_workflow("demo", "演示", root=tmp_path)
    save_workflow("demo", {"title": "演示", "nodes": _nodes(str(_outside(tmp_path, "spec.md", "一\n")))}, root=tmp_path)
    folder = tmp_path / "workflows" / "demo" / "templates"
    (folder / "stray.md").write_text("没人引用\n", encoding="utf-8")
    save_workflow("demo", {"title": "演示 2", "nodes": _nodes("templates/spec.md")}, root=tmp_path)
    assert sorted(path.name for path in folder.iterdir()) == ["spec.md"]


def test_unreadable_external_path_is_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _root(tmp_path, monkeypatch)
    create_workflow("demo", "演示", root=tmp_path)
    missing = str(tmp_path / "outside" / "gone.md")
    save_workflow("demo", {"title": "演示", "nodes": _nodes(missing)}, root=tmp_path)
    assert _template_of("demo", tmp_path) == missing
    problems = check_workflow(get_workflow("demo", root=tmp_path)["workflow"], "demo", root=tmp_path)
    assert any("文件不存在" in line for line in problems)


def test_source_is_inferred_from_the_template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _root(tmp_path, monkeypatch)
    create_workflow("demo", "演示", root=tmp_path)
    nodes = _nodes("https://example.com/spec.md")
    del nodes[1]["outputs"][0]["source"]
    save_workflow("demo", {"title": "演示", "nodes": nodes}, root=tmp_path)
    output = get_workflow("demo", root=tmp_path)["workflow"]["nodes"][1]["outputs"][0]
    assert output["source"] == "link"
    assert not (tmp_path / "workflows" / "demo" / "templates").exists()
    source = _outside(tmp_path, "spec.md", "一\n")
    nodes = _nodes(str(source))
    del nodes[1]["outputs"][0]["source"]
    save_workflow("demo", {"title": "演示", "nodes": nodes}, root=tmp_path)
    assert _template_of("demo", tmp_path) == "templates/spec.md"


@pytest.mark.parametrize("bad", ["templates/../x.md", "templates/a/b.md", "../templates/x.md", "templates/.hidden", "x.md"])
def test_owned_name_rejects_paths_outside_templates(bad: str) -> None:
    assert owned_name(bad) == ""


def test_relative_path_outside_templates_fails_the_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _root(tmp_path, monkeypatch)
    create_workflow("demo", "演示", root=tmp_path)
    (tmp_path / "workflows" / "demo" / "workflow.yaml").write_text(
        "workflow_id: demo\ntitle: 演示\nnodes:\n"
        "- {id: start, kind: start, name: 启动, role: human, returns_to: ''}\n"
        "- id: n1\n  kind: activity\n  name: 起草\n  role: developer\n  returns_to: ''\n"
        "  outputs: [{name: spec_doc, source: file, template: templates/../../secret.md}]\n"
        "- {id: end, kind: end, name: 结束, role: human, returns_to: ''}\n",
        encoding="utf-8",
    )
    problems = check_workflow(get_workflow("demo", root=tmp_path)["workflow"], "demo", root=tmp_path)
    assert any("本流程 templates/" in line for line in problems)


def test_copy_and_subgraph_bring_templates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _root(tmp_path, monkeypatch)
    create_workflow("demo", "演示", root=tmp_path)
    save_workflow("demo", {"title": "演示", "nodes": _nodes(str(_outside(tmp_path, "spec.md", "一\n")))}, root=tmp_path)
    copy_workflow("demo", "demo-copy", "副本", root=tmp_path)
    assert _template_of("demo-copy", tmp_path) == "templates/spec.md"
    assert (tmp_path / "workflows" / "demo-copy" / "templates" / "spec.md").read_text(encoding="utf-8") == "一\n"
    nodes = get_workflow("demo", root=tmp_path)["workflow"]["nodes"]
    save_as_subgraph("片段", nodes, workflow_id="piece", source_id="demo", root=tmp_path)
    assert _template_of("piece", tmp_path) == "templates/spec.md"
    assert (tmp_path / "workflows" / "piece" / "templates" / "spec.md").is_file()
    assert check_workflow(get_workflow("piece", root=tmp_path)["workflow"], "piece", root=tmp_path) == []


def test_template_file_error_limits_size_and_encoding(tmp_path: Path) -> None:
    large = tmp_path / "large.md"
    large.write_bytes(b"a" * (MAX_TEMPLATE_BYTES + 1))
    assert "超过" in template_file_error(str(large))
    binary = tmp_path / "binary.md"
    binary.write_bytes(b"\xff\xfe\x00")
    assert "UTF-8" in template_file_error(str(binary))


def test_template_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _root(tmp_path, monkeypatch)
    create_workflow("demo", "演示", root=tmp_path)
    save_workflow("demo", {"title": "演示", "nodes": _nodes(str(_outside(tmp_path, "spec.md", "一\n")))}, root=tmp_path)
    client = TestClient(app)
    content = client.get("/api/workflows/demo/templates/content", params={"path": "templates/spec.md"})
    assert content.status_code == 200
    assert content.json()["content"] == "一\n"
    assert client.get("/api/workflows/demo/templates/content", params={"path": "templates/../workflow.yaml"}).status_code == 400
    assert client.get("/api/workflows/demo/templates/check", params={"path": "templates/spec.md"}).status_code == 200
    missing = client.get("/api/workflows/demo/templates/check", params={"path": "templates/none.md"})
    assert missing.status_code == 400
    assert missing.json()["detail"] == "文件不存在。"
