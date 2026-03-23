"""
场景化模型配置 - 按使用场景分配不同成本的模型
"""

from enum import Enum


class ModelTier(str, Enum):
    """模型成本分层"""

    ECONOMY = "economy"  # 经济型：最便宜，适合简单任务（摘要、分类、关键词提取）
    STANDARD = "standard"  # 标准型：性价比，适合一般任务（RAG、对话、翻译）
    PREMIUM = "premium"  # 高级型：较贵，适合复杂任务（深度分析、写作、推理）
    VISION = "vision"  # 视觉型：图像/图表理解


MODEL_TIER_SCENARIOS = {
    # Economy 场景 - 快速 + 便宜
    ModelTier.ECONOMY: [
        "skim",  # 论文粗读
        "keyword",  # 关键词提取
        "classify",  # 分类/标签
        "embedding",  # 向量化
        "summarize_short",  # 短摘要
    ],
    # Standard 场景 - 性价比
    ModelTier.STANDARD: [
        "translate",  # 翻译
        "rag",  # RAG 问答
        "chat",  # Agent 对话
        "explain",  # 概念解释
        "summarize_medium",  # 中等摘要
    ],
    # Premium 场景 - 高质量
    ModelTier.PREMIUM: [
        "deep",  # 论文精读
        "writing",  # 学术写作
        "reasoning",  # 逻辑推理
        "figure_analysis",  # 图表分析
        "wiki",  # Wiki 生成
        "summarize_long",  # 长文档摘要
    ],
    # Vision 场景
    ModelTier.VISION: [
        "vision",  # 视觉理解
        "ocr",  # OCR 识别
    ],
}


# 预设模型配置模板（常见服务商）
PRESET_MODEL_CONFIGS = {
    "zhipu": {
        ModelTier.ECONOMY: "glm-4-flash",  # ~¥0.001/1k tokens
        ModelTier.STANDARD: "glm-4.7",  # ~¥0.005/1k tokens
        ModelTier.PREMIUM: "glm-4-air",  # ~¥0.01/1k tokens
        ModelTier.VISION: "glm-4v-flash",  # 视觉
    },
    "openai": {
        ModelTier.ECONOMY: "gpt-4o-mini",  # $0.00015/1k
        ModelTier.STANDARD: "gpt-4o",  # $0.005/1k
        ModelTier.PREMIUM: "gpt-4.5-preview",  # $0.075/1k
        ModelTier.VISION: "gpt-4o",
    },
    "anthropic": {
        ModelTier.ECONOMY: "claude-3-haiku",  # $0.00025/1k
        ModelTier.STANDARD: "claude-3.5-sonnet",  # $0.003/1k
        ModelTier.PREMIUM: "claude-3.5-opus",  # $0.015/1k
        ModelTier.VISION: "claude-3.5-sonnet",
    },
    "siliconflow": {
        ModelTier.ECONOMY: "Qwen/Qwen2.5-7B-Instruct",  # 免费/极便宜
        ModelTier.STANDARD: "Qwen/Qwen2.5-72B-Instruct",  # 便宜
        ModelTier.PREMIUM: "deepseek-ai/DeepSeek-V3",  # 性价比高
        ModelTier.VISION: "Pro/Qwen/Qwen2.5-VL-72B-Instruct",
    },
}
