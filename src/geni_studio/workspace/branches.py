"""并行支路的快照工作树：分叉时从本轮工作区当前内容建快照，汇合时三方合并回本轮工作区。"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from geni_studio.workspace.layout import WorkspaceError

_IDENTITY = {
    "GIT_AUTHOR_NAME": "geni-studio",
    "GIT_AUTHOR_EMAIL": "geni-studio@localhost",
    "GIT_COMMITTER_NAME": "geni-studio",
    "GIT_COMMITTER_EMAIL": "geni-studio@localhost",
}


def _git(cwd: Path, *args: str, env: dict[str, str] | None = None, check: bool = True, stdin: str | None = None):
    proc = subprocess.run(
        ["git", "-C", os.fspath(cwd), *args],
        capture_output=True,
        text=True,
        input=stdin,
        env={**os.environ, **_IDENTITY, **(env or {})},
        check=False,
    )
    if check and proc.returncode != 0:
        raise WorkspaceError((proc.stderr or proc.stdout or f"git {args[0]} 失败").strip())
    return proc


def _tree_commit(worktree: Path, parent: str, message: str) -> str:
    """把工作区当前内容（含未跟踪、遵守 .gitignore）写成一个提交，不改动工作区的索引与分支。"""
    with tempfile.TemporaryDirectory() as tmp:
        env = {"GIT_INDEX_FILE": os.path.join(tmp, "index")}
        _git(worktree, "read-tree", parent, env=env)
        _git(worktree, "add", "-A", env=env)
        tree = _git(worktree, "write-tree", env=env).stdout.strip()
    return _git(worktree, "commit-tree", tree, "-p", parent, "-m", message).stdout.strip()


def snapshot(worktree: Path) -> str:
    head = _git(worktree, "rev-parse", "HEAD").stdout.strip()
    return _tree_commit(worktree, head, "geni-studio parallel snapshot")


def branch_root(repo: Path, thread_id: str) -> Path:
    return repo / ".geni_studio" / "branches" / thread_id


def add_branch_worktree(repo: Path, thread_id: str, name: str, commit: str) -> Path:
    path = branch_root(repo, thread_id) / name
    if path.exists():
        remove_branch_worktree(repo, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "--detach", os.fspath(path), commit)
    from geni_studio.workspace.push_guard import install

    install(path)
    return path


def branch_changes(branch: Path, base: str) -> tuple[str, list[tuple[str, int, int]]]:
    """支路相对快照的补丁与逐文件增删行数；二进制文件的行数记为 0。"""
    head = _tree_commit(branch, base, "geni-studio parallel branch")
    patch = _git(branch, "diff", "--binary", base, head).stdout
    stats: list[tuple[str, int, int]] = []
    for line in _git(branch, "diff", "--numstat", base, head).stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            added, removed, name = parts
            stats.append((name, int(added) if added.isdigit() else 0, int(removed) if removed.isdigit() else 0))
    return patch, stats


def merge_back(worktree: Path, branch: Path, base: str) -> list[str]:
    """把支路相对快照的改动三方合并进本轮工作区；返回冲突文件，失败而无冲突文件时返回错误说明。"""
    head = _tree_commit(branch, base, "geni-studio parallel branch")
    patch = _git(worktree, "diff", "--binary", base, head).stdout
    if not patch.strip():
        return []
    _git(worktree, "add", "-A")
    applied = _git(worktree, "apply", "--3way", "--binary", "-", stdin=patch, check=False)
    conflicts: list[str] = []
    if applied.returncode != 0:
        listed = _git(worktree, "diff", "--name-only", "--diff-filter=U", check=False).stdout
        conflicts = [line for line in listed.splitlines() if line.strip()]
        if not conflicts:
            conflicts = [(applied.stderr or applied.stdout or "git apply 失败").strip()]
    _git(worktree, "reset", "-q", check=False)
    return conflicts


def remove_branch_worktree(repo: Path, path: Path) -> None:
    proc = _git(repo, "worktree", "remove", "--force", os.fspath(path), check=False)
    if proc.returncode != 0 and path.exists():
        shutil.rmtree(path, ignore_errors=True)
        _git(repo, "worktree", "prune", check=False)
