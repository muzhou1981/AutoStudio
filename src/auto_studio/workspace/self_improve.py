"""自改进是否允许启动。桥接未就绪时返回退出码，不创建工作树。"""

from __future__ import annotations


def self_improve_block_reason(bridge_ready: bool) -> int | None:
    if not bridge_ready:
        return 2
    return None
