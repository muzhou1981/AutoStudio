"""加载 factory 根目录 `.env`（不覆盖已导出的环境变量，除非 override）。"""

from __future__ import annotations

import os
from pathlib import Path

from geni_studio.config.context import factory_root

# 仅在 .env 中缺失或为空时，把进程环境里已有的值写入 .env；不覆盖已有非空项。
_ENV_SYNC_KEYS = ("CURSOR_API_KEY",)


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


def sync_env_secrets_to_dotenv(*, root: Path | None = None) -> list[str]:
    """将 shell 等已注入、但 .env 未落盘的密钥写入 `.env`。返回本次写入的键名。"""
    from geni_studio.cli import env_path, write_env_key

    root = root or factory_root()
    path = env_path(root)
    file_vars = _parse_env_file(path)
    written: list[str] = []
    for name in _ENV_SYNC_KEYS:
        env_val = os.environ.get(name, "").strip()
        if not env_val:
            continue
        if file_vars.get(name, "").strip():
            continue
        write_env_key(path, name, env_val)
        written.append(name)
        file_vars[name] = env_val
    return written


def bootstrap_env(*, root: Path | None = None, override: bool = False) -> bool:
    """加载 `.env`，并把进程里已有密钥同步到空的 `.env` 槽位。"""
    ok = apply_env_file(root=root, override=override)
    sync_env_secrets_to_dotenv(root=root)
    return ok
