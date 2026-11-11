"""在目标工作树中执行允许的测试命令，并把输出当作验证证据。"""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from geni_studio.backends.cost import current_project_id
from geni_studio.config.context import ConfigError, factory_root, load_project_config

_ALLOWED_EXECUTABLES = {"pytest", "python", "python3", "go", "cargo", "npm"}


class TestCommandError(ValueError):
    """测试命令不在允许范围内。"""

    __test__ = False


@dataclass(frozen=True)
class TestCommandResult:
    __test__ = False
    argv: list[str]
    returncode: int
    transcript: str


def verified_report(
    state: dict, report: str, claimed_status: str = "pass", *, claim_binding: bool = False
) -> tuple[str, str]:
    """附上验证命令输出，并给出测试结论。

    执行了验证命令时以命令退出码为准；`claim_binding` 为真（测试工程师给出了结构化结论）时，
    结论为失败也判失败。真实后端未配置验证命令时视为缺少证据。
    """
    from geni_studio.backends.runner import role_is_simulated

    try:
        result = run_test_command(state)
    except (TestCommandError, subprocess.TimeoutExpired, OSError, ValueError) as exc:
        return f"{report}\n\n## 测试命令\n执行失败：{type(exc).__name__}: {exc}", "fail"
    if result is not None:
        ok = result.returncode == 0 and (claimed_status == "pass" or not claim_binding)
        return f"{report}\n\n{result.transcript}", "pass" if ok else "fail"
    if role_is_simulated("tester"):
        return f"{report}\n\n模拟验证（stub），未执行测试命令。", claimed_status
    return f"{report}\n\n未配置验证命令，缺少机器验证证据。", "fail"


def verification_config(state: dict) -> dict:
    """本轮的 `verification` 配置：冻结快照优先，其次项目配置。"""
    frozen = state.get("config_snapshot_effective")
    if isinstance(frozen, dict):
        raw = frozen.get("verification")
        return dict(raw) if isinstance(raw, dict) else {}
    project_id = str(state.get("project_id") or current_project_id())
    if not project_id.strip():
        return {}
    try:
        cfg, _ = load_project_config(factory_root(), project_id)
    except ConfigError:
        return {}
    raw = cfg.get("verification")
    return dict(raw) if isinstance(raw, dict) else {}


def _allowed_executables(cfg: dict) -> set[str]:
    extra = cfg.get("allow") or []
    if isinstance(extra, str):
        extra = [extra]
    return _ALLOWED_EXECUTABLES | {str(item).strip() for item in extra if str(item).strip()}


def resolve_test_command(state: dict) -> list[str] | None:
    frozen = state.get("config_snapshot_effective")
    default = frozen.get("_test_command", "") if isinstance(frozen, dict) else os.environ.get("GENI_STUDIO_TEST_COMMAND")
    cfg = verification_config(state)
    raw: object = state.get("test_command") or default or ""
    if not raw:
        raw = cfg.get("command") or ""
    if isinstance(raw, list):
        argv = [str(item) for item in raw]
    else:
        argv = shlex.split(str(raw).strip())
    if not argv:
        return None
    from geni_studio.workspace.policy import reject_remote_push

    reject_remote_push(argv)
    allowed = _allowed_executables(cfg)
    executable = Path(argv[0]).name
    if executable not in allowed:
        raise TestCommandError(
            f"测试命令必须以 {'、'.join(sorted(allowed))} 开头，拒绝: {executable}。"
            "需要其他可执行文件时，在项目 verification.allow 中声明。"
        )
    if any(token for token in argv if any(ch in token for ch in ";&|`$<>")):
        raise TestCommandError("测试命令不允许包含 shell 元字符；需要管道时请写成脚本并把解释器加入 allow")
    return argv


_SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
_SECRET_PREFIXES = ("LARK_", "CURSOR_", "OPENAI_", "ANTHROPIC_", "LANGSMITH_", "GENI_STUDIO_FEISHU_")


def scrubbed_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """验证命令的环境：去掉密钥类变量，避免被测代码或脚本读到工厂凭证。"""
    env = dict(os.environ if base is None else base)
    for name in list(env):
        upper = name.upper()
        if upper.startswith(_SECRET_PREFIXES) or any(marker in upper for marker in _SECRET_MARKERS):
            env.pop(name)
    return env


def sandboxed_argv(argv: list[str], *, workspace: Path, cwd: Path, sandbox: str) -> list[str]:
    if sandbox in {"", "none"}:
        return argv
    if sandbox != "bwrap":
        raise TestCommandError(f"未知的验证沙箱：{sandbox}（可选 none、bwrap）")
    import shutil

    bwrap = shutil.which("bwrap")
    if bwrap is None:
        raise TestCommandError("项目要求 bwrap 沙箱，但本机没有安装 bubblewrap。")
    ws = str(workspace.resolve())
    binds = ["--bind", ws, ws]
    git_dir = workspace / ".git"
    if git_dir.is_file():
        # 工作树的 .git 指向主仓库的 worktrees/<名称>，测试可能需要写索引。
        target = git_dir.read_text(encoding="utf-8").partition("gitdir:")[2].strip()
        if target and Path(target).is_dir():
            binds += ["--bind", target, target]
    return [
        bwrap,
        "--ro-bind", "/", "/",
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
        *binds,
        "--unshare-net",
        "--die-with-parent",
        "--chdir", str(cwd.resolve()),
        "--",
        *argv,
    ]


def assert_command_cwd(cwd: Path, workspace: Path) -> None:
    """工作目录必须落在本轮工作树内。"""
    if not str(workspace).strip():
        raise TestCommandError("没有本轮工作树，拒绝执行测试命令。")
    root = workspace.resolve()
    resolved = cwd.resolve()
    if resolved != root and root not in resolved.parents:
        raise TestCommandError(f"测试命令的工作目录必须在本轮工作树内：{workspace}")


def run_test_command(state: dict, *, timeout: float | None = None) -> TestCommandResult | None:
    argv = resolve_test_command(state)
    if argv is None:
        return None
    workspace = str(state.get("workspace_path") or "").strip()
    if not workspace:
        raise TestCommandError("没有本轮工作树，拒绝执行测试命令。")
    cwd = Path(workspace)
    assert_command_cwd(cwd, cwd)
    cfg = verification_config(state)
    if timeout is None:
        try:
            timeout = float(cfg.get("timeout_seconds") or 120)
        except (TypeError, ValueError) as exc:
            raise TestCommandError("verification.timeout_seconds 必须是数字") from exc
    sandbox = str(cfg.get("sandbox") or "none").strip().lower()
    proc = subprocess.run(
        sandboxed_argv(argv, workspace=cwd, cwd=cwd, sandbox=sandbox),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=scrubbed_env(),
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
