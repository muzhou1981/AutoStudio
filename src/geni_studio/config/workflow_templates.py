"""随流程保存的输出模板：存放在 workflows/<id>/templates/，流程里记相对路径。

文件一经写入不再覆盖：内容变了就另起名，旧版本仍引用原文件，回退时模板一并回到当时的内容。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from geni_studio.config.context import ConfigError

TEMPLATES_DIR = "templates"
MAX_TEMPLATE_BYTES = 256 * 1024
_SUFFIX_RE = re.compile(r"^(.*?)-(\d+)$")


def output_items(nodes: Any) -> Iterator[dict[str, Any]]:
    """逐个给出活动里带模板字段的输出项（含并行分支内的活动），可原地修改。"""
    if not isinstance(nodes, list):
        return
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("kind") == "parallel":
            for branch in node.get("branches") or []:
                if isinstance(branch, dict):
                    yield from output_items(branch.get("nodes"))
            continue
        outputs = node.get("outputs")
        if not isinstance(outputs, list):
            continue
        for item in outputs:
            if not isinstance(item, dict):
                continue
            template = str(item.get("template") or "").strip().lower()
            source = str(item.get("source") or ("link" if template.startswith(("http://", "https://")) else "file"))
            if source == "file":
                yield item


def owned_name(template: str) -> str:
    """`templates/<文件名>` 形式时返回文件名，否则返回空字符串。"""
    text = (template or "").strip()
    prefix = TEMPLATES_DIR + "/"
    if not text.startswith(prefix):
        return ""
    name = text[len(prefix):]
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return ""
    return name


def owned_path(folder: Path, template: str) -> Path | None:
    """流程自带模板的实际位置；路径不合规或是符号链接时返回 None。"""
    name = owned_name(template)
    if not name:
        return None
    path = folder / TEMPLATES_DIR / name
    if path.is_symlink():
        return None
    return path


def template_text(data: bytes) -> str:
    if len(data) > MAX_TEMPLATE_BYTES:
        raise ConfigError(f"模板超过 {MAX_TEMPLATE_BYTES // 1024} KB。")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError("模板须为 UTF-8 文本。") from exc


def read_owned(folder: Path, template: str) -> str:
    path = owned_path(folder, template)
    if path is None:
        raise ConfigError("只能读取本流程 templates/ 下的模板。")
    if not path.is_file():
        raise ConfigError("模板文件不存在。")
    return template_text(path.read_bytes())


def anchor_templates(workflow: dict[str, Any], folder: Path) -> dict[str, Any]:
    """返回副本：流程自带模板的相对路径换成绝对路径，供检查与编译读取。"""
    copied = deepcopy(workflow)
    for item in output_items(copied.get("nodes")):
        path = owned_path(folder, str(item.get("template") or ""))
        if path is not None:
            item["template"] = str(path)
    return copied


def _clean_name(raw: str, fallback: str) -> str:
    name = Path(raw.replace("\\", "/")).name.strip()
    if not name or name.startswith("."):
        name = fallback
    return name


def store_template(folder: Path, name: str, data: bytes, *, renumber: bool = False) -> str:
    """写入模板并返回相对路径。同名同内容时复用，同名不同内容时依次改用 -2、-3。

    renumber 为真时先去掉文件名末尾的 -N，使反复编辑得到 spec-2、spec-3，而不是 spec-2-2。
    """
    template_text(data)
    target_dir = folder / TEMPLATES_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    stem, suffix = Path(name).stem, Path(name).suffix
    matched = _SUFFIX_RE.match(stem) if renumber else None
    if matched:
        stem = matched.group(1)
    number = 1
    while True:
        candidate = f"{stem}{suffix}" if number == 1 else f"{stem}-{number}{suffix}"
        path = target_dir / candidate
        if path.is_symlink():
            number += 1
            continue
        if not path.exists():
            path.write_bytes(data)
            return f"{TEMPLATES_DIR}/{candidate}"
        if path.is_file() and path.read_bytes() == data:
            return f"{TEMPLATES_DIR}/{candidate}"
        number += 1


def absorb_templates(payload: dict[str, Any], folder: Path) -> dict[str, Any]:
    """返回副本：草稿里改过的正文与外部绝对路径都写进流程目录，改记相对路径。

    外部文件读不到时保留原路径，由运行前检查指出。
    """
    copied = deepcopy(payload)
    for item in output_items(copied.get("nodes")):
        template = str(item.get("template") or "").strip()
        content = item.pop("content", None)
        fallback = f"{item.get('name') or 'template'}.md"
        if isinstance(content, str):
            item["template"] = store_template(
                folder,
                _clean_name(template, fallback),
                content.encode("utf-8"),
                renumber=bool(owned_name(template)),
            )
            continue
        path = Path(template).expanduser() if template else None
        if path is None or not path.is_absolute():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        try:
            item["template"] = store_template(folder, _clean_name(template, fallback), data)
        except ConfigError:
            continue
    return copied


def import_from(source: Path, nodes: Any) -> Any:
    """返回副本：引用 source 流程自带模板的相对路径换成绝对路径，以便另一份流程收入。"""
    return anchor_templates({"nodes": nodes}, source)["nodes"]


def _referenced(data: Any) -> set[str]:
    nodes = data.get("nodes") if isinstance(data, dict) else None
    return {name for item in output_items(nodes) if (name := owned_name(str(item.get("template") or "")))}


def prune_templates(folder: Path) -> list[str]:
    """删掉既不被当前定义、也不被保留版本引用的模板文件，返回删掉的文件名。"""
    target_dir = folder / TEMPLATES_DIR
    if not target_dir.is_dir():
        return []
    keep: set[str] = set()
    sources = [folder / "workflow.yaml", *sorted((folder / "versions").glob("*.yaml"))]
    for path in sources:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            # 读不懂的定义可能还引用模板，宁可不删。
            return []
        if isinstance(data, dict) and isinstance(data.get("workflow"), dict) and "nodes" not in data:
            data = data["workflow"]
        keep |= _referenced(data)
    removed: list[str] = []
    for path in sorted(target_dir.iterdir()):
        if path.name in keep or not (path.is_file() or path.is_symlink()):
            continue
        path.unlink(missing_ok=True)
        removed.append(path.name)
    return removed
