"""帮助正文：读取 `docs/help/*.md`，按帮助所需的 Markdown 子集渲染成 HTML。

只支持帮助用到的写法：二、三级标题（可用 `{#id}` 指定锚点）、段落、有序与无序列表（列表项下可再缩进一层无序列表）、
表格、代码块、单独成行的图片、`> [!NOTE]` 一类提示框、以 `<` 开头的原样 HTML 块，以及行内的粗体、代码、链接与 `<kbd>`。
正文由人维护并随仓库评审，原样 HTML 块不做清洗。
"""

from __future__ import annotations

import re
from html import escape, unescape
from pathlib import Path

from geni_studio.config.context import factory_root

TOPICS = (
    "quickstart",
    "concepts",
    "project",
    "run",
    "workflow",
    "roles",
    "config",
    "faq",
    "architecture",
)

ALIASES = {
    "overview": "quickstart",
    "guide": "quickstart",
    "agent": "config/agent",
    "workspace": "config/workspace",
    "feishu": "config/feishu",
    "env": "config/env",
}

ASSET_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*\.(png|jpg|jpeg|svg)$")

_CALLOUTS = {"NOTE": ("note", "说明"), "TIP": ("tip", "提示"), "WARNING": ("warning", "注意")}
_HEADING = re.compile(r"^(#{1,3})\s+(.+?)(?:\s+\{#([a-z0-9][a-z0-9-]*)\})?\s*$")
_ORDERED = re.compile(r"^(\d+)\.\s+(.*)$")
_IMAGE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)\)$")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_CJK = re.compile(r"[\u3000-\u9fff\uff00-\uffef]")


class HelpError(RuntimeError):
    """帮助正文缺失或写法超出支持的子集。"""


def help_dir() -> Path:
    return factory_root() / "docs" / "help"


def _join(lines: list[str]) -> str:
    """把折行接回一句。两侧都是中文或全角标点时不加空格。"""
    out = ""
    for line in lines:
        text = line.strip()
        if not text:
            continue
        if out and not (_CJK.search(out[-1]) or _CJK.search(text[0])):
            out += " "
        out += text
    return out


def _href(target: str, topic: str) -> tuple[str, bool]:
    """返回（地址，是否外部链接）。`run.md#todo` 与 `#todo` 换成帮助页内的地址。"""
    if target.startswith(("http://", "https://")):
        return target, True
    if target.startswith("#"):
        return "/help#" + topic + "/" + target[1:], False
    page, _, anchor = target.partition("#")
    if page.endswith(".md") and "/" not in page:
        dest = page[: -len(".md")]
        return "/help#" + dest + ("/" + anchor if anchor else ""), False
    return target, False


def _inline(text: str, topic: str) -> str:
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for part in parts:
        if len(part) > 2 and part.startswith("`") and part.endswith("`"):
            out.append("<code>" + escape(part[1:-1]) + "</code>")
            continue
        html = escape(part, quote=False)
        html = re.sub(r"&lt;kbd&gt;(.+?)&lt;/kbd&gt;", r"<kbd>\1</kbd>", html)
        html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)

        def link(match: re.Match[str]) -> str:
            href, external = _href(unescape(match.group(2)), topic)
            extra = ' target="_blank" rel="noopener"' if external else ""
            return '<a href="' + escape(href) + '"' + extra + ">" + match.group(1) + "</a>"

        out.append(_LINK.sub(link, html))
    return "".join(out)


def _asset(src: str) -> str:
    if src.startswith("images/"):
        return "/api/help/assets/" + src[len("images/") :]
    return src


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _list_html(lines: list[str], topic: str) -> str:
    """一个列表块。列表项下缩进的 `- ` 行成为嵌套的无序列表，其他缩进行接在所属的项后面。"""
    ordered = bool(_ORDERED.match(lines[0]))
    items: list[dict] = []
    for raw in lines:
        indented = raw.startswith((" ", "\t"))
        text = raw.strip()
        if not indented:
            match = _ORDERED.match(text) if ordered else None
            body = match.group(2) if match else text[2:]
            items.append({"text": [body], "sub": []})
            continue
        if not items:
            raise HelpError("列表前面不能有缩进行：" + raw)
        item = items[-1]
        if text.startswith("- "):
            item["sub"].append([text[2:]])
        elif item["sub"]:
            item["sub"][-1].append(text)
        else:
            item["text"].append(text)
    tag = "ol" if ordered else "ul"
    html = ["<" + tag + ">"]
    for item in items:
        inner = _inline(_join(item["text"]), topic)
        if item["sub"]:
            inner += "<ul>" + "".join("<li>" + _inline(_join(sub), topic) + "</li>" for sub in item["sub"]) + "</ul>"
        html.append("<li>" + inner + "</li>")
    html.append("</" + tag + ">")
    return "".join(html)


def _is_list(line: str) -> bool:
    return line.startswith("- ") or bool(_ORDERED.match(line))


def render(text: str, topic: str) -> dict:
    """渲染一篇帮助。返回标题、HTML 与二、三级标题目录。"""
    lines = text.splitlines()
    title = ""
    html: list[str] = []
    sections: list[dict] = []
    seen: set[str] = set()
    para: list[str] = []
    i = 0

    def flush() -> None:
        if para:
            html.append("<p>" + _inline(_join(para), topic) + "</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            flush()
            i += 1
            continue
        if stripped.startswith("```"):
            flush()
            lang = stripped[3:].strip()
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            if i >= len(lines):
                raise HelpError(topic + "：代码块没有结束。")
            cls = ' class="language-' + escape(lang) + '"' if lang else ""
            html.append("<pre><code" + cls + ">" + escape("\n".join(body)) + "</code></pre>")
            i += 1
            continue
        if line.startswith("<"):
            flush()
            block = []
            while i < len(lines) and lines[i].strip():
                block.append(lines[i])
                i += 1
            html.append("\n".join(block))
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            label = heading.group(2).strip()
            if level == 1:
                if title:
                    raise HelpError(topic + "：一篇只能有一个一级标题。")
                title = label
                i += 1
                continue
            anchor = heading.group(3) or "s" + str(len(sections) + 1)
            if anchor in seen:
                raise HelpError(topic + "：锚点重复：" + anchor)
            seen.add(anchor)
            sections.append({"id": anchor, "title": label, "level": level})
            html.append(
                "<h" + str(level) + ' id="' + escape(topic + "/" + anchor) + '">' + _inline(label, topic)
                + "</h" + str(level) + ">"
            )
            i += 1
            continue
        image = _IMAGE.match(stripped)
        if image:
            flush()
            alt = escape(image.group(1))
            html.append(
                '<figure class="help-figure"><img src="' + escape(_asset(image.group(2))) + '" alt="' + alt
                + '" loading="lazy" /><figcaption>' + alt + "</figcaption></figure>"
            )
            i += 1
            continue
        if stripped.startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            kind = re.match(r"^\[!([A-Z]+)\]$", quote[0]) if quote else None
            if kind and kind.group(1) in _CALLOUTS:
                cls, label = _CALLOUTS[kind.group(1)]
                quote = quote[1:]
                paras = [p for p in "\n".join(quote).split("\n\n") if p.strip()]
                body = "".join("<p>" + _inline(_join(p.splitlines()), topic) + "</p>" for p in paras)
                html.append(
                    '<aside class="help-callout is-' + cls + '"><p class="help-callout-label">' + label + "</p>"
                    + body + "</aside>"
                )
            else:
                html.append("<blockquote><p>" + _inline(_join(quote), topic) + "</p></blockquote>")
            continue
        if stripped.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            if len(rows) < 2 or not re.match(r"^\|?[\s:|-]+\|?$", rows[1].strip()):
                raise HelpError(topic + "：表格缺少表头分隔行。")
            head = "".join("<th>" + _inline(cell, topic) + "</th>" for cell in _cells(rows[0]))
            body = "".join(
                "<tr>" + "".join("<td>" + _inline(cell, topic) + "</td>" for cell in _cells(row)) + "</tr>"
                for row in rows[2:]
            )
            html.append(
                '<div class="help-table"><table><thead><tr>' + head + "</tr></thead><tbody>" + body
                + "</tbody></table></div>"
            )
            continue
        if _is_list(line):
            flush()
            block = []
            while i < len(lines):
                cur = lines[i]
                if not cur.strip():
                    nxt = lines[i + 1] if i + 1 < len(lines) else ""
                    if _is_list(nxt) and bool(_ORDERED.match(nxt)) == bool(_ORDERED.match(block[0])):
                        i += 1
                        continue
                    break
                if block and not _is_list(cur) and not cur.startswith((" ", "\t")):
                    break
                block.append(cur)
                i += 1
            html.append(_list_html(block, topic))
            continue
        para.append(line)
        i += 1
    flush()
    if not title:
        raise HelpError(topic + "：缺少一级标题。")
    return {"id": topic, "title": title, "html": "\n".join(html), "sections": sections}


def load_topics(root: Path | None = None) -> list[dict]:
    base = root or help_dir()
    topics = []
    for topic in TOPICS:
        path = base / (topic + ".md")
        if not path.is_file():
            raise HelpError("缺少帮助正文：" + path.name)
        topics.append(render(path.read_text(encoding="utf-8"), topic))
    return topics


def asset_path(name: str, root: Path | None = None) -> Path | None:
    if not ASSET_NAME.match(name):
        return None
    path = (root or help_dir()) / "images" / name
    return path if path.is_file() else None
