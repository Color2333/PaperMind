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
        ModelTier.ECONOMY: "glm-4.7",  # 统一使用 GLM-4.7
        ModelTier.STANDARD: "glm-4.7",  # 统一使用 GLM-4.7
        ModelTier.PREMIUM: "glm-4.7",  # 统一使用 GLM-4.7
        ModelTier.VISION: "glm-4.6v",  # 视觉专用
    },
}
