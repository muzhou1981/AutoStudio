"""将 lark-cli event consume 输出转发到 AutoStudio Webhook。"""

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
    req = urllib.request.Request(
        webhook_url,
        data=line.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[feishu-bridge] HTTP {e.code}: {body[:300]}", file=sys.stderr)


def _consume_loop(webhook_url: str, event_key: str, env: dict[str, str]) -> None:
    proc = subprocess.Popen(
        ["lark-cli", "event", "consume", event_key, "--as", "bot"],
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


def main() -> None:
    parser = argparse.ArgumentParser(description="飞书 event consume → AutoStudio Webhook")
    parser.add_argument(
        "--webhook",
        default=os.environ.get(
            "AUTO_STUDIO_FEISHU_WEBHOOK",
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
            args=(args.webhook, key, env),
            name=f"feishu-bridge:{key}",
            daemon=True,
        )
        t.start()
        threads.append(t)
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
