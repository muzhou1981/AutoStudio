"""Cursor SDK 连通性 smoke（需 CURSOR_API_KEY；可选 AUTO_STUDIO_CURSOR_SMOKE_RUN=1 跑短 completion）。"""

from __future__ import annotations

import os
import sys


def main() -> int:
    if not os.environ.get("CURSOR_API_KEY", "").strip():
        print("SKIP: 未设置 CURSOR_API_KEY", file=sys.stderr)
        return 2
    os.environ.pop("AUTO_STUDIO_BACKEND", None)
    from auto_studio.backends.base import StubBackend, get_default_backend

    backend = get_default_backend()
    if isinstance(backend, StubBackend):
        print("FAIL: 仍为 StubBackend（Bridge 未就绪或 Cursor 初始化失败）", file=sys.stderr)
        return 1
    print(f"OK: backend={type(backend).__name__}")
    try:
        from cursor_sdk import Cursor
        from cursor_sdk.errors import AuthenticationError, CursorSDKError

        user = Cursor.me(client=backend._client, api_key=backend._api_key)  # type: ignore[attr-defined]
        print(f"OK: Cursor.me email={getattr(user, 'email', user)!s}"[:120])
    except AuthenticationError as e:
        print(f"WARN: CURSOR_API_KEY 校验失败: {e}", file=sys.stderr)
        return 1
    except CursorSDKError as e:
        print(f"WARN: Cursor SDK: {e}", file=sys.stderr)
        return 1
    if os.environ.get("AUTO_STUDIO_CURSOR_SMOKE_RUN", "").strip() not in (
        "1",
        "true",
        "yes",
    ):
        print("hint: AUTO_STUDIO_CURSOR_SMOKE_RUN=1 可触发 project_manager 短 completion")
        return 0
    out = backend.complete(
        role_name="project_manager",
        system_prompt="你是项目经理，回复一行 Markdown。",
        user_prompt="回复：SMOKE_OK",
    )
    print("completion:", out[:500])
    return 0 if out.strip() else 1


if __name__ == "__main__":
    raise SystemExit(main())
