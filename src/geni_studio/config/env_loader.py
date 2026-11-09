"""加载 factory 根目录 `.env`（不覆盖已导出的环境变量，除非 override）。"""

from __future__ import annotations

import os
from pathlib import Path

from geni_studio.config.context import factory_root


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def apply_env_file(*, root: Path | None = None, override: bool = False) -> bool:
    """将 `.env` 写入 `os.environ`；返回是否读到文件。"""
    root = root or factory_root()
    path = root / ".env"
    values = _parse_env_file(path)
    if not values:
        return path.is_file()
    for key, val in values.items():
        if override or key not in os.environ:
            os.environ[key] = val
    return True
