"""对基准任务跑一轮并记下可比较的分数。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from auto_studio.hitl.service import GraphRunService
from auto_studio.verification.acceptance import extract_acceptance_ids
from auto_studio.workflows.default import graph


def load_task(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"基准任务不是 mapping: {path}")
    return data


def score_values(values: dict[str, Any], expected: list[str]) -> dict[str, Any]:
    spec = str(values.get("requirement_spec") or "")
    evidence = str(values.get("test_report") or "")
    present = extract_acceptance_ids(spec)
    covered = [ac for ac in expected if ac in evidence]
    return {
        "qa_status": values.get("qa_status") or "",
        "dev_retry_count": int(values.get("dev_retry_count") or 0),
        "acceptance_in_spec": present,
        "acceptance_covered": covered,
        "acceptance_gap": [ac for ac in expected if ac not in covered],
    }


def run_task(path: Path, *, test_command: str = "", max_steps: int = 12) -> dict[str, Any]:
    task = load_task(path)
    expected = [str(item) for item in task.get("expect_acceptance_ids") or []]
    svc = GraphRunService(graph)
    st = svc.start(
        human_request=str(task.get("human_request") or "").strip(),
        scenario_key=str(task.get("scenario_key") or "npu_operator"),
    )
    if test_command:
        svc._graph.update_state(
            svc._config(st.thread_id),
            {
                "test_command": test_command,
                "requirement_spec": "\n".join(expected),
            },
        )
    for _ in range(max_steps):
        st = svc.status(st.thread_id)
        if st.phase in ("completed", "rejected", "stopped"):
            break
        if st.phase == "awaiting_human" and st.awaiting_human and st.awaiting_human.kind == "gate":
            st = svc.submit_hitl(st.thread_id, gate_decision="approved", channel="benchmark")
            continue
        break
    score = score_values(st.values, expected)
    score["thread_id"] = st.thread_id
    score["phase"] = st.phase
    score["task_id"] = task.get("id")
    return score


def write_score(score: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(score, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def improved(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return len(after.get("acceptance_gap") or []) < len(before.get("acceptance_gap") or [])
