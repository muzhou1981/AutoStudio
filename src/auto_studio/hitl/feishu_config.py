"""飞书 HITL 项目级配置与后端选择（lark-cli / 直连 Bot 凭据）。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from auto_studio.config.context import ConfigError, factory_root, load_project_config

LarkBackend = Literal["lark_cli", "env_bot"]


@dataclass(frozen=True)
class FeishuHitlConfig:
    notify_chat_id: str = ""
    notify_open_id: str = ""
    web_base_url: str = ""
    backend: LarkBackend = "lark_cli"


def _read_env_file(root: Path) -> dict[str, str]:
    env_path = root / ".env"
    out: dict[str, str] = {}
    if not env_path.is_file():
        return out
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def resolve_lark_backend(root: Path | None = None) -> LarkBackend:
    root = root or factory_root()
    env = _read_env_file(root)
    raw = (env.get("AUTO_STUDIO_LARK_BACKEND") or os.environ.get("AUTO_STUDIO_LARK_BACKEND") or "").strip()
    if raw == "env_bot":
        return "env_bot"
    if raw == "lark_cli":
        return "lark_cli"
    if env.get("LARK_APP_ID") or os.environ.get("LARK_APP_ID"):
        return "env_bot"
    return "lark_cli"


def resolve_public_base_url(root: Path | None = None) -> str:
    root = root or factory_root()
    env = _read_env_file(root)
    return (
        env.get("AUTO_STUDIO_PUBLIC_BASE_URL")
        or os.environ.get("AUTO_STUDIO_PUBLIC_BASE_URL")
        or "http://127.0.0.1:8765"
    ).rstrip("/")


def load_feishu_hitl_config(
    project_id: str,
    *,
    root: Path | None = None,
) -> FeishuHitlConfig | None:
    pid = (project_id or "").strip()
    if not pid:
        return None
    root = root or factory_root()
    try:
        project_cfg, _ = load_project_config(root, pid)
    except ConfigError:
        return None
    hitl = project_cfg.get("hitl")
    if not isinstance(hitl, dict):
        return None
    feishu = hitl.get("feishu")
    if not isinstance(feishu, dict):
        return None
    chat_id = str(feishu.get("notify_chat_id") or "").strip()
    open_id = str(feishu.get("notify_open_id") or "").strip()
    if not chat_id and not open_id:
        return None
    web = str(feishu.get("web_base_url") or "").strip()
    return FeishuHitlConfig(
        notify_chat_id=chat_id,
        notify_open_id=open_id,
        web_base_url=web,
        backend=resolve_lark_backend(root),
    )


def feishu_target(cfg: FeishuHitlConfig) -> tuple[str, str]:
    """返回 (receive_id_type, receive_id)。"""
    if cfg.notify_chat_id:
        return "chat_id", cfg.notify_chat_id
    return "open_id", cfg.notify_open_id
