"""试点场景整图端到端：自动批复关卡、答复澄清，直到 completed 或步数上限。"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

from geni_studio.config.env_loader import apply_env_file
from geni_studio.hitl.service import GraphRunService, HitlError
from geni_studio.workflows.default import graph


def _log(msg: str) -> None:
    ts = datetime.now(UTC).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def main() -> int:
    apply_env_file(
        override=os.environ.get("GENI_STUDIO_DOTENV_OVERRIDE", "1").strip().lower()
        in ("1", "true", "yes")
    )
    scenario = os.environ.get("GENI_STUDIO_E2E_SCENARIO", "npu_operator")
    project = os.environ.get("GENI_STUDIO_E2E_PROJECT", "_example")
    request = os.environ.get(
        "GENI_STUDIO_E2E_REQUEST",
        "为 npu_operator 场景实现 Mul 算子：输入输出为 float16，含单测与可检验验收标准。"
        "不要列出待澄清问题，直接给出可执行需求说明。",
    )
    max_steps = int(os.environ.get("GENI_STUDIO_E2E_MAX_STEPS", "40"))
    svc = GraphRunService(graph)
    _log(f"start scenario={scenario} project={project} backend={os.environ.get('GENI_STUDIO_BACKEND') or 'auto'}")
    t0 = time.monotonic()
    st = svc.start(human_request=request, scenario_key=scenario, project_id=project)
    _log(f"thread={st.thread_id} phase={st.phase} next={st.next_nodes}")

    for step in range(1, max_steps + 1):
        st = svc.status(st.thread_id)
        ah = st.awaiting_human
        if st.phase == "completed":
            _log(f"COMPLETED steps={step - 1} elapsed={time.monotonic() - t0:.0f}s")
            _summarize(st.values)
            return 0
        if st.phase == "rejected":
            _log("REJECTED")
            return 1
        if ah is None:
            _log(f"step {step} phase={st.phase} next={st.next_nodes}（无待办，尝试推进）")
            svc._graph.invoke(None, svc._config(st.thread_id))
            continue
        _log(f"step {step} awaiting={ah.kind} gate={ah.gate_id} summary={ah.summary[:80]}")
        try:
            if ah.kind == "gate":
                st = svc.submit_hitl(
                    st.thread_id,
                    gate_decision="approved",
                    human_reply="E2E 自动批准",
                    channel="web",
                )
            elif ah.kind == "pm_clarification":
                st = svc.submit_hitl(
                    st.thread_id,
                    human_reply="按当前范围继续：仅 Mul 算子，float16，含单测。无需再澄清。",
                    channel="web",
                )
            elif ah.kind == "escalation":
                st = svc.submit_hitl(
                    st.thread_id,
                    escalation_choice="continue",
                    human_reply="E2E 选择继续",
                    channel="web",
                )
            else:
                _log(f"FAIL 未知待办 {ah.kind}")
                return 1
        except HitlError as e:
            _log(f"FAIL hitl: {e}")
            return 1
        _log(f"  -> phase={st.phase} next={st.next_nodes}")

    _log(f"FAIL 超过 {max_steps} 步仍未结束 phase={st.phase}")
    return 1


def _summarize(values: dict) -> None:
    keys = (
        "requirement_spec",
        "architecture_design",
        "task_plan",
        "code_change",
        "test_report",
        "qa_report",
        "delivery_report",
        "run_record",
    )
    for key in keys:
        text = str(values.get(key) or "")
        head = text.replace("\n", " ")[:120]
        _log(f"  {key}: len={len(text)} {head}")


if __name__ == "__main__":
    raise SystemExit(main())
