"""改进提案：未批准不得改角色或流程，批准后留下版本记录。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


class ProposalError(ValueError):
    """提案状态不允许该操作。"""


def target_root_from_worktree(worktree: str) -> Path | None:
    path = Path(worktree)
    if path.parent.name == "worktrees" and path.parent.parent.name == ".auto_studio":
        return path.parent.parent.parent
    return None


def save_retro_proposal(worktree: str, summary: str) -> str:
    """把复盘提案写成 pending 文件。不修改角色或流程。"""
    root = target_root_from_worktree(worktree)
    if root is None:
        return ""
    proposal_id = f"retro-{path_name(worktree)}"
    save_proposal(
        root,
        proposal_id,
        target="roles/process_owner/role.md",
        summary=summary[:200],
        body="提案状态：pending。未经批准不得修改角色定义或流程。",
    )
    return proposal_id


def path_name(worktree: str) -> str:
    return Path(worktree).name


def proposal_path(root: Path, proposal_id: str) -> Path:
    return root / "evolution" / "proposals" / f"{proposal_id}.json"


def save_proposal(root: Path, proposal_id: str, *, target: str, summary: str, body: str) -> Path:
    path = proposal_path(root, proposal_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": proposal_id,
        "status": "pending",
        "target": target,
        "summary": summary,
        "body": body,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_proposal(root: Path, proposal_id: str) -> dict:
    path = proposal_path(root, proposal_id)
    if not path.is_file():
        raise ProposalError(f"没有提案 {proposal_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ProposalError(f"提案 {proposal_id} 不是对象")
    return data


def approve_proposal(root: Path, proposal_id: str, *, evidence: str) -> dict:
    data = load_proposal(root, proposal_id)
    if data.get("status") == "applied":
        raise ProposalError("已合入的提案不能再次批准")
    data["status"] = "approved"
    data["approved_at"] = datetime.now(UTC).isoformat()
    data["evidence"] = evidence
    proposal_path(root, proposal_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    ledger = root / "evolution" / "ledger.md"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    if not ledger.is_file():
        ledger.write_text("# 改进记录\n\n| 日期 | 提案 | 修改对象 | 证据 |\n|------|------|----------|------|\n", encoding="utf-8")
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(
            f"| {data['approved_at']} | {proposal_id} | {data.get('target')} | {evidence} |\n"
        )
    return data


def apply_proposal(root: Path, proposal_id: str) -> Path:
    data = load_proposal(root, proposal_id)
    if data.get("status") != "approved":
        raise ProposalError("未经批准不得修改角色定义或流程")
    target = root / str(data["target"])
    if not target.is_file():
        raise ProposalError(f"修改对象不存在: {target}")
    text = target.read_text(encoding="utf-8")
    addition = str(data.get("body") or "").rstrip() + "\n"
    if addition.strip() not in text:
        target.write_text(text.rstrip() + "\n\n" + addition, encoding="utf-8")
    data["status"] = "applied"
    proposal_path(root, proposal_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
