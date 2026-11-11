"""将 lark-cli event consume 输出转发到 GeniStudio Webhook。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request

DEFAULT_EVENT_KEYS = ("card.action.trigger", "im.message.receive_v1")


def forward_line(webhook_url: str, line: str) -> None:
    line = line.strip()
    if not line:
        return
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("GENI_STUDIO_FEISHU_WEBHOOK_TOKEN", "").strip()
    if token:
        headers["X-Geni-Studio-Webhook-Token"] = token
    req = urllib.request.Request(
        webhook_url,
        data=line.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[feishu-bridge] HTTP {e.code}: {body[:300]}", file=sys.stderr)


def _consume_loop(webhook_url: str, event_key: str, env: dict[str, str], lark_cli: str) -> None:
    proc = subprocess.Popen(
        [lark_cli, "event", "consume", event_key, "--as", "bot"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        text=True,
        env=env,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        try:
            json.loads(line)
        except json.JSONDecodeError:
            continue
        forward_line(webhook_url, line)
    proc.wait()


_bridge_started = False


def start_background() -> None:
    """在 Web 进程里消费飞书事件。仅当 GENI_STUDIO_FEISHU_BRIDGE=1 且本机有 lark-cli。"""
    from geni_studio.hitl.lark_cli_client import lark_cli_path

    global _bridge_started
    if os.environ.get("GENI_STUDIO_FEISHU_BRIDGE", "").strip() != "1":
        return
    if _bridge_started:
        return
    lark_cli = lark_cli_path()
    if not lark_cli:
        print(
            "[feishu-bridge] 未启动：找不到 lark-cli（交互终端有 nvm 时，"
            "Web 进程 PATH 可能不含它；可设 GENI_STUDIO_LARK_CLI_PATH 或把 lark-cli 链到 ~/bin）",
            file=sys.stderr,
        )
        return
    _bridge_started = True
    if not os.environ.get("GENI_STUDIO_FEISHU_WEBHOOK_TOKEN", "").strip():
        import secrets

        os.environ["GENI_STUDIO_FEISHU_WEBHOOK_TOKEN"] = secrets.token_urlsafe(32)
    webhook = os.environ.get("GENI_STUDIO_FEISHU_WEBHOOK", "http://127.0.0.1:8765/api/webhooks/feishu")
    env = {
        **os.environ,
        "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1",
        "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1",
    }
    for key in DEFAULT_EVENT_KEYS:
        threading.Thread(
            target=_consume_loop,
            args=(webhook, key, env, lark_cli),
            name=f"feishu-bridge:{key}",
            daemon=True,
        ).start()


def main() -> None:
    from geni_studio.config.env_loader import apply_env_file
    from geni_studio.hitl.lark_cli_client import lark_cli_path

    apply_env_file()
    lark_cli = lark_cli_path()
    if not lark_cli:
        print("[feishu-bridge] 找不到 lark-cli", file=sys.stderr)
        raise SystemExit(1)
    if not os.environ.get("GENI_STUDIO_FEISHU_WEBHOOK_TOKEN", "").strip():
        print("[feishu-bridge] 独立运行须设置 GENI_STUDIO_FEISHU_WEBHOOK_TOKEN，并与 Web 进程一致", file=sys.stderr)
        raise SystemExit(1)
    parser = argparse.ArgumentParser(description="飞书 event consume → GeniStudio Webhook")
    parser.add_argument(
        "--webhook",
        default=os.environ.get(
            "GENI_STUDIO_FEISHU_WEBHOOK",
            "http://127.0.0.1:8765/api/webhooks/feishu",
        ),
    )
    parser.add_argument(
        "--event-key",
        action="append",
        default=[],
        help="lark-cli EventKey，可重复；默认 card + IM 文本",
    )
    args = parser.parse_args()
    keys = args.event_key or list(DEFAULT_EVENT_KEYS)
    env = {
        **os.environ,
        "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1",
        "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1",
    }
    threads: list[threading.Thread] = []
    for key in keys:
        t = threading.Thread(
            target=_consume_loop,
            args=(args.webhook, key, env, lark_cli),
            name=f"feishu-bridge:{key}",
            daemon=True,
        )
        t.start()
        threads.append(t)
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
