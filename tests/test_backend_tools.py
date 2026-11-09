"""活动节点可选的 Skill 与 MCP。"""

from pathlib import Path

from geni_studio.backends.tools import collect_cursor_tools
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


def test_activity_prompt_names_selected_tools(monkeypatch) -> None:
    captured: dict = {}

    def fake_invoke(**kwargs):
        captured.update(kwargs)
        return "正文"

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", fake_invoke)
    _activity({"id": "n1", "name": "开发", "role": "developer", "inputs": [], "outputs": []})(
        {"node_tools": {"n1": {"skills": ["project:sdk"], "mcp": ["user:wiki"]}}}
    )
    prompt = captured["user_prompt"]
    assert "sdk（项目）" in prompt
    assert "wiki（用户）" in prompt
    assert "这一步只使用下面列出的 Skill 和 MCP。" in prompt
