"""
LLM 调用成本估算

硬编码价格表，按 model 名称前缀匹配。单位：USD / 1M tokens。
@author Color2333
"""

from __future__ import annotations

# 顺序：更具体的模式放前面
PRICE_BOOK: list[tuple[str, float, float]] = [
    ("gpt-4.1-mini", 0.4, 1.6),
    ("gpt-4.1", 2.0, 8.0),
    ("gpt-4o-mini", 0.15, 0.6),
    ("gpt-4o", 2.5, 10.0),
    ("claude-3-haiku", 0.25, 1.25),
    ("claude-3-5-sonnet", 3.0, 15.0),
    ("glm-4.6v", 0.14, 0.14),
    ("glm-4.7", 0.1, 0.1),
    ("glm-4-flash", 0.01, 0.01),
    ("glm-4v", 0.14, 0.14),
    ("glm-4", 0.1, 0.1),
    # 小米 MiMo（套餐内 Credits 计费，此处为占位估值，仅用于成本展示）
    ("mimo-v2.5-pro", 0.5, 1.5),
    ("mimo-v2.5-tts", 0.2, 0.2),
    ("mimo-v2.5", 0.3, 0.9),
    ("mimo-v2-pro", 0.5, 1.5),
    ("mimo-v2-omni", 0.3, 0.9),
    ("mimo-v2-tts", 0.2, 0.2),
    # 阿里百炼 DashScope embedding（占位估值）
    ("text-embedding-v4", 0.05, 0.0),
    ("text-embedding-v3", 0.05, 0.0),
    ("text-embedding-v2", 0.05, 0.0),
    ("embedding", 0.005, 0.0),
]


def estimate_cost(
    *,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
) -> tuple[float, float]:
    """估算单次调用成本，返回 (input_cost_usd, output_cost_usd)"""
    model_lower = (model or "").lower()
    in_million = 1.0
    out_million = 4.0
    for key, pin, pout in PRICE_BOOK:
        if key in model_lower:
            in_million = pin
            out_million = pout
            break
    in_t = input_tokens or 0
    out_t = output_tokens or 0
    in_cost = float(in_t) * in_million / 1_000_000.0
    out_cost = float(out_t) * out_million / 1_000_000.0
    return in_cost, out_cost
