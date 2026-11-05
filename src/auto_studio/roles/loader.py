"""从 roles/<name>/role.md 加载角色系统提示。"""

from __future__ import annotations

from pathlib import Path

from auto_studio.config.context import factory_root


def role_md_path(role_name: str, root: Path | None = None) -> Path:
    root = root or factory_root()
    return root / "roles" / role_name / "role.md"


def load_role_system_prompt(role_name: str, root: Path | None = None) -> str:
    path = role_md_path(role_name, root)
    if not path.is_file():
        raise FileNotFoundError(f"缺少角色定义: {path}")
    return path.read_text(encoding="utf-8")
