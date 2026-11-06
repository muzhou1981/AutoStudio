"""在目标工作树中执行允许的测试命令，并把输出当作验证证据。"""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from auto_studio.backends.cost import current_project_id
from auto_studio.config.context import ConfigError, factory_root, load_project_config

_ALLOWED_EXECUTABLES = {"pytest", "python", "python3", "go", "cargo", "npm"}


class TestCommandError(ValueError):
    """测试命令不在允许范围内。"""


@dataclass(frozen=True)
class TestCommandResult:
    argv: list[str]
    returncode: int
    transcript: str


def resolve_test_command(state: dict) -> list[str] | None:
    raw = str(state.get("test_command") or os.environ.get("AUTO_STUDIO_TEST_COMMAND") or "").strip()
    if not raw:
        raw = _command_from_project(str(state.get("project_id") or current_project_id()))
    if not raw:
        return None
    argv = shlex.split(raw)
    if not argv:
        return None
    from auto_studio.workspace.policy import reject_remote_push

    reject_remote_push(argv)
    executable = Path(argv[0]).name
    if executable not in _ALLOWED_EXECUTABLES:
        raise TestCommandError(
            f"测试命令必须以 {'、'.join(sorted(_ALLOWED_EXECUTABLES))} 开头，拒绝: {executable}"
        )
    if any(token for token in argv if any(ch in token for ch in ";&|`$<>")):
        raise TestCommandError("测试命令不允许包含 shell 元字符")
    return argv


def run_test_command(state: dict, *, timeout: float = 120) -> TestCommandResult | None:
    argv = resolve_test_command(state)
    if argv is None:
        return None
    cwd = str(state.get("workspace_path") or "").strip() or os.getcwd()
    proc = subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    transcript = "\n".join(
        [
            "## 测试命令",
            "```",
            " ".join(argv),
            f"exit={proc.returncode}",
            (proc.stdout or "")[-4000:],
            (proc.stderr or "")[-2000:],
            "```",
        ]
    )
    return TestCommandResult(argv=argv, returncode=proc.returncode, transcript=transcript)


def _command_from_project(project_id: str) -> str:
    if not project_id.strip():
        return ""
    try:
        cfg, _ = load_project_config(factory_root(), project_id)
    except ConfigError:
        return ""
    verification = cfg.get("verification")
    if not isinstance(verification, dict):
        return ""
    return str(verification.get("command") or "").strip()
