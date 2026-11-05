"""通过官方 lark-cli 以 Bot 身份发 IM（不依赖仓库 .env 中的 App Secret）。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

_CLI_ENV = {
    **os.environ,
    "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1",
    "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1",
}


class LarkCliError(RuntimeError):
    pass


def lark_cli_path() -> str | None:
    return shutil.which("lark-cli")


def lark_cli_installed() -> bool:
    return lark_cli_path() is not None


def _run(args: list[str], *, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    exe = lark_cli_path()
    if not exe:
        raise LarkCliError("未找到 lark-cli；请先安装并完成 lark-cli config init")
    return subprocess.run(
        [exe, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_CLI_ENV,
        check=False,
    )


def _parse_json_stdout(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    text = (proc.stdout or "").strip()
    if not text:
        raise LarkCliError((proc.stderr or proc.stdout or "lark-cli 无输出").strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise LarkCliError(f"lark-cli 输出非 JSON: {text[:200]}") from e
    if proc.returncode != 0:
        detail = data.get("error") or data.get("message") or text
        raise LarkCliError(str(detail))
    return data if isinstance(data, dict) else {"data": data}


@dataclass
class LarkCliAuthSummary:
    installed: bool
    config_ok: bool
    bot_ready: bool
    hint: str
    raw: dict[str, Any] | None = None


def auth_summary() -> LarkCliAuthSummary:
    if not lark_cli_installed():
        return LarkCliAuthSummary(
            installed=False,
            config_ok=False,
            bot_ready=False,
            hint="安装 lark-cli 后执行：lark-cli config init --new",
        )
    try:
        data = _parse_json_stdout(_run(["auth", "status", "--json", "--verify"]))
    except LarkCliError as e:
        return LarkCliAuthSummary(
            installed=True,
            config_ok=False,
            bot_ready=False,
            hint=str(e),
        )
    identities = data.get("identities") or {}
    bot = identities.get("bot") if isinstance(identities, dict) else {}
    bot_status = ""
    if isinstance(bot, dict):
        bot_status = str(bot.get("status") or bot.get("tokenStatus") or "")
    verified = bool(data.get("verified"))
    bot_ready = verified and (
        not bot_status or bot_status.lower() in ("ok", "valid", "active", "ready")
    )
    hint = "Bot 凭证由 lark-cli 管理（config init）；发消息使用 --as bot"
    if not bot_ready:
        hint = "请完成 lark-cli config init，并在开发者后台为个人应用开通 IM Bot 权限"
    return LarkCliAuthSummary(
        installed=True,
        config_ok=verified,
        bot_ready=bot_ready,
        hint=hint,
        raw=data,
    )


def send_text_as_bot(*, chat_id: str = "", open_id: str = "", text: str) -> dict[str, Any]:
    if not text.strip():
        raise LarkCliError("消息正文为空")
    args = ["im", "+messages-send", "--as", "bot", "--text", text]
    if chat_id:
        args.extend(["--chat-id", chat_id])
    elif open_id:
        args.extend(["--user-id", open_id])
    else:
        raise LarkCliError("须指定 chat_id 或 open_id")
    return _parse_json_stdout(_run(args))
