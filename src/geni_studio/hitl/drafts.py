"""尚未启动的 Run 草稿，保存目标、节点工具与角色模型/推理设置，不进入图。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

from geni_studio.config.context import factory_root
from geni_studio.hitl.run_name import assign_run_name, clean_run_name
from geni_studio.hitl.service import HitlError, RunConflict, RunNotFound

_DRAFT_ID = re.compile(r"^[0-9a-f]{32}$")
_MAX_REQUEST = 20_000


def drafts_dir() -> Path:
    path = factory_root() / "runs" / "drafts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(draft_id: str) -> Path:
    if not _DRAFT_ID.fullmatch(draft_id):
        raise RunNotFound("这份 Run 配置无法识别。")
    return drafts_dir() / f"{draft_id}.json"


def _read(draft_id: str) -> dict:
    path = _path(draft_id)
    if not path.is_file():
        raise RunNotFound(f"未知 Run 配置 {draft_id}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunNotFound(f"未知 Run 配置 {draft_id}") from exc
    if not isinstance(data, dict):
        raise RunNotFound(f"未知 Run 配置 {draft_id}")
    return data


def load_draft(draft_id: str) -> dict:
    data = _read(draft_id)
    data["draft_id"] = draft_id
    data["phase"] = "saved"
    data["kind"] = "draft"
    return data


def list_drafts(*, project_id: str = "") -> list[dict]:
    want = project_id.strip()
    rows: list[tuple[float, dict]] = []
    root = drafts_dir()
    for path in root.glob("*.json"):
        draft_id = path.stem
        if not _DRAFT_ID.fullmatch(draft_id):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        pid = str(data.get("project_id") or "")
        if want and pid != want:
            continue
        name = str(data.get("run_name") or draft_id)
        mtime = path.stat().st_mtime
        rows.append(
            (
                mtime,
                {
                    "updated_at": mtime,
                    "thread_id": draft_id,
                    "draft_id": draft_id,
                    "run_name": name,
                    "phase": "saved",
                    "project_id": pid,
                    "current": "",
                    "kind": "draft",
                },
            )
        )
    rows.sort(key=lambda item: item[0], reverse=True)
    return [row for _mtime, row in rows]


def taken_draft_names(project_id: str, *, except_id: str = "") -> set[str]:
    names: set[str] = set()
    for row in list_drafts(project_id=project_id):
        if row["draft_id"] == except_id:
            continue
        if row["run_name"]:
            names.add(row["run_name"])
    return names


def save_draft(
    *,
    draft_id: str = "",
    project_id: str,
    run_name: str,
    human_request: str,
    node_tools: dict[str, dict[str, list[str]]] | None = None,
    taken_names: set[str] | None = None,
    attachments: list[str] | None = None,
    role_models: dict[str, str] | None = None,
    role_reasoning_efforts: dict[str, str] | None = None,
    role_fast_modes: dict[str, str] | None = None,
    role_model_params: dict[str, dict[str, str]] | None = None,
) -> dict:
    from geni_studio.backends.reasoning import (
        clean_role_fast_modes,
        clean_role_model_params,
        clean_role_reasoning_efforts,
    )

    efforts = clean_role_reasoning_efforts(role_reasoning_efforts)
    fast_modes = clean_role_fast_modes(role_fast_modes)
    model_params = clean_role_model_params(role_model_params)
    pid = project_id.strip()
    if not pid:
        raise HitlError("先选择项目。")
    if len(pid) > 120:
        raise HitlError("项目标识无法识别。")
    request = str(human_request or "").strip()
    if len(request) > _MAX_REQUEST:
        raise HitlError("交付目标过长。")
    clean_run_name(run_name)
    existing_id = draft_id.strip()
    if existing_id:
        _read(existing_id)
    else:
        existing_id = uuid4().hex
    taken = set(taken_names or set())
    taken |= taken_draft_names(pid, except_id=existing_id)
    name = assign_run_name(pid, run_name, taken)
    from geni_studio.hitl.attachments import load_upload

    files = []
    for upload_id in attachments or []:
        item = load_upload(upload_id)
        files.append({"id": item["id"], "name": item["name"], "size": item["size"]})
    payload = {
        "project_id": pid,
        "run_name": name,
        "human_request": request,
        "node_tools": node_tools or {},
        "attachments": files,
        "role_models": role_models or {},
        "role_reasoning_efforts": efforts,
        "role_fast_modes": fast_modes,
        "role_model_params": model_params,
    }
    _path(existing_id).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    saved = load_draft(existing_id)
    return saved


def delete_draft(draft_id: str, *, confirm_name: str) -> None:
    data = load_draft(draft_id)
    expected = str(data.get("run_name") or draft_id).strip() or draft_id
    if confirm_name.strip() != expected:
        raise RunConflict("名称不一致，没有删除。")
    _path(draft_id).unlink()
