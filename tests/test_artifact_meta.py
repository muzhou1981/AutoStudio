"""产物落盘、登记与提示词引用（D2 第三项）。"""

from __future__ import annotations

import re
from pathlib import Path

from geni_studio.hitl.service import GraphRunService
from geni_studio.workflows import artifacts
from geni_studio.workflows.default import graph


def _start(tmp_path, monkeypatch, prompts):
    from geni_studio.backends import runner

    real = runner.invoke_role

    def spy(**kwargs):
        prompts.append((kwargs["role_name"], kwargs["user_prompt"]))
        return real(**kwargs)

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", spy)
    monkeypatch.setenv("GENI_STUDIO_WORKSPACE", "1")
    monkeypatch.setenv("GENI_STUDIO_TARGET_ROOT", str(tmp_path))
    return GraphRunService(graph).start(human_request="写一个乘法工具", scenario_key="npu_operator")


def test_artifacts_are_written_and_registered(tmp_path, monkeypatch):
    st = _start(tmp_path, monkeypatch, [])
    meta = st.values["artifact_meta"]
    spec = st.values["requirement_spec"]
    entry = meta["requirement_spec"]
    assert entry["node"] == "project_manager_draft"
    assert entry["attempt"] == 1
    assert entry["sha256"] == artifacts.digest(spec)
    path = Path(entry["path"])
    assert path == tmp_path / ".geni_studio" / "runs" / st.thread_id / "artifacts" / "requirement_spec.md"
    assert path.read_text(encoding="utf-8").strip() == spec.strip()
    assert meta["testability_review"]["node"] == "tester_testability"
    assert "human_request" not in meta


def test_file_capable_backend_gets_a_path_instead_of_text(tmp_path, monkeypatch):
    monkeypatch.setattr("geni_studio.backends.runner.backend_reads_files", lambda role: True)
    prompts: list[tuple[str, str]] = []
    st = _start(tmp_path, monkeypatch, prompts)
    spec = st.values["requirement_spec"]
    tester = next(prompt for role, prompt in prompts if role == "tester")
    assert "全文在文件" in tester
    assert st.values["artifact_meta"]["requirement_spec"]["path"] in tester
    assert spec not in tester


def test_stub_backend_still_gets_the_full_text(tmp_path, monkeypatch):
    prompts: list[tuple[str, str]] = []
    st = _start(tmp_path, monkeypatch, prompts)
    tester = next(prompt for role, prompt in prompts if role == "tester")
    assert f"需求说明：\n{st.values['requirement_spec']}" in tester


def test_attempts_count_up_and_long_text_is_not_truncated():
    first = artifacts.record({}, {"code_change": "v1"}, "developer", "")
    second = artifacts.record({"artifact_meta": first["artifact_meta"]}, {"code_change": "v2"}, "developer", "")
    assert second["artifact_meta"]["code_change"]["attempt"] == 2
    assert "path" not in second["artifact_meta"]["code_change"]
    long = "甲" * 30000
    assert artifacts.reference({"requirement_spec": long}, "requirement_spec", "需求说明", role="tester").endswith(long)


def test_prompt_builders_have_no_hardcoded_truncation():
    root = Path(__file__).resolve().parents[1] / "src" / "geni_studio" / "workflows"
    for name in ("default.py", "executable.py"):
        source = (root / name).read_text(encoding="utf-8")
        assert not re.search(r"\[:\d{3,}\]", source), name
