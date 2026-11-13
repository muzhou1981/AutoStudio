"""判断一轮的代码是否已经回到项目目录当前检出的分支。"""

from __future__ import annotations

from pathlib import Path

from geni_studio.workspace.gc import (
    BRANCH_PREFIX,
    _branch_exists,
    _current_branch,
    _git,
)


def current_branch(repo: Path) -> str:
    """仓库当前检出的分支；不是 git 仓库或处于分离头指针时返回空字符串。"""
    if not (repo / ".git").exists():
        return ""
    branch = _current_branch(repo)
    return "" if branch == "HEAD" else branch


def run_leftover(repo: Path, thread_id: str) -> str:
    """返回这一轮的代码尚未回到项目目录的原因；已经回到或不在工作树中运行时返回空字符串。"""
    worktree = repo / ".geni_studio" / "worktrees" / thread_id
    if worktree.is_dir():
        status = _git(worktree, "status", "--porcelain")
        if status.returncode == 0 and status.stdout.strip():
            return "工作树里有未提交的改动"
    branch = BRANCH_PREFIX + thread_id
    if not _branch_exists(repo, branch):
        return ""
    base = current_branch(repo)
    if not base:
        return ""
    ahead = _git(repo, "rev-list", "--count", f"{base}..{branch}")
    count = int(ahead.stdout.strip() or 0) if ahead.returncode == 0 else 0
    if count:
        return f"本轮分支有 {count} 个提交未合入 {base}"
    return ""
