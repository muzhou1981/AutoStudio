"""目标项目 `.geni_studio` 与独立 git 工作树。"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from geni_studio.config.context import factory_root


class WorkspaceError(RuntimeError):
    """无法准备目标项目工作区。"""


def workspace_enabled() -> bool:
    raw = os.environ.get("GENI_STUDIO_WORKSPACE", "1").strip().lower()
    return raw not in ("0", "false", "no")


def _expand_workspace(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = factory_root() / path
    return path.resolve()


def _project_workspace(project_id: str) -> str:
    try:
        from geni_studio.config.registry import project_workspace
    except ImportError:
        return ""
    return project_workspace(project_id)


def resolve_target_root(project_id: str = "") -> Path:
    """待开发项目目录。项目工作区优先于环境变量，再退回 workspaces/项目名。"""
    raw = _project_workspace(project_id) if project_id.strip() else ""
    if not raw:
        raw = os.environ.get("GENI_STUDIO_TARGET_ROOT", "").strip()
    if raw:
        return _expand_workspace(raw)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (project_id or "_default"))
    return (factory_root() / "workspaces" / safe).resolve()


def workspace_config_error(raw: str) -> str | None:
    """空字符串表示不配置。返回给人看的错误，没有问题则返回 None。"""
    text = raw.strip()
    if not text:
        return None
    path = _expand_workspace(text)
    if path == factory_root().resolve() and os.environ.get(
        "GENI_STUDIO_ALLOW_FACTORY_TARGET", ""
    ).strip().lower() not in ("1", "true", "yes"):
        return "工作区不能填工厂仓库本身。"
    if path.is_file():
        return "工作区要填目录，不能是文件。"
    if path.exists() and any(path.iterdir()) and not _is_git_repo(path):
        return "这个目录不是 git 仓库。换一个已有仓库，或先保存到空目录。"
    return None


@dataclass(frozen=True)
class RunLayout:
    target_root: Path
    dot_dir: Path
    worktree: Path
    run_dir: Path


def prepare_run_layout(target_root: Path, thread_id: str) -> RunLayout:
    target_root = target_root.resolve()
    if target_root == factory_root().resolve() and os.environ.get(
        "GENI_STUDIO_ALLOW_FACTORY_TARGET", ""
    ).strip().lower() not in ("1", "true", "yes"):
        raise WorkspaceError(
            "目标目录是工厂仓库。递归改进自身时请设置 GENI_STUDIO_ALLOW_FACTORY_TARGET=1，"
            "改动只进入 .geni_studio/worktrees。"
        )
    target_root.mkdir(parents=True, exist_ok=True)
    _ensure_git_repo(target_root)
    dot = target_root / ".geni_studio"
    dot.mkdir(parents=True, exist_ok=True)
    (dot / "runs").mkdir(parents=True, exist_ok=True)
    _ensure_gitignore(target_root)
    worktree = dot / "worktrees" / thread_id
    if not worktree.exists():
        branch = f"geni-studio/{thread_id}"
        proc = subprocess.run(
            ["git", "-C", os.fspath(target_root), "worktree", "add", "-b", branch, os.fspath(worktree)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise WorkspaceError((proc.stderr or proc.stdout or "git worktree add 失败").strip())
    run_dir = dot / "runs" / thread_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "worktree.txt").write_text(os.fspath(worktree) + "\n", encoding="utf-8")
    return RunLayout(target_root=target_root, dot_dir=dot, worktree=worktree, run_dir=run_dir)


def _is_git_repo(path: Path) -> bool:
    proc = subprocess.run(
        ["git", "-C", os.fspath(path), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def _ensure_git_repo(path: Path) -> None:
    if _is_git_repo(path):
        if not _has_commit(path):
            _initial_commit(path)
        return
    if any(path.iterdir()):
        raise WorkspaceError(f"目标目录不是 git 仓库，拒绝自动初始化: {path}")
    subprocess.run(["git", "-C", os.fspath(path), "init", "-q"], check=True)
    _initial_commit(path)


def _has_commit(path: Path) -> bool:
    proc = subprocess.run(
        ["git", "-C", os.fspath(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def _ensure_gitignore(path: Path) -> None:
    """已有提交的仓库写入 .git/info/exclude，避免改当前分支上的 .gitignore。"""
    line = ".geni_studio/\n"
    ignore = path / ".gitignore"
    exclude = path / ".git" / "info" / "exclude"
    tracked = ignore.read_text(encoding="utf-8") if ignore.is_file() else ""
    if ".geni_studio/" in tracked:
        return
    if _has_commit(path) and exclude.parent.is_dir():
        current = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
        if ".geni_studio/" in current:
            return
        with exclude.open("a", encoding="utf-8") as handle:
            if current and not current.endswith("\n"):
                handle.write("\n")
            handle.write(line)
        return
    with ignore.open("a", encoding="utf-8") as handle:
        if ignore.stat().st_size and not tracked.endswith("\n"):
            handle.write("\n")
        handle.write(".geni_studio/worktrees/\n")


def _initial_commit(path: Path) -> None:
    _ensure_gitignore(path)
    keep = path / ".geni_studio" / ".gitkeep"
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.touch()
    subprocess.run(["git", "-C", os.fspath(path), "add", ".gitignore", ".geni_studio/.gitkeep"], check=True)
    subprocess.run(
        ["git", "-C", os.fspath(path), "commit", "-q", "-m", "init GeniStudio target"],
        check=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "GeniStudio", "GIT_AUTHOR_EMAIL": "geni_studio@local", "GIT_COMMITTER_NAME": "GeniStudio", "GIT_COMMITTER_EMAIL": "geni_studio@local"},
    )
