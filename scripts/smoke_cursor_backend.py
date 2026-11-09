"""Cursor SDK 连通性 smoke（需 CURSOR_API_KEY；可选 GENI_STUDIO_CURSOR_SMOKE_RUN=1 跑短 completion）。"""

from __future__ import annotations

import os
import sys


def main() -> int:
    from geni_studio.config.env_loader import apply_env_file

    apply_env_file(
        override=os.environ.get("GENI_STUDIO_DOTENV_OVERRIDE", "1").strip().lower()
        in ("1", "true", "yes")
    )
    if not os.environ.get("CURSOR_API_KEY", "").strip():
        print("SKIP: 未设置 CURSOR_API_KEY", file=sys.stderr)
        return 2
    os.environ.pop("GENI_STUDIO_BACKEND", None)
    from geni_studio.backends.base import StubBackend, get_default_backend

    backend = get_default_backend()
    if isinstance(backend, StubBackend):
        try:
            from cursor_sdk import Cursor
            from cursor_sdk.errors import AuthenticationError, ConfigurationError

            from geni_studio.backends.cursor_backend import CursorBackend

            inst = CursorBackend()
            Cursor.me(client=inst._client, api_key=inst._api_key)
        except ConfigurationError as e:
            print(f"FAIL: Cursor Bridge 未就绪: {e}", file=sys.stderr)
            return 1
        except AuthenticationError as e:
            print(
                "FAIL: CURSOR_API_KEY 无效（Cursor 设置 → Account → User API Keys 更新）",
                file=sys.stderr,
            )
            print(f"detail: {e}", file=sys.stderr)
            return 1
        except ImportError as e:
            print(f"FAIL: 未安装 cursor-sdk: {e}", file=sys.stderr)
            return 1
        print("FAIL: 仍为 StubBackend（未知原因）", file=sys.stderr)
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
    if os.environ.get("GENI_STUDIO_CURSOR_SMOKE_RUN", "").strip() not in (
        "1",
        "true",
        "yes",
    ):
        print("hint: GENI_STUDIO_CURSOR_SMOKE_RUN=1 可触发 project_manager 短 completion")
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
