"""把 Run 图状态中的产物全文写到目标项目 `.geni_studio/runs/<thread_id>/artifacts/`。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ARTIFACT_KEYS = (
    "requirement_spec",
    "testability_review",
    "test_cases",
    "test_report",
    "config_plan",
    "baseline_log",
    "config_baseline",
    "config_retro",
    "budget_plan",
    "cost_report",
    "ux_spec",
    "ui_spec",
    "visual_assets",
    "architecture_design",
    "task_plan",
    "code_change",
    "land_record",
    "change_request",
    "review_report",
    "qa_report",
    "delivery_report",
    "retro_report",
    "process_proposals",
    "config_proposals",
    "run_record",
    "hitl_audit_log",
    "human_request",
)


def persist_values(*, run_dir: Path, thread_id: str, phase: str, values: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    folder = run_dir / "artifacts"
    folder.mkdir(exist_ok=True)
    written: list[str] = []
    gaps: list[str] = []
    from geni_studio.config.context import factory_root
    from geni_studio.verification.template_check import missing_headings

    templates = factory_root() / "templates" / "artifacts"
    extra = values.get("extra_artifacts")
    extra_keys = [key for key in (extra if isinstance(extra, dict) else {}) if key not in ARTIFACT_KEYS]
    for key in [*ARTIFACT_KEYS, *extra_keys]:
        text = values.get(key) if key in ARTIFACT_KEYS else extra.get(key)
        if not isinstance(text, str) or not text.strip():
            continue
        name = f"{key}.md"
        (folder / name).write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        written.append(f"artifacts/{name}")
        template = templates / f"{key}.md"
        if template.is_file():
            missing = missing_headings(template.read_text(encoding="utf-8"), text)
            if missing:
                gaps.append(f"{key}: " + "；".join(missing))
    (run_dir / "template_gaps.md").write_text(
        ("\n".join(gaps) + "\n") if gaps else "无缺失章节。\n",
        encoding="utf-8",
    )
    meta = {
        "thread_id": thread_id,
        "phase": phase,
        "workspace_path": str(values.get("workspace_path") or ""),
        "files": written,
        "artifact_meta": values.get("artifact_meta") or {},
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
