"""Agent 节点与 Workflow Profile（skip_nodes）衔接。"""

from collections.abc import Callable
from typing import TypeVar

from geni_studio.config.context import ConfigError, build_run_context_from_state

TState = TypeVar("TState")


def skip_if_disabled(node_name: str) -> Callable[[Callable[[TState], dict]], Callable[[TState], dict]]:
    """profile 中 skip_nodes 命中时 no-op，不调度 Agent 逻辑。"""

    def decorator(fn: Callable[[TState], dict]) -> Callable[[TState], dict]:
        def wrapped(state: TState) -> dict:
            try:
                ctx = build_run_context_from_state(state)  # type: ignore[arg-type]
            except ConfigError:
                return fn(state)
            if not ctx.is_node_enabled(node_name):
                return {
                    "run_record": (
                        f"[skipped:profile] node={node_name} "
                        f"profile={ctx.profile_id or '(未指定)'}"
                    )
                }
            return fn(state)

        wrapped.__name__ = fn.__name__
        return wrapped

    return decorator
