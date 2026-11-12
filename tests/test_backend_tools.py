"""后端的 Skill 与 MCP 目录；Skill 按节点选用，MCP 全局可见。"""

from pathlib import Path

from geni_studio.backends.tools import collect_cursor_tools, list_backend_tools
from geni_studio.workflows.executable import _activity


def test_catalog_reads_project_and_user_sources(tmp_path: Path) -> None:
    project = tmp_path / "project"
    user = tmp_path / "user"
    skill = project / ".cursor" / "skills" / "sdk"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: sdk\ndescription: 查询模型\n---\n正文\n",
        encoding="utf-8",
    )
    (user / ".cursor").mkdir(parents=True)
    (user / ".cursor" / "mcp.json").write_text(
        '{"mcpServers": {"wiki": {"command": "secret-command"}}}',
        encoding="utf-8",
    )
    catalog = collect_cursor_tools(project, user)
    assert catalog["skills"] == [
        {"id": "project:sdk", "name": "sdk", "scope": "project", "description": "查询模型"},
    ]
    assert catalog["mcp"] == [
        {"id": "user:wiki", "name": "wiki", "scope": "user", "description": ""},
    ]
    assert "secret-command" not in str(catalog)


def test_activity_prompt_names_only_selected_skills(monkeypatch) -> None:
    captured: dict = {}

    def fake_invoke(**kwargs):
        captured.update(kwargs)
        return "正文"

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", fake_invoke)
    _activity({"id": "n1", "name": "开发", "role": "developer", "inputs": [], "outputs": []})(
        {"node_tools": {"n1": {"skills": ["project:sdk"], "mcp": ["user:wiki"]}}}
    )
    prompt = captured["user_prompt"]
    assert "这一步优先使用下面的 Skill：sdk（项目）" in prompt
    assert "wiki" not in prompt and "MCP" not in prompt


def test_catalog_follows_the_requested_backend_and_project(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "repo"
    (workspace / ".cursor").mkdir(parents=True)
    (workspace / ".cursor" / "mcp.json").write_text('{"mcpServers": {"repo-mcp": {"url": "x"}}}', encoding="utf-8")
    codex = tmp_path / "codex"
    codex.mkdir()
    (codex / "config.toml").write_text(
        '[mcp_servers.docs]\ncommand = "secret"\n\n[mcp_servers.off]\ncommand = "x"\nenabled = false\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CODEX_HOME", str(codex))
    monkeypatch.setattr("geni_studio.backends.tools._project_root", lambda pid: workspace if pid else tmp_path)

    cursor = list_backend_tools(backend="cursor", project_id="demo")
    assert [item["id"] for item in cursor["mcp"]] == ["project:repo-mcp"]
    assert list_backend_tools(backend="cursor")["mcp"] == []
    assert [item["id"] for item in list_backend_tools(backend="codex")["mcp"]] == ["user:docs"]
    stub = list_backend_tools(backend="stub")
    assert stub["source"] == "stub" and stub["mcp"] == []
    assert "secret" not in str(list_backend_tools(backend="codex"))
