"""帮助正文：渲染子集、篇目完整性、站内链接与配图。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geni_studio.web.app import app
from geni_studio.web.help_docs import (
    ALIASES,
    TOPICS,
    HelpError,
    asset_path,
    help_dir,
    load_topics,
    render,
)

ROOT = Path(__file__).resolve().parents[1]

SAMPLE = """# 标题

第一行
第二行 with `code` and **粗体**，见[运行](run.md#todo)与[本篇](#a)。

## 小节 {#a}

1. 第一步
   - 结果：看到页面。
2. 第二步<kbd>Ctrl</kbd>

> [!WARNING]
> 注意事项

| 列 | 说明 |
|---|---|
| a | b |

![图](images/x.png)

```bash
echo <hi>
```
"""


def test_render_subset():
    text = SAMPLE
    out = render(text, "demo")
    assert out["title"] == "标题"
    assert out["sections"] == [{"id": "a", "title": "小节", "level": 2}]
    html = out["html"]
    assert "<p>第一行第二行 with <code>code</code> and <strong>粗体</strong>" in html
    assert '<a href="/help#run/todo">运行</a>' in html and '<a href="/help#demo/a">本篇</a>' in html
    assert '<h2 id="demo/a">小节</h2>' in html
    assert "<ol><li>第一步<ul><li>结果：看到页面。</li></ul></li><li>第二步<kbd>Ctrl</kbd></li></ol>" in html
    assert 'class="help-callout is-warning"' in html and "<p>注意事项</p>" in html
    assert "<th>列</th>" in html and "<td>b</td>" in html
    assert 'src="/api/help/assets/x.png"' in html and "<figcaption>图</figcaption>" in html
    assert "echo &lt;hi&gt;" in html


def test_render_escapes_text_and_marks_external_links():
    html = render("# T\n\n转义 <script>，[外链](https://example.com)\n", "t")["html"]
    assert "&lt;script&gt;" in html
    assert 'href="https://example.com" target="_blank" rel="noopener"' in html


def test_render_rejects_bad_documents():
    with pytest.raises(HelpError):
        render("没有标题\n", "t")
    with pytest.raises(HelpError):
        render("# A\n\n## x {#same}\n\n## y {#same}\n", "t")
    with pytest.raises(HelpError):
        render("# A\n\n| 只有表头 |\n", "t")


def test_every_topic_renders_and_internal_links_resolve():
    topics = {topic["id"]: topic for topic in load_topics()}
    assert tuple(topics) == TOPICS
    anchors = {(tid, s["id"]) for tid, topic in topics.items() for s in topic["sections"]}
    for topic in topics.values():
        for href in re.findall(r'href="/help#([^"]+)"', topic["html"]):
            tid, _, section = href.partition("/")
            assert tid in topics, f"{topic['id']} 链到不存在的篇：{href}"
            if section:
                assert (tid, section) in anchors, f"{topic['id']} 链到不存在的小节：{href}"
        for src in re.findall(r'src="/api/help/assets/([^"]+)"', topic["html"]):
            assert asset_path(src) is not None, f"{topic['id']} 缺少配图：{src}"
    for alias, target in ALIASES.items():
        tid, _, section = target.partition("/")
        assert tid in topics and (not section or (tid, section) in anchors), alias


def test_page_links_point_at_existing_help():
    """侧栏帮助菜单与界面里的“?”都要指向存在的篇或小节。"""
    topics = {topic["id"]: topic for topic in load_topics()}
    anchors = {(tid, s["id"]) for tid, topic in topics.items() for s in topic["sections"]}
    html = (ROOT / "src/geni_studio/web/static/hitl.html").read_text(encoding="utf-8")
    menu = re.findall(r'data-help-topic="([a-z]+)"', html)
    assert tuple(menu) == TOPICS
    groups = re.findall(r'data-help-group="([a-z]+)"', html)
    controls = re.findall(r'class="help-nav-caption"[^>]*aria-controls="([A-Za-z]+)"', html)
    assert len(groups) == len(controls) == 3
    for target in controls:
        assert f'class="help-nav-items" id="{target}"' in html
    tips = re.findall(r'class="help-tip" href="/help#([^"]+)"', html)
    assert len(tips) >= 8
    for href in tips:
        tid, _, section = href.partition("/")
        assert tid in topics and (not section or (tid, section) in anchors), href


def test_help_api_and_assets():
    client = TestClient(app)
    data = client.get("/api/help").json()
    assert [topic["id"] for topic in data["topics"]] == list(TOPICS)
    assert data["aliases"]["guide"] == "quickstart"
    assert client.get("/api/help/assets/overview.jpg").status_code == 200
    assert client.get("/api/help/assets/missing.png").status_code == 404
    assert client.get("/api/help/assets/..%2Fquickstart.md").status_code == 404


def test_help_dir_is_in_repository():
    assert help_dir() == ROOT / "docs" / "help"
