"""自改进入口：桥接不可用时直接退出，避免再留下空工作树。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from geni_studio.backends.cursor_backend import ensure_lowercase_proxy
from geni_studio.workspace.self_improve import self_improve_block_reason

ROOT = Path(__file__).resolve().parents[1]
REQUEST = (
    "只做这一处改进：在 README.md 的本地开发一节末尾追加一行"
    "「自改进场景 self_improve 的改动只出现在 .geni_studio/worktrees，不合并到当前分支。」"
    "不要列出待澄清问题，不要改其他文件。"
)


def bridge_ready(timeout: float = 8) -> bool:
    probe = (
        "from geni_studio.config.env_loader import apply_env_file\n"
        "apply_env_file(override=True)\n"
        "import os\n"
        "os.environ['GENI_STUDIO_CURSOR_VERIFY']='0'\n"
        "os.environ.pop('GENI_STUDIO_BACKEND', None)\n"
        "from geni_studio.backends.cursor_backend import CursorBackend\n"
        "print(CursorBackend().complete(role_name='project_manager', system_prompt='只回复一行。', user_prompt='回复 BRIDGE_OK')[:20])\n"
    )
    ensure_lowercase_proxy()
    try:
        proc = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=ROOT,
            env={**os.environ, "GENI_STUDIO_CURSOR_VERIFY": "0"},
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False
    return proc.returncode == 0


def main() -> int:
    blocked = self_improve_block_reason(bridge_ready())
    if blocked is not None:
        print("Cursor 桥接未恢复，不创建新的工作树。", file=sys.stderr)
        return blocked
    env = {
        **os.environ,
        "GENI_STUDIO_WORKSPACE": "1",
        "GENI_STUDIO_ALLOW_FACTORY_TARGET": "1",
        "GENI_STUDIO_TARGET_ROOT": str(ROOT),
        "GENI_STUDIO_CURSOR_VERIFY": "0",
        "GENI_STUDIO_E2E_SCENARIO": "self_improve",
        "GENI_STUDIO_E2E_PROJECT": "",
        "GENI_STUDIO_E2E_MAX_STEPS": "20",
        "GENI_STUDIO_E2E_REQUEST": REQUEST,
    }
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "e2e_graph.py")], cwd=ROOT, env=env, check=False)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
