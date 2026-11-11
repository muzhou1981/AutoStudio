"""飞书 HITL 项目级配置与后端选择（lark-cli / 直连 Bot 凭据）。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from geni_studio.config.context import ConfigError, factory_root, load_project_config

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
    raw = (env.get("GENI_STUDIO_LARK_BACKEND") or os.environ.get("GENI_STUDIO_LARK_BACKEND") or "").strip()
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
        env.get("GENI_STUDIO_PUBLIC_BASE_URL")
        or os.environ.get("GENI_STUDIO_PUBLIC_BASE_URL")
        or "http://127.0.0.1:8765"
    ).rstrip("/")


def _feishu_hitl_from_env(root: Path | None = None) -> FeishuHitlConfig | None:
    root = root or factory_root()
    env = _read_env_file(root)
    chat_id = (
        env.get("GENI_STUDIO_FEISHU_NOTIFY_CHAT_ID")
        or os.environ.get("GENI_STUDIO_FEISHU_NOTIFY_CHAT_ID")
        or ""
    ).strip()
    open_id = (
        env.get("GENI_STUDIO_FEISHU_NOTIFY_OPEN_ID")
        or os.environ.get("GENI_STUDIO_FEISHU_NOTIFY_OPEN_ID")
        or ""
    ).strip()
    if not chat_id and not open_id:
        return None
    web = (
        env.get("GENI_STUDIO_PUBLIC_BASE_URL")
        or os.environ.get("GENI_STUDIO_PUBLIC_BASE_URL")
        or ""
    ).strip()
    return FeishuHitlConfig(
        notify_chat_id=chat_id,
        notify_open_id=open_id,
        web_base_url=web,
        backend=resolve_lark_backend(root),
    )


def load_feishu_hitl_config(
    project_id: str,
    *,
    root: Path | None = None,
) -> FeishuHitlConfig | None:
    root = root or factory_root()
    pid = (project_id or "").strip()
    if pid:
        try:
            project_cfg, _ = load_project_config(root, pid)
        except ConfigError:
            project_cfg = None
        if isinstance(project_cfg, dict):
            hitl = project_cfg.get("hitl")
            if isinstance(hitl, dict):
                feishu = hitl.get("feishu")
                if isinstance(feishu, dict):
                    chat_id = str(feishu.get("notify_chat_id") or "").strip()
                    open_id = str(feishu.get("notify_open_id") or "").strip()
                    if chat_id or open_id:
                        web = str(feishu.get("web_base_url") or "").strip()
                        return FeishuHitlConfig(
                            notify_chat_id=chat_id,
                            notify_open_id=open_id,
                            web_base_url=web,
                            backend=resolve_lark_backend(root),
                        )
    return _feishu_hitl_from_env(root)


def feishu_approvers(project_id: str, *, root: Path | None = None) -> list[str]:
    """项目 `hitl.feishu.approvers`（open_id 列表）。为空表示不限制。"""
    pid = (project_id or "").strip()
    if not pid:
        return []
    try:
        project_cfg, _ = load_project_config(root or factory_root(), pid)
    except ConfigError:
        return []
    hitl = project_cfg.get("hitl") if isinstance(project_cfg, dict) else None
    feishu = hitl.get("feishu") if isinstance(hitl, dict) else None
    raw = feishu.get("approvers") if isinstance(feishu, dict) else None
    if isinstance(raw, str):
        raw = [raw]
    return [str(item).strip() for item in raw or [] if str(item).strip()]


def feishu_target(cfg: FeishuHitlConfig) -> tuple[str, str]:
    """返回 (receive_id_type, receive_id)。"""
    if cfg.notify_chat_id:
        return "chat_id", cfg.notify_chat_id
    return "open_id", cfg.notify_open_id
