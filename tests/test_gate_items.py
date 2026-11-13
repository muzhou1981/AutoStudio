"""决策点的逐项审批（ADR 0032）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver
from test_subgraph_parallel import _patch, _root

from geni_studio.config.context import ConfigError
from geni_studio.hitl.gate_items import ItemsError, items_section, judge_items
from geni_studio.hitl.service import GraphRunService, HitlError
from geni_studio.workflows.default import compile_graph

_FLOW = (
    "workflow_id: sample\ntitle: 逐项审批\nnodes:\n"
    "- {id: start, kind: start, name: 启动, role: human, returns_to: ''}\n"
    "- {id: dev, kind: activity, name: 开发, role: developer, returns_to: ''}\n"
    "- id: review\n  kind: gate\n  name: 评审\n  role: human\n  returns_to: ''\n  decision: approve\n"
    "  reject_to: dev\n  items:\n"
    "  - {id: api, title: 接口兼容, hint: 对照接口说明}\n"
    "  - {id: perf, title: 性能, required: false}\n"
    "- {id: end, kind: end, name: 结束, role: human, returns_to: ''}\n"
)

_CHECKLIST = {
    "items": [
        {"id": "api", "title": "接口兼容", "hint": "", "required": True},
        {"id": "perf", "title": "性能", "hint": "", "required": False},
    ],
    "pass_rule": "all",
}


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flow: str = _FLOW):
    _root(tmp_path)
    _patch(monkeypatch, tmp_path)
    (tmp_path / "workflows" / "sample").mkdir(parents=True)
    (tmp_path / "workflows" / "sample" / "workflow.yaml").write_text(flow, encoding="utf-8")
    calls: list[str] = []

    def fake_invoke(*, role_name: str, user_prompt: str, stub_note: str, model: str | None = None) -> str:
        calls.append(user_prompt)
        return f"[{role_name}]"

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", fake_invoke)
    svc = GraphRunService(compile_graph(MemorySaver()))
    st = svc.start(human_request="逐项", scenario_key="demo", project_id="bound")
    return svc, st, calls


def test_all_rule_derives_the_overall_decision():
    decision, judged = judge_items(_CHECKLIST, [{"id": "api", "decision": "approved"}], "rejected")
    assert decision == "approved" and [item["id"] for item in judged] == ["api"]
    decision, judged = judge_items(
        _CHECKLIST,
        [{"id": "api", "decision": "approved"}, {"id": "perf", "decision": "rejected", "note": "慢了一倍"}],
        "approved",
    )
    assert decision == "rejected"
    assert items_section(judged) == "逐项结论：\n- 通过“接口兼容”\n- 不通过“性能”：慢了一倍"


def test_items_need_required_answers_and_reasons():
    with pytest.raises(ItemsError, match="1 个必答项没有结论：“接口兼容”"):
        judge_items(_CHECKLIST, [{"id": "perf", "decision": "approved"}], None)
    with pytest.raises(ItemsError, match="要写明原因"):
        judge_items(_CHECKLIST, [{"id": "api", "decision": "rejected"}], None)
    with pytest.raises(ItemsError, match="不在这个决策点上"):
        judge_items(_CHECKLIST, [{"id": "x", "decision": "approved"}], None)
    with pytest.raises(ItemsError, match="逐项处理"):
        judge_items(_CHECKLIST, None, "rejected")
    decision, judged = judge_items(_CHECKLIST, None, "approved")
    assert decision == "approved" and len(judged) == 2


def test_manual_rule_keeps_the_human_decision():
    manual = {**_CHECKLIST, "pass_rule": "manual"}
    decision, judged = judge_items(manual, [{"id": "perf", "decision": "rejected", "note": "慢"}], "approved")
    assert decision == "approved" and judged[0]["id"] == "perf"
    assert judge_items(manual, None, "rejected") == ("rejected", [])


def test_gate_with_items_rejects_back_with_item_reasons(tmp_path, monkeypatch):
    from geni_studio.hitl.conversation import conversation_dir

    svc, st, calls = _run(tmp_path, monkeypatch)
    assert st.awaiting_human is not None and st.awaiting_human.gate_id == "review"
    awaiting = svc.status_dict(st.thread_id)["awaiting_human"]
    assert awaiting["pass_rule"] == "all"
    assert [item["id"] for item in awaiting["items"]] == ["api", "perf"]
    assert awaiting["items"][1]["required"] is False
    with pytest.raises(HitlError, match="必答项"):
        svc.submit_hitl(st.thread_id, item_decisions=[{"id": "perf", "decision": "approved"}])
    back = svc.submit_hitl(
        st.thread_id,
        gate_decision="approved",
        item_decisions=[{"id": "api", "decision": "rejected", "note": "删了旧字段"}],
    )
    assert back.awaiting_human is not None and back.awaiting_human.gate_id == "review"
    assert len(calls) == 2 and "不通过“接口兼容”：删了旧字段" in calls[-1]
    done = svc.submit_hitl(st.thread_id, gate_decision="approved")
    assert done.phase == "completed"
    log = conversation_dir(st.thread_id, str(done.values.get("workspace_path") or "")).parent / "decisions.jsonl"
    entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert entries[0]["decision"] == "rejected"
    assert entries[0]["items"] == [{"id": "api", "title": "接口兼容", "decision": "rejected", "note": "删了旧字段"}]
    assert [item["decision"] for item in entries[1]["items"]] == ["approved", "approved"]


def test_item_definitions_are_checked(tmp_path, monkeypatch):
    from geni_studio.config.workflow_defs import validate_workflow

    _root(tmp_path)
    _patch(monkeypatch, tmp_path)

    def payload(gate: dict) -> dict:
        return {
            "workflow_id": "sample",
            "title": "检查",
            "nodes": [
                {"id": "start", "kind": "start"},
                {"id": "dev", "kind": "activity", "name": "开发", "role": "developer"},
                {"id": "g", "kind": "gate", "name": "评审", "role": "human", "decision": "approve", **gate},
                {"id": "end", "kind": "end"},
            ],
        }

    with pytest.raises(ConfigError, match="不能空，也不能重复"):
        validate_workflow(payload({"items": [{"id": "a", "title": "甲"}, {"id": "a", "title": "乙"}]}), root=tmp_path)
    with pytest.raises(ConfigError, match="没写名称"):
        validate_workflow(payload({"items": [{"id": "a", "title": ""}]}), root=tmp_path)
    with pytest.raises(ConfigError, match="汇总规则"):
        validate_workflow(payload({"items": [{"id": "a", "title": "甲"}], "pass_rule": "most"}), root=tmp_path)
    cleaned = validate_workflow(
        payload({"items": [{"id": "a", "title": "甲", "required": False}], "pass_rule": "manual"}), root=tmp_path
    )
    gate = cleaned["nodes"][2]
    assert gate["items"] == [{"id": "a", "title": "甲", "required": False}] and gate["pass_rule"] == "manual"


def test_feishu_card_offers_approve_all_and_web(tmp_path):
    from geni_studio.hitl.feishu_cards import build_gate_interactive_card

    card = build_gate_interactive_card(
        thread_id="t1",
        summary="",
        gate_id="review",
        web_url="http://x",
        node_label="评审",
        items=_CHECKLIST["items"],
    )
    text = json.dumps(card, ensure_ascii=False)
    assert "共 2 项待逐项审批，其中 1 项必答" in text
    buttons = [el["text"]["content"] for el in card["body"]["elements"] if el.get("tag") == "button"]
    assert buttons == ["全部通过", "在网页逐项处理"]
