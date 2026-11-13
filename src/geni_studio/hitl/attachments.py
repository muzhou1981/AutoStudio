"""运行提示词上的附件。文件先暂存在工厂目录，启动时拷进当轮工作区。"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from uuid import uuid4

from geni_studio.config.context import factory_root
from geni_studio.hitl.service import HitlError

_UPLOAD_ID = re.compile(r"^[0-9a-f]{32}$")
_MAX_BYTES = 20 * 1024 * 1024
_MAX_COUNT = 8


def uploads_dir() -> Path:
    path = factory_root() / "runs" / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(raw: str) -> str:
    name = Path(str(raw or "").replace("\x00", "")).name.strip().strip(".")
    if not name or name in {".", ".."} or any(ord(ch) < 32 for ch in name):
        raise HitlError("附件名称无法识别。")
    if len(name) > 120:
        raise HitlError("附件名称过长。")
    return name


def _folder(upload_id: str) -> Path:
    if not _UPLOAD_ID.fullmatch(upload_id):
        raise HitlError("这份附件无法识别。")
    return uploads_dir() / upload_id


def store_upload(filename: str, data: bytes) -> dict:
    name = _safe_name(filename)
    if not data:
        raise HitlError("附件是空的。")
    if len(data) > _MAX_BYTES:
        raise HitlError("单个附件不超过 20 MB。")
    upload_id = uuid4().hex
    folder = _folder(upload_id)
    folder.mkdir(parents=True)
    (folder / name).write_bytes(data)
    (folder / "meta.json").write_text(
        json.dumps({"name": name, "size": len(data)}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {"id": upload_id, "name": name, "size": len(data)}


def load_upload(upload_id: str) -> dict:
    folder = _folder(upload_id)
    meta_path = folder / "meta.json"
    if not meta_path.is_file():
        raise HitlError("这份附件已经不在。")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HitlError("这份附件已经不在。") from exc
    if not isinstance(meta, dict):
        raise HitlError("这份附件已经不在。")
    name = _safe_name(str(meta.get("name") or ""))
    path = folder / name
    if not path.is_file():
        raise HitlError("这份附件已经不在。")
    return {"id": upload_id, "name": name, "size": int(meta.get("size") or path.stat().st_size), "path": path}


def clean_attachment_ids(raw: object) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise HitlError("附件须为列表。")
    if len(raw) > _MAX_COUNT:
        raise HitlError("一次最多 8 个附件。")
    ids: list[str] = []
    for item in raw:
        upload_id = ""
        if isinstance(item, str):
            upload_id = item.strip()
        elif isinstance(item, dict):
            upload_id = str(item.get("id") or "").strip()
        else:
            upload_id = str(getattr(item, "id", "") or "").strip()
        if not upload_id:
            raise HitlError("附件无法识别。")
        if upload_id in ids:
            raise HitlError("这个附件重复了。")
        load_upload(upload_id)
        ids.append(upload_id)
    return ids


def _unique_name(name: str, used: set[str]) -> str:
    if name not in used:
        used.add(name)
        return name
    stem = Path(name).stem
    suffix = Path(name).suffix
    number = 2
    while True:
        candidate = f"{stem}-{number}{suffix}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        number += 1


def stage_attachments(upload_ids: list[str], dest: Path) -> list[str]:
    """把暂存文件拷进 dest，返回相对工作区的 attachments/ 路径。"""
    if len(upload_ids) > _MAX_COUNT:
        raise HitlError("一次最多 8 个附件。")
    dest.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    relative: list[str] = []
    for upload_id in upload_ids:
        item = load_upload(upload_id)
        name = _unique_name(item["name"], used)
        shutil.copyfile(item["path"], dest / name)
        relative.append(f"attachments/{name}")
    return relative


def stage_reply_attachments(upload_ids: list[str], dest: Path) -> list[Path]:
    """待办答复带的附件拷进 dest；与已有文件重名时加序号，不覆盖启动时的附件。"""
    if len(upload_ids) > _MAX_COUNT:
        raise HitlError("一次最多 8 个附件。")
    dest.mkdir(parents=True, exist_ok=True)
    used = {item.name for item in dest.iterdir()}
    staged: list[Path] = []
    for upload_id in upload_ids:
        item = load_upload(upload_id)
        target = dest / _unique_name(item["name"], used)
        shutil.copyfile(item["path"], target)
        staged.append(target)
    return staged


def reply_section(paths: list[str]) -> str:
    if not paths:
        return ""
    return "附件，可直接读取：\n" + "\n".join(f"- {path}" for path in paths)


def prompt_section(paths: object) -> str:
    if not isinstance(paths, list):
        return ""
    lines = [str(item).strip() for item in paths if str(item).strip()]
    if not lines:
        return ""
    body = "\n".join(f"- {line}" for line in lines)
    return "本轮附件，可直接读取：\n" + body
