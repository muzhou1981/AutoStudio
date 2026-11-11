"""Codex 推理强度配置；无需安装 SDK 即可保存和展示设置。"""

import os

from geni_studio.backends.runtime import current_config

# 对应固定依赖 openai-codex 0.167.0 的 ReasoningEffort 协议枚举。
# 协议接受不等于每个模型都支持；模型限制仍由 Codex 服务端校验。
REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
REASONING_ENV = "GENI_STUDIO_CODEX_REASONING_EFFORT"


def normalize_reasoning_effort(value: str | None) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("Codex reasoning_effort 必须是字符串")
    value = value.strip().lower()
    if value in {"", "default", "auto"}:
        return ""
    if value not in REASONING_EFFORTS:
        raise ValueError("Codex reasoning_effort 须为 default 或 " + ", ".join(REASONING_EFFORTS))
    return value


def factory_reasoning_effort() -> str:
    frozen = current_config()
    if frozen is not None:
        # 历史 Run 未保存此项时沿用 SDK，不能读取后来更改的工厂设置。
        return normalize_reasoning_effort(frozen.get("_codex_reasoning_effort"))
    return normalize_reasoning_effort(os.environ.get(REASONING_ENV))
