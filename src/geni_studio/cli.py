"""工厂命令行：启动观测与后端配置。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from geni_studio.config.context import factory_root
from geni_studio.config.env_loader import apply_env_file

_SECRET_KEYS = {"CURSOR_API_KEY", "OPENAI_API_KEY"}
_ALLOWED = {
    "CURSOR_API_KEY",
    "OPENAI_API_KEY",
    "GENI_STUDIO_CURSOR_MODEL",
    "GENI_STUDIO_CODEX_MODEL",
    "GENI_STUDIO_DEFAULT_MODEL",
    "GENI_STUDIO_BACKEND",
    "GENI_STUDIO_TARGET_ROOT",
    "GENI_STUDIO_LARK_BACKEND",
    "GENI_STUDIO_PUBLIC_BASE_URL",
    "GENI_STUDIO_FEISHU_NOTIFY_CHAT_ID",
    "GENI_STUDIO_FEISHU_NOTIFY_OPEN_ID",
}


def env_path(root: Path | None = None) -> Path:
    return (root or factory_root()) / ".env"


def read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, _, value = raw.partition("=")
        out[key.strip()] = value.strip()
    return out


def write_env_key(path: Path, key: str, value: str) -> None:
    if key not in _ALLOWED:
        raise SystemExit(f"不允许写入配置项 {key}")
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    prefix = f"{key}="
    replaced = False
    new_lines: list[str] = []
    for line in lines:
        if line.strip().startswith(prefix):
            new_lines.append(prefix + value)
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        new_lines.append(prefix + value)
    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def mask(key: str, value: str) -> str:
    if key in _SECRET_KEYS and value:
        return value[:4] + "…" if len(value) > 4 else "…"
    return value or "（空）"


def cmd_show(root: Path) -> int:
    data = read_env(env_path(root))
    for key in sorted(_ALLOWED):
        print(f"{key}={mask(key, data.get(key, os.environ.get(key, '')))}")
    return 0


def cmd_run(args: argparse.Namespace, root: Path) -> int:
    os.environ["GENI_STUDIO_CHECKPOINT"] = os.environ.get("GENI_STUDIO_CHECKPOINT", "sqlite")
    apply_env_file(root=root)
    from geni_studio.hitl.service import GraphRunService
    from geni_studio.workflows.default import graph

    st = GraphRunService(graph).start(
        human_request=args.request,
        scenario_key=args.scenario,
        project_id=args.project,
    )
    print(f"thread_id={st.thread_id}")
    print(f"phase={st.phase}")
    if st.awaiting_human:
        print(f"awaiting={st.awaiting_human.kind}")
        print(f"summary={st.awaiting_human.summary}")
    _print_feishu(st.thread_id, str(st.values.get("project_id") or args.project))
    work = st.values.get("workspace_path") or ""
    if work:
        print(f"worktree={work}")
    return 0


def cmd_hitl(args: argparse.Namespace) -> int:
    from geni_studio.hitl.service import GraphRunService, HitlError
    from geni_studio.workflows.default import graph

    try:
        st = GraphRunService(graph).submit_hitl(
            args.thread_id,
            gate_decision=args.decision,
            human_reply=args.reply,
            channel="cli",
            escalation_choice=args.escalation,
        )
    except HitlError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"thread_id={st.thread_id}")
    print(f"phase={st.phase}")
    _print_feishu(st.thread_id, str(st.values.get("project_id") or ""))
    return 0


def _print_feishu(thread_id: str, project_id: str) -> None:
    from geni_studio.hitl.feishu_notify import notify_awaiting_human_via_lark_cli
    from geni_studio.hitl.service import GraphRunService
    from geni_studio.workflows.default import graph

    result = notify_awaiting_human_via_lark_cli(GraphRunService(graph), thread_id, project_id)
    if result.sent:
        print("feishu=sent")
    elif result.detail:
        print(f"feishu={result.detail}")


def cmd_proposal(args: argparse.Namespace, root: Path) -> int:
    from geni_studio.evolution.proposals import (
        ProposalError,
        apply_proposal,
        approve_proposal,
        save_proposal,
    )

    try:
        if args.proposal_cmd == "save":
            save_proposal(
                root,
                args.id,
                target=args.target,
                summary=args.summary,
                body=args.body,
            )
            print(f"pending {args.id}")
            return 0
        if args.proposal_cmd == "approve":
            approve_proposal(root, args.id, evidence=args.evidence)
            print(f"approved {args.id}")
            return 0
        if args.proposal_cmd == "apply":
            path = apply_proposal(root, args.id)
            print(f"applied {path}")
            return 0
    except ProposalError as exc:
        raise SystemExit(str(exc)) from exc
    return 2


def cmd_status(thread_id: str) -> int:
    from geni_studio.hitl.service import GraphRunService, HitlError
    from geni_studio.workflows.default import graph

    try:
        st = GraphRunService(graph).status(thread_id)
    except HitlError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"thread_id={st.thread_id}")
    print(f"phase={st.phase}")
    print(f"next={','.join(st.next_nodes)}")
    if st.awaiting_human is not None:
        print(f"awaiting={st.awaiting_human.kind}")
        if st.awaiting_human.gate_id:
            print(f"gate={st.awaiting_human.gate_id}")
    print(f"qa_status={st.values.get('qa_status') or ''}")
    print(f"cost_ledger={st.values.get('cost_ledger') or ''}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="geni-studio")
    parser.add_argument("--root", type=Path, default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="启动一轮并打印待办")
    run_p.add_argument("request")
    run_p.add_argument("--scenario", default="npu_operator")
    run_p.add_argument("--project", default="")
    status_p = sub.add_parser("status", help="查看 Run")
    status_p.add_argument("thread_id")
    hitl_p = sub.add_parser("hitl", help="以项目经理身份提交关卡或升级决定")
    hitl_p.add_argument("thread_id")
    hitl_p.add_argument("--decision", choices=["approved", "rejected"])
    hitl_p.add_argument("--reply", default="")
    hitl_p.add_argument("--escalation", choices=["continue", "pause", "abort"])
    cfg = sub.add_parser("config", help="查看或写入 .env 中的后端配置")
    cfg_sub = cfg.add_subparsers(dest="config_cmd", required=True)
    cfg_sub.add_parser("show")
    set_p = cfg_sub.add_parser("set")
    set_p.add_argument("key")
    set_p.add_argument("value")
    prop = sub.add_parser("proposal", help="保存、批准或合入改进提案")
    prop_sub = prop.add_subparsers(dest="proposal_cmd", required=True)
    save_p = prop_sub.add_parser("save")
    save_p.add_argument("id")
    save_p.add_argument("--target", required=True)
    save_p.add_argument("--summary", required=True)
    save_p.add_argument("--body", required=True)
    approve_p = prop_sub.add_parser("approve")
    approve_p.add_argument("id")
    approve_p.add_argument("--evidence", required=True)
    apply_p = prop_sub.add_parser("apply")
    apply_p.add_argument("id")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = args.root or factory_root()
    if args.cmd == "config" and args.config_cmd == "show":
        return cmd_show(root)
    if args.cmd == "config" and args.config_cmd == "set":
        write_env_key(env_path(root), args.key, args.value)
        print(f"已写入 {args.key}")
        return 0
    if args.cmd == "run":
        return cmd_run(args, root)
    if args.cmd == "proposal":
        return cmd_proposal(args, root)
    if args.cmd == "status":
        return cmd_status(args.thread_id)
    if args.cmd == "hitl":
        return cmd_hitl(args)
    parser.error("未知命令")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
