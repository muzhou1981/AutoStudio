"""当前后端能交给活动节点的 Skill 和 MCP。

Cursor 的公开 SDK 没有单独的列表接口。本地 Agent 会从项目目录和用户目录
加载 Skill 与 ``.cursor/mcp.json``。这里按同样的位置读取，只返回名称，不返回
命令、参数或密钥。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

_SKILL_DIRS = (
    (".cursor", "skills"),
    (".cursor", "skills-cursor"),
    (".agents", "skills"),
    (".cursor", "plugins", "local"),
)
_SKIP_DIRS = {".git", "node_modules", "__pycache__"}


def clean_tool_ids(raw: object, label: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise TypeError(f"{label} 须为列表。")
    names: list[str] = []
    for item in raw:
        name = str(item or "").strip()
        if not name:
            raise ValueError(f"{label} 名称不能空。")
        if name in names:
            raise ValueError(f"这个 {label} 重复了。")
        if len(name) > 120 or any(char in name for char in "\n\r"):
            raise ValueError(f"{label} 名称无法识别。")
        names.append(name)
    return names


def list_backend_tools() -> dict:
    from geni_studio.backends.cursor_backend import _cursor_backend_enabled

    if os.environ.get("GENI_STUDIO_BACKEND", "").strip().lower() == "codex":
        from geni_studio.config.context import factory_root

        skills = _skills_in(factory_root() / ".agents" / "skills", "project")
        skills += _skills_in(Path.home() / ".agents" / "skills", "user")
        skills += _skills_in(Path.home() / ".codex" / "skills", "user")
        return {"skills": _unique(skills), "mcp": [], "source": "codex", "detail": ""}
    if not _cursor_backend_enabled():
        return {
            "skills": [],
            "mcp": [],
            "source": "stub",
            "detail": "当前后端没有 Skill 和 MCP 工具。",
        }
    try:
        import cursor_sdk  # noqa: F401
    except ImportError:
        return {
            "skills": [],
            "mcp": [],
            "source": "cursor",
            "detail": "读不到 Skill 和 MCP。当前环境没有 Cursor SDK。",
        }
    from geni_studio.config.context import factory_root

    catalog = collect_cursor_tools(factory_root(), Path.home())
    return {
        "skills": catalog["skills"],
        "mcp": catalog["mcp"],
        "source": "cursor",
        "detail": "",
    }


def collect_cursor_tools(project_root: Path, user_root: Path) -> dict:
    skills = _skills(project_root, "project") + _skills(user_root, "user")
    mcp = _mcp_file(project_root / ".cursor" / "mcp.json", "project")
    mcp += _mcp_file(user_root / ".cursor" / "mcp.json", "user")
    return {"skills": _unique(skills), "mcp": _unique(mcp)}


def _skills_in(base: Path, scope: str) -> list[dict]:
    found: list[dict] = []
    for path in _skill_files(base):
        item = _skill_item(path, scope)
        if item:
            found.append(item)
    return found


def _skills(root: Path, scope: str) -> list[dict]:
    found: list[dict] = []
    for parts in _SKILL_DIRS:
        base = root.joinpath(*parts)
        for path in _skill_files(base):
            item = _skill_item(path, scope)
            if item:
                found.append(item)
    return found


def _skill_files(base: Path) -> list[Path]:
    if not base.is_dir():
        return []
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_DIRS]
        if "SKILL.md" in filenames:
            found.append(Path(dirpath) / "SKILL.md")
    return found


def _skill_item(path: Path, scope: str) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    meta = _front_matter(text)
    name = str(meta.get("name") or path.parent.name).strip()
    if not name or "\n" in name:
        return None
    description = str(meta.get("description") or "").strip().replace("\n", " ")
    if len(description) > 120:
        description = description[:117] + "…"
    return {
        "id": f"{scope}:{name}",
        "name": name,
        "scope": scope,
        "description": description,
    }


def _front_matter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    try:
        data = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _mcp_file(path: Path, scope: str) -> list[dict]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return []
    found = []
    for raw in servers:
        name = str(raw).strip()
        if not name or "\n" in name:
            continue
        found.append({"id": f"{scope}:{name}", "name": name, "scope": scope, "description": ""})
    return found


def _unique(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    kept = []
    for item in sorted(items, key=lambda row: (row["scope"] != "project", row["name"])):
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        kept.append(item)
    return kept
