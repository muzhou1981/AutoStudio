"""从 roles/<name>/role.md 加载角色系统提示与显示名。"""

from __future__ import annotations

from pathlib import Path

import yaml

from auto_studio.config.context import factory_root


def role_md_path(role_name: str, root: Path | None = None) -> Path:
    root = root or factory_root()
    return root / "roles" / role_name / "role.md"


def load_role_system_prompt(role_name: str, root: Path | None = None) -> str:
    path = role_md_path(role_name, root)
    if not path.is_file():
        raise FileNotFoundError(f"缺少角色定义: {path}")
    return path.read_text(encoding="utf-8")


def role_front_matter(text: str) -> dict:
    """读取 role.md 开头的 YAML。没有或无法解析时返回空映射。"""
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


def role_title(text: str, fallback: str) -> str:
    """读取 role.md 文件头的 title。没有时用角色标识。"""
    title = str(role_front_matter(text).get("title") or "").strip().strip("\"'")
    return title or fallback


def _name_list(value: object) -> list[str]:
    raw = value
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def role_contract(role_name: str, root: Path | None = None) -> tuple[list[str], list[str]]:
    """角色默认读取和产出的产物名。"""
    data = role_front_matter(load_role_system_prompt(role_name, root))
    return _name_list(data.get("inputs")), _name_list(data.get("outputs"))
