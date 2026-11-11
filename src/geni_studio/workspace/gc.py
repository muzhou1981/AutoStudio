"""回收运行留下的工作树、分支与运行目录。

已合入开工分支的 `geni-studio/<thread_id>` 分支才删除；未合入的分支保留，避免丢失提交。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from geni_studio.workspace.layout import run_dir_for_workspace, workspace_lock_root

BRANCH_PREFIX = "geni-studio/"


@dataclass
class GcReport:
    removed_worktrees: list[str] = field(default_factory=list)
    removed_run_dirs: list[str] = field(default_factory=list)
    deleted_branches: list[str] = field(default_factory=list)
    kept_branches: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def merge(self, other: GcReport) -> None:
        self.removed_worktrees += other.removed_worktrees
        self.removed_run_dirs += other.removed_run_dirs
        self.deleted_branches += other.deleted_branches
        self.kept_branches += other.kept_branches
        self.errors += other.errors

    def lines(self) -> list[str]:
        out = [f"移除工作树 {item}" for item in self.removed_worktrees]
        out += [f"移除运行目录 {item}" for item in self.removed_run_dirs]
        out += [f"删除已合入分支 {item}" for item in self.deleted_branches]
        out += [f"保留未合入分支 {item}" for item in self.kept_branches]
        out += [f"失败 {item}" for item in self.errors]
        return out


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", os.fspath(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _current_branch(repo: Path) -> str:
    proc = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _branch_exists(repo: Path, branch: str) -> bool:
    return _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0


def _is_merged(repo: Path, branch: str, base: str) -> bool:
    if not base or base == "HEAD":
        return False
    return _git(repo, "merge-base", "--is-ancestor", branch, base).returncode == 0


def _drop_branch(repo: Path, branch: str, report: GcReport, dry_run: bool = False) -> None:
    if not _branch_exists(repo, branch):
        return
    base = _current_branch(repo)
    if not _is_merged(repo, branch, base):
        report.kept_branches.append(f"{repo}:{branch}")
        return
    if dry_run:
        report.deleted_branches.append(f"{repo}:{branch}")
        return
    proc = _git(repo, "branch", "-D", branch)
    if proc.returncode == 0:
        report.deleted_branches.append(f"{repo}:{branch}")
    else:
        report.errors.append(f"{repo}:{branch} {proc.stderr.strip()}")


def _drop_worktree(repo: Path, worktree: Path, report: GcReport, dry_run: bool = False) -> None:
    if not worktree.exists():
        return
    if dry_run:
        report.removed_worktrees.append(os.fspath(worktree))
        return
    proc = _git(repo, "worktree", "remove", "--force", os.fspath(worktree))
    if proc.returncode != 0:
        shutil.rmtree(worktree, ignore_errors=True)
        _git(repo, "worktree", "prune")
    if worktree.exists():
        report.errors.append(f"{worktree} {proc.stderr.strip()}")
    else:
        report.removed_worktrees.append(os.fspath(worktree))


def _drop_run_dir(run_dir: Path, report: GcReport, dry_run: bool = False) -> None:
    if run_dir.is_dir():
        if dry_run:
            report.removed_run_dirs.append(os.fspath(run_dir))
            return
        shutil.rmtree(run_dir, ignore_errors=True)
        report.removed_run_dirs.append(os.fspath(run_dir))


def _drop_parallel_leftovers(repo: Path, thread_id: str, report: GcReport, dry_run: bool = False) -> None:
    """并行支路的快照工作树与本轮的工作树锁文件。"""
    folder = repo / ".geni_studio" / "branches" / thread_id
    if folder.is_dir():
        for path in sorted(folder.iterdir()):
            _drop_worktree(repo, path, report, dry_run)
        if not dry_run:
            shutil.rmtree(folder, ignore_errors=True)
    lock = repo / ".geni_studio" / "locks" / f"{thread_id}.lock"
    if lock.is_file() and not dry_run:
        lock.unlink(missing_ok=True)


def remove_run_workspace(workspace_path: str, thread_id: str) -> GcReport:
    """删除一轮时回收它的工作树、运行目录与已合入的分支。当前分支模式不动仓库本身。"""
    report = GcReport()
    repo = workspace_lock_root(workspace_path)
    run_dir = run_dir_for_workspace(workspace_path, thread_id)
    if repo is None:
        return report
    worktree = repo / ".geni_studio" / "worktrees" / thread_id
    if Path(workspace_path).resolve() == repo.resolve():
        from geni_studio.workspace.push_guard import release

        release(repo, thread_id)
    _drop_worktree(repo, worktree, report)
    _drop_parallel_leftovers(repo, thread_id, report)
    _git(repo, "worktree", "prune")
    _drop_branch(repo, BRANCH_PREFIX + thread_id, report)
    if run_dir is not None:
        _drop_run_dir(run_dir, report)
    return report


def collect_garbage(repo: Path, live_threads: set[str], *, dry_run: bool = False) -> GcReport:
    """清理一个目标仓库中不属于任何现存运行的工作树、运行目录与已合入分支。"""
    report = GcReport()
    repo = repo.resolve()
    dot = repo / ".geni_studio"
    if not dot.is_dir():
        return report
    if not dry_run:
        _git(repo, "worktree", "prune")
    worktrees = dot / "worktrees"
    if worktrees.is_dir():
        for path in sorted(worktrees.iterdir()):
            if path.is_dir() and path.name not in live_threads:
                _drop_worktree(repo, path, report, dry_run)
    branches = dot / "branches"
    if branches.is_dir():
        for path in sorted(branches.iterdir()):
            if path.is_dir() and path.name not in live_threads:
                _drop_parallel_leftovers(repo, path.name, report, dry_run)
    runs = dot / "runs"
    if runs.is_dir():
        for path in sorted(runs.iterdir()):
            if path.is_dir() and path.name not in live_threads and path.name != "inbox":
                _drop_run_dir(path, report, dry_run)
    listed = _git(repo, "for-each-ref", "--format=%(refname:short)", f"refs/heads/{BRANCH_PREFIX}")
    for branch in listed.stdout.split():
        if branch.removeprefix(BRANCH_PREFIX) not in live_threads:
            _drop_branch(repo, branch, report, dry_run)
    return report


def candidate_repos(root: Path) -> list[Path]:
    """工厂已知的目标仓库：各项目配置的工作区、`GENI_STUDIO_TARGET_ROOT` 与 `workspaces/` 下的目录。"""
    from geni_studio.config.registry import list_projects, project_workspace
    from geni_studio.workspace.layout import resolve_target_root

    found: list[Path] = []
    for project in list_projects(root):
        if project_workspace(project.project_id, root):
            found.append(resolve_target_root(project.project_id))
    env_root = os.environ.get("GENI_STUDIO_TARGET_ROOT", "").strip()
    if env_root:
        found.append(resolve_target_root(""))
    workspaces = root / "workspaces"
    if workspaces.is_dir():
        found += [path for path in sorted(workspaces.iterdir()) if path.is_dir()]
    unique: list[Path] = []
    for path in found:
        resolved = path.resolve()
        if resolved not in unique and (resolved / ".geni_studio").is_dir():
            unique.append(resolved)
    return unique
