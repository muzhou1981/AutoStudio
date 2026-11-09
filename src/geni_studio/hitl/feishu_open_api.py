"""用应用凭据直连飞书开放平台发消息。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from geni_studio.hitl.lark_cli_client import LarkCliError


def tenant_access_token(app_id: str, app_secret: str) -> str:
    body = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode("utf-8")
    request = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise LarkCliError("飞书应用凭据无法换取访问令牌。") from exc
    token = str(payload.get("tenant_access_token") or "")
    if int(payload.get("code") or 0) != 0 or not token:
        raise LarkCliError("飞书应用凭据无法换取访问令牌。")
    return token


def send_interactive_via_tenant(
    *,
    app_id: str,
    app_secret: str,
    content_json: str,
    chat_id: str = "",
    open_id: str = "",
) -> None:
    if not content_json.strip():
        raise LarkCliError("卡片 JSON 为空")
    receive_id = chat_id or open_id
    receive_id_type = "chat_id" if chat_id else "open_id"
    if not receive_id:
        raise LarkCliError("须指定 chat_id 或 open_id")
    token = tenant_access_token(app_id, app_secret)
    body = json.dumps(
        {"receive_id": receive_id, "msg_type": "interactive", "content": content_json},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise LarkCliError("飞书消息发送失败。") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise LarkCliError("飞书消息发送失败。") from exc
    if int(payload.get("code") or 0) != 0:
        raise LarkCliError("飞书消息发送失败。")
