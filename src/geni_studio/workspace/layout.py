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
    base_branch: str = ""


def prepare_run_layout(
    target_root: Path,
    thread_id: str,
    *,
    on_current_branch: bool = False,
) -> RunLayout:
    target_root = target_root.resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    _ensure_git_repo(target_root)
    dot = target_root / ".geni_studio"
    dot.mkdir(parents=True, exist_ok=True)
    (dot / "runs").mkdir(parents=True, exist_ok=True)
    _ensure_gitignore(target_root)
    run_dir = dot / "runs" / thread_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if on_current_branch:
        branch = _branch_name(target_root)
        (run_dir / "base_branch.txt").write_text(branch + "\n", encoding="utf-8")
        (run_dir / "worktree.txt").write_text(os.fspath(target_root) + "\n", encoding="utf-8")
        return RunLayout(
            target_root=target_root,
            dot_dir=dot,
            worktree=target_root,
            run_dir=run_dir,
            base_branch=branch,
        )
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
    (run_dir / "worktree.txt").write_text(os.fspath(worktree) + "\n", encoding="utf-8")
    return RunLayout(target_root=target_root, dot_dir=dot, worktree=worktree, run_dir=run_dir)


def workspace_lock_root(workspace_path: str) -> Path | None:
    """本轮可写目录对应的目标仓库。当前分支模式的工作区就是仓库根。"""
    if not workspace_path.strip():
        return None
    path = Path(workspace_path)
    if path.parent.name == "worktrees" and path.parent.parent.name == ".geni_studio":
        return path.parent.parent.parent
    if (path / ".geni_studio").is_dir():
        return path
    return None


def run_dir_for_workspace(workspace_path: str, thread_id: str) -> Path | None:
    """产物目录。工作树在 `.geni_studio/worktrees` 下；当前分支模式在仓库根。"""
    if not workspace_path.strip() or not thread_id.strip():
        return None
    path = Path(workspace_path)
    if path.parent.name == "worktrees" and path.parent.parent.name == ".geni_studio":
        return path.parent.parent / "runs" / thread_id
    dot = path / ".geni_studio"
    if dot.is_dir():
        return dot / "runs" / thread_id
    return None


def commit_current_branch(workspace_path: str, base_branch: str, summary: str) -> str:
    """程序员在开工时的当前分支提交尚未提交的改动。不推送远端。"""
    path = Path(workspace_path)
    if not workspace_path.strip() or not _is_git_repo(path):
        raise WorkspaceError("工作区不是 git 仓库，不能提交。")
    expected = base_branch.strip()
    if not expected:
        raise WorkspaceError("这一轮没有记录开工分支，不能提交。")
    current = _branch_name(path)
    if current != expected:
        raise WorkspaceError(f"当前分支是 {current}，开工时是 {expected}。拒绝提交。")
    if (path / ".git" / "MERGE_HEAD").is_file():
        raise WorkspaceError("目标仓库已有未完成的合并，不能提交。")
    if not _user_status(path):
        return f"分支 {current} 没有未提交的改动，未创建新的提交。"
    add = subprocess.run(
        ["git", "-C", os.fspath(path), "add", "-A"],
        capture_output=True,
        text=True,
        check=False,
    )
    if add.returncode != 0:
        raise WorkspaceError((add.stderr or add.stdout or "git add 失败").strip())
    reset = subprocess.run(
        ["git", "-C", os.fspath(path), "reset", "-q", "--", ".geni_studio"],
        capture_output=True,
        text=True,
        check=False,
    )
    if reset.returncode != 0:
        raise WorkspaceError((reset.stderr or reset.stdout or "无法排除工厂运行目录。").strip())
    staged = subprocess.run(
        ["git", "-C", os.fspath(path), "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        check=False,
    )
    if staged.returncode != 0:
        raise WorkspaceError((staged.stderr or staged.stdout or "无法读取暂存内容。").strip())
    if not staged.stdout.strip():
        return f"分支 {current} 没有未提交的改动，未创建新的提交。"
    message = f"入库：{_commit_subject(summary)}\n\n人类已确认入库。程序员在当前分支提交本轮改动。\n"
    proc = subprocess.run(
        ["git", "-C", os.fspath(path), "commit", "-m", message],
        capture_output=True,
        text=True,
        check=False,
        env=_commit_env(path),
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "git commit 失败").strip()
        raise WorkspaceError(detail)
    sha = subprocess.run(
        ["git", "-C", os.fspath(path), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    short = sha.stdout.strip() or "HEAD"
    return f"已由程序员在分支 {current} 提交 {short}。"


def _branch_name(path: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", os.fspath(path), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    name = proc.stdout.strip()
    if proc.returncode != 0 or not name:
        raise WorkspaceError((proc.stderr or proc.stdout or "无法读取当前分支。").strip())
    if name == "HEAD":
        raise WorkspaceError("当前是分离头指针，自我改进需要一个分支。")
    return name


def _status_porcelain(path: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", os.fspath(path), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise WorkspaceError((proc.stderr or proc.stdout or "无法读取工作区状态。").strip())
    return proc.stdout.strip()


def _commit_subject(summary: str) -> str:
    text = " ".join(str(summary or "").split())
    if not text:
        text = "本轮已批准的改动"
    if len(text) > 50:
        text = text[:50].rstrip() + "…"
    return text


def _commit_env(path: Path) -> dict[str, str]:
    env = dict(os.environ)
    if not _git_config(path, "user.name"):
        env.setdefault("GIT_AUTHOR_NAME", "GeniStudio")
        env.setdefault("GIT_COMMITTER_NAME", "GeniStudio")
    if not _git_config(path, "user.email"):
        env.setdefault("GIT_AUTHOR_EMAIL", "geni_studio@local")
        env.setdefault("GIT_COMMITTER_EMAIL", "geni_studio@local")
    return env


def _git_config(path: Path, key: str) -> str:
    proc = subprocess.run(
        ["git", "-C", os.fspath(path), "config", key],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


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


def _ignores_geni_studio(text: str) -> bool:
    for raw in text.splitlines():
        item = raw.strip()
        if not item or item.startswith("#"):
            continue
        if item in {".geni_studio", ".geni_studio/"}:
            return True
    return False


def _user_status(path: Path) -> str:
    lines: list[str] = []
    for line in _status_porcelain(path).splitlines():
        entry = line[3:].strip().strip('"')
        if entry == ".geni_studio" or entry.startswith(".geni_studio/"):
            continue
        lines.append(line)
    return "\n".join(lines)


def _ensure_gitignore(path: Path) -> None:
    """已有提交的仓库写入 .git/info/exclude，避免改当前分支上的 .gitignore。"""
    line = ".geni_studio/\n"
    ignore = path / ".gitignore"
    exclude = path / ".git" / "info" / "exclude"
    tracked = ignore.read_text(encoding="utf-8") if ignore.is_file() else ""
    if _ignores_geni_studio(tracked):
        return
    if _has_commit(path) and exclude.parent.is_dir():
        current = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
        if _ignores_geni_studio(current):
            return
        with exclude.open("a", encoding="utf-8") as handle:
            if current and not current.endswith("\n"):
                handle.write("\n")
            handle.write(line)
        return
    with ignore.open("a", encoding="utf-8") as handle:
        if ignore.stat().st_size and not tracked.endswith("\n"):
            handle.write("\n")
        handle.write(line)


def _initial_commit(path: Path) -> None:
    _ensure_gitignore(path)
    subprocess.run(["git", "-C", os.fspath(path), "add", ".gitignore"], check=True)
    subprocess.run(
        ["git", "-C", os.fspath(path), "commit", "-q", "-m", "init GeniStudio target"],
        check=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "GeniStudio", "GIT_AUTHOR_EMAIL": "geni_studio@local", "GIT_COMMITTER_NAME": "GeniStudio", "GIT_COMMITTER_EMAIL": "geni_studio@local"},
    )
