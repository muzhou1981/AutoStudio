"""将 lark-cli event consume 输出转发到 auto_studio Webhook。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request


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


def main() -> None:
    parser = argparse.ArgumentParser(description="飞书 event consume → auto_studio Webhook")
    parser.add_argument(
        "--webhook",
        default=os.environ.get(
            "AUTO_STUDIO_FEISHU_WEBHOOK",
            "http://127.0.0.1:8765/api/webhooks/feishu",
        ),
    )
    parser.add_argument(
        "--event-key",
        default="card.action.trigger",
        help="lark-cli EventKey",
    )
    args = parser.parse_args()
    env = {
        **os.environ,
        "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1",
        "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1",
    }
    proc = subprocess.Popen(
        ["lark-cli", "event", "consume", args.event_key, "--as", "bot"],
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
        forward_line(args.webhook, line)
    proc.wait()


if __name__ == "__main__":
    main()
