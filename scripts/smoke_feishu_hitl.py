"""飞书 HITL 联调 smoke：进程内 API E2E；--live 经 lark-cli 出站 Gate 卡片。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _api_e2e(base: str) -> int:
    payload = json.dumps(
        {"human_request": "feishu smoke", "scenario_key": "npu_operator"}
    ).encode()
    req = urllib.request.Request(
        f"{base.rstrip('/')}/api/runs",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        start = json.loads(resp.read().decode())
    tid = start["thread_id"]
    assert start.get("phase") == "awaiting_human", start
    webhook = {
        "header": {"event_type": "card.action.trigger"},
        "event": {
            "type": "card.action.trigger",
            "action_value": json.dumps(
                {
                    "thread_id": tid,
                    "hitl_action": "gate",
                    "gate_decision": "approved",
                }
            ),
        },
    }
    req2 = urllib.request.Request(
        f"{base.rstrip('/')}/api/webhooks/feishu",
        data=json.dumps(webhook).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req2, timeout=60) as resp:
        wh = json.loads(resp.read().decode())
    assert wh.get("ok") is True, wh
    assert wh.get("toast"), wh
    req3 = urllib.request.Request(
        f"{base.rstrip('/')}/api/runs/{tid}",
        method="GET",
    )
    with urllib.request.urlopen(req3, timeout=60) as resp:
        after = json.loads(resp.read().decode())
    assert after.get("phase") == "awaiting_human", after
    ah = after.get("awaiting_human") or {}
    assert ah.get("gate_id") == "gate_architecture_review", after
    print(f"OK: feishu_webhook_inbound thread={tid} -> {ah.get('gate_id')}")
    return 0


def _live_notify(base: str) -> int:
    open_id = os.environ.get("GENI_STUDIO_FEISHU_NOTIFY_OPEN_ID", "").strip()
    if not open_id:
        print("SKIP live: 未设置 GENI_STUDIO_FEISHU_NOTIFY_OPEN_ID", file=sys.stderr)
        return 2
    os.environ.setdefault("GENI_STUDIO_LARK_BACKEND", "lark_cli")
    payload = json.dumps(
        {
            "human_request": "feishu live card",
            "scenario_key": "npu_operator",
            "project_id": "",
        }
    ).encode()
    req = urllib.request.Request(
        f"{base.rstrip('/')}/api/runs",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        start = json.loads(resp.read().decode())
    tid = start["thread_id"]
    print(f"OK: live run started thread={tid};请在飞书点击批准或调用 card-action")
    print(f"  curl -X POST {base}/api/webhooks/feishu/card-action \\")
    print('    -H "Content-Type: application/json" \\')
    print(f'    -d \'{{"thread_id":"{tid}","gate_decision":"approved"}}\'')
    return 0


def main() -> int:
    from geni_studio.config.env_loader import apply_env_file

    apply_env_file(
        override=os.environ.get("GENI_STUDIO_DOTENV_OVERRIDE", "1").strip().lower()
        in ("1", "true", "yes")
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base",
        default=os.environ.get("GENI_STUDIO_WEB_BASE", "http://127.0.0.1:8765"),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="启动 Run 并尝试 lark-cli 出站卡片（需 Web 已运行 + open_id）",
    )
    args = parser.parse_args()
    try:
        if args.live:
            return _live_notify(args.base)
        return _api_e2e(args.base)
    except urllib.error.URLError as e:
        print(f"FAIL: 无法访问 {args.base} — {e}", file=sys.stderr)
        print("hint: 另开终端运行 geni-studio-web", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
