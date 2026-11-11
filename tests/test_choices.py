"""人工待办选项解析。"""

from geni_studio.hitl.choices import (
    answers_from_reply,
    choice_groups_from_reading,
    choice_reply_line,
    choices_from_reading,
    extract_choice_groups,
    extract_choices,
)


def test_choice_reply_line_matches_web_wording():
    line = choice_reply_line({"id": "A", "label": "只删 placeholder", "recommended": True})
    assert line == "选择 A（推荐）：只删 placeholder"


def test_extract_choices_grill_me_style():
    body = """
请确认范围：

A（推荐）：只删 placeholder，保留 label
B：placeholder 和 label 都去掉
C：其他（请说明）
""".strip()
    parsed = extract_choices(body)
    assert [item["id"] for item in parsed] == ["A", "B", "C"]
    assert parsed[0]["recommended"] is True
    assert parsed[0]["label"].startswith("只删 placeholder")
    assert parsed[2]["label"] == "其他（请说明）"


def test_extract_choices_requires_at_least_two():
    assert extract_choices("A：仅一条\n") == []


def test_extract_choice_groups_splits_by_blank_line():
    body = "问题一：范围？\nA：方案一\nB：方案二\n\n问题二：测试？\nA：全量\nB：子集\n"
    groups = extract_choice_groups(body)
    assert len(groups) == 2
    assert groups[0]["choices"][0]["id"] == "A"
    assert groups[1]["choices"][1]["label"] == "子集"


def test_choice_groups_from_reading():
    sections = [
        {"title": "需求说明", "body": "A：一\nB：二\n\nC：三\nD：四\n"},
    ]
    groups = choice_groups_from_reading(sections)
    assert len(groups) == 2


def test_choices_from_reading_dedupes_by_id():
    sections = [
        {"title": "需求说明", "body": "A：一\nB：二\n"},
        {"title": "代码变更", "body": "A：重复\nC：三\n"},
    ]
    merged = choices_from_reading(sections)
    assert [item["id"] for item in merged] == ["A", "B", "C"]
    assert merged[0]["label"] == "一"


def test_bold_markdown_options_take_the_lead_in_question_as_prompt():
    body = (
        "先确认最关键的一点：\n\n**未选择项目时应如何处理？**\n\n"
        "- **A（推荐）**：清空并隐藏  \n- **B**：保留占位\n\n请选 A / B。"
    )
    groups = extract_choice_groups(body)
    assert len(groups) == 1
    assert groups[0]["prompt"] == "未选择项目时应如何处理？"
    assert [(c["id"], c["label"], c["recommended"]) for c in groups[0]["choices"]] == [
        ("A", "清空并隐藏", True),
        ("B", "保留占位", False),
    ]


def test_answers_from_reply_reads_letters_in_question_order():
    groups = extract_choice_groups("问题一：范围？\nA：方案一\nB：方案二\n\n问题二：测试？\nA：全量\nB：子集\n")
    assert answers_from_reply(groups, "选择 A：方案一\n选择 B：子集") == {"q1": "A", "q2": "B"}
    assert answers_from_reply(groups[:1], "同意B") == {"q1": "B"}
    assert answers_from_reply(groups[:1], "B") == {"q1": "B"}
    assert answers_from_reply(groups[:1], "LGTM") == {}
