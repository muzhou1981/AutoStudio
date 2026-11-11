"""运行工作区的推送防护：落在 git 配置上，不依赖提示词。

- 启用 `extensions.worktreeConfig`，只在本工作区的 `config.worktree` 中设置；
- 每个已有远端的 `pushurl` 指向不可用地址（`--no-verify` 也无法绕过）；
- `core.hooksPath` 指向防护目录：`pre-push` 拒绝推送，其余钩子链接回原钩子。

当前分支模式下工作区就是用户仓库本身，用持有标记登记；最后一个持有的运行结束时恢复。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

DISABLED_PUSH_URL = "geni-studio-push-disabled:///"
_PRE_PUSH = "#!/bin/sh\necho 'GeniStudio：运行工作区禁止推送远端。' >&2\nexit 1\n"


def _git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", os.fspath(path), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _git_path(path: Path, name: str) -> Path:
    out = _git(path, "rev-parse", "--path-format=absolute", "--git-path", name).stdout.strip()
    return Path(out)


def _guard_dir(workspace: Path) -> Path:
    return _git_path(workspace, "geni-studio-guard")


def _original_hooks(workspace: Path) -> Path:
    configured = _git(workspace, "config", "--get", "core.hooksPath").stdout.strip()
    guard = _guard_dir(workspace) / "hooks"
    if configured and Path(configured).resolve() != guard.resolve():
        hooks = Path(configured)
        return hooks if hooks.is_absolute() else workspace / hooks
    common = Path(_git(workspace, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
    return common / "hooks"


def install(workspace: Path, holder: str = "") -> None:
    """为工作区装上推送防护；`holder` 非空时登记一个持有者（当前分支模式）。"""
    workspace = workspace.resolve()
    guard = _guard_dir(workspace)
    hooks = guard / "hooks"
    original = _original_hooks(workspace)
    hooks.mkdir(parents=True, exist_ok=True)
    if original.is_dir():
        for item in original.iterdir():
            target = hooks / item.name
            if item.name == "pre-push" or item.name.endswith(".sample") or target.exists():
                continue
            target.symlink_to(item.resolve())
    pre_push = hooks / "pre-push"
    pre_push.write_text(_PRE_PUSH, encoding="utf-8")
    pre_push.chmod(0o755)
    _git(workspace, "config", "extensions.worktreeConfig", "true")
    _git(workspace, "config", "--worktree", "core.hooksPath", os.fspath(hooks))
    for remote in _git(workspace, "remote").stdout.split():
        _git(workspace, "config", "--worktree", f"remote.{remote}.pushurl", DISABLED_PUSH_URL)
    if holder:
        holders = guard / "holders"
        holders.mkdir(parents=True, exist_ok=True)
        (holders / holder).touch()


def release(workspace: Path, holder: str) -> bool:
    """注销持有者；没有其他持有者时撤销防护。返回是否已撤销。"""
    workspace = workspace.resolve()
    if not workspace.is_dir():
        return False
    guard = _guard_dir(workspace)
    holders = guard / "holders"
    (holders / holder).unlink(missing_ok=True)
    if holders.is_dir() and any(holders.iterdir()):
        return False
    _git(workspace, "config", "--worktree", "--unset", "core.hooksPath")
    for remote in _git(workspace, "remote").stdout.split():
        _git(workspace, "config", "--worktree", "--unset", f"remote.{remote}.pushurl")
    return True


def is_guarded(workspace: Path) -> bool:
    hooks = _git(workspace, "config", "--get", "core.hooksPath").stdout.strip()
    return bool(hooks) and Path(hooks).resolve() == (_guard_dir(workspace.resolve()) / "hooks").resolve()
