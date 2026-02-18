"""
学术写作助手服务 - 封装高质量写作 Prompt 模板
Prompt 模板来源：https://github.com/Leey21/awesome-ai-research-writing
@author Bamzc
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from packages.integrations.llm_client import LLMClient, LLMResult

logger = logging.getLogger(__name__)


class WritingAction(str, Enum):
    ZH_TO_EN = "zh_to_en"
    EN_TO_ZH = "en_to_zh"
    ZH_POLISH = "zh_polish"
    EN_POLISH = "en_polish"
    COMPRESS = "compress"
    EXPAND = "expand"
    LOGIC_CHECK = "logic_check"
    DEAI = "deai"
    FIG_CAPTION = "fig_caption"
    TABLE_CAPTION = "table_caption"
    EXPERIMENT_ANALYSIS = "experiment_analysis"
    REVIEWER = "reviewer"
    CHART_RECOMMEND = "chart_recommend"


@dataclass
class WritingTemplate:
    action: WritingAction
    label: str
    description: str
    icon: str
    placeholder: str


WRITING_TEMPLATES: list[WritingTemplate] = [
    WritingTemplate(
        action=WritingAction.ZH_TO_EN,
        label="中转英",
        description="将中文草稿翻译并润色为英文学术论文片段",
        icon="Languages",
        placeholder="在此处粘贴你的中文草稿...",
    ),
    WritingTemplate(
        action=WritingAction.EN_TO_ZH,
        label="英转中",
        description="将英文 LaTeX 代码片段翻译为流畅易读的中文文本",
        icon="BookOpen",
        placeholder="在此处粘贴你的英文 LaTeX 代码...",
    ),
    WritingTemplate(
        action=WritingAction.ZH_POLISH,
        label="中文润色",
        description="将口语化草稿重写为逻辑严密、符合学术规范的中文段落",
        icon="PenLine",
        placeholder="在此处粘贴你的中文草稿、零散想法或要点...",
    ),
    WritingTemplate(
        action=WritingAction.EN_POLISH,
        label="英文润色",
        description="深度润色英文论文，提升学术严谨性与可读性",
        icon="Sparkles",
        placeholder="在此处粘贴你的英文 LaTeX 代码...",
    ),
    WritingTemplate(
        action=WritingAction.COMPRESS,
        label="缩写",
        description="在不损失信息量的前提下微幅缩减文本长度",
        icon="Minimize2",
        placeholder="在此处粘贴你的英文 LaTeX 代码...",
    ),
    WritingTemplate(
        action=WritingAction.EXPAND,
        label="扩写",
        description="通过深挖内容深度和增强逻辑连接微幅扩写文本",
        icon="Maximize2",
        placeholder="在此处粘贴你的英文 LaTeX 代码...",
    ),
    WritingTemplate(
        action=WritingAction.LOGIC_CHECK,
        label="逻辑检查",
        description="终稿校对：一致性与逻辑核对，只报致命错误",
        icon="ShieldCheck",
        placeholder="在此处粘贴你的英文 LaTeX 代码...",
    ),
    WritingTemplate(
        action=WritingAction.DEAI,
        label="去 AI 味",
        description="将 AI 生成的机械化文本重写为自然学术表达",
        icon="Eraser",
        placeholder="在此处粘贴你的英文 LaTeX 代码...",
    ),
    WritingTemplate(
        action=WritingAction.FIG_CAPTION,
        label="图标题",
        description="将中文描述转化为符合顶会规范的英文图标题",
        icon="Image",
        placeholder="在此处粘贴你的中文描述...",
    ),
    WritingTemplate(
        action=WritingAction.TABLE_CAPTION,
        label="表标题",
        description="将中文描述转化为符合顶会规范的英文表标题",
        icon="Table",
        placeholder="在此处粘贴你的中文描述...",
    ),
    WritingTemplate(
        action=WritingAction.EXPERIMENT_ANALYSIS,
        label="实验分析",
        description="从实验数据中挖掘关键特征和趋势，生成 LaTeX 分析段落",
        icon="BarChart3",
        placeholder="在此处粘贴你的实验数据（Excel/CSV 原始表格）...",
    ),
    WritingTemplate(
        action=WritingAction.REVIEWER,
        label="审稿视角",
        description="以顶会审稿人视角严苛审视论文，发现致命问题",
        icon="Eye",
        placeholder="在此处粘贴你的论文内容（摘要+方法+实验）...",
    ),
    WritingTemplate(
        action=WritingAction.CHART_RECOMMEND,
        label="图表推荐",
        description="分析实验数据，推荐最佳学术绘图方案",
        icon="PieChart",
        placeholder="在此处粘贴你的实验数据，并简述想强调的核心结论...",
    ),
]

TEMPLATE_MAP: dict[WritingAction, WritingTemplate] = {
    t.action: t for t in WRITING_TEMPLATES
}

# Prompt 模板构建函数

def _build_zh_to_en(text: str) -> str:
    return (
        "# Role\n"
        "你是一位兼具顶尖科研写作专家与资深会议审稿人（ICML/ICLR 等）双重身份的助手。"
        "你的学术品味极高，对逻辑漏洞和语言瑕疵零容忍。\n\n"
        "# Task\n"
        "请处理我提供的【中文草稿】，将其翻译并润色为【英文学术论文片段】。\n\n"
        "# Constraints\n"
        "1. 视觉与排版：尽量不要使用加粗、斜体或引号。保持 LaTeX 源码的纯净。\n"
        "2. 风格与逻辑：逻辑严谨，用词准确，表达凝练连贯，使用常见单词。"
        "不要使用破折号（—），拒绝使用\\item列表，去除\u201cAI味\u201d。\n"
        "3. 时态规范：统一使用一般现在时描述方法和结论。\n"
        "4. 输出格式：\n"
        "   - Part 1 [LaTeX]：翻译后的英文内容（LaTeX 格式），转义特殊字符。\n"
        "   - Part 2 [Translation]：对应的中文直译。\n\n"
        "# Execution Protocol\n"
        "输出前自我审查：检查是否存在过度排版、逻辑跳跃或未翻译的中文。\n\n"
        f"# Input\n{text}"
    )


def _build_en_to_zh(text: str) -> str:
    return (
        "# Role\n"
        "你是一位资深的计算机科学领域的学术翻译官。\n\n"
        "# Task\n"
        "请将我提供的【英文 LaTeX 代码片段】翻译为流畅、易读的【中文文本】。\n\n"
        "# Constraints\n"
        "1. 语法清洗：删除 \\cite{}/\\ref{}/\\label{} 等索引命令。"
        "提取 \\textbf{text} 等修饰性命令内的文本。"
        "将 LaTeX 数学公式转化为自然语言描述。\n"
        "2. 翻译原则：严格直译，保持句式结构与英文一致，不要润色或重写。\n"
        "3. 输出格式：只输出翻译后的纯中文文本段落，不要包含任何 LaTeX 代码。\n\n"
        f"# Input\n{text}"
    )


def _build_zh_polish(text: str) -> str:
    return (
        "# Role\n"
        "你是一位资深的中文学术期刊编辑，同时也是顶尖会议的中文审稿人。\n\n"
        "# Task\n"
        "请阅读我提供的【中文草稿】，将其重写为逻辑连贯、符合中文学术规范的【论文正文段落】。\n\n"
        "# Constraints\n"
        "1. 格式与排版（Word 适配）：输出纯净的文本，严禁使用 Markdown 加粗、斜体。"
        "标点规范：严格使用中文全角标点符号。\n"
        "2. 逻辑与结构：不要机械逐句润色，先识别逻辑主线，将松散句子重新串联。"
        "遵循\u201c一个段落一个核心观点\u201d原则。\n"
        "3. 语言风格：极度正式，客观中立，保留关键技术名词。\n"
        "4. 输出格式：\n"
        "   - Part 1 [Refined Text]：重写后的中文段落。\n"
        "   - Part 2 [Logic flow]：简要说明重构思路。\n\n"
        f"# Input\n{text}"
    )


def _build_en_polish(text: str) -> str:
    return (
        "# Role\n"
        "你是一位计算机科学领域的资深学术编辑，专注于提升顶级会议投稿论文的语言质量。\n\n"
        "# Task\n"
        "请对我提供的【英文 LaTeX 代码片段】进行深度润色与重写，"
        "使其达到零错误的最高出版水准。\n\n"
        "# Constraints\n"
        "1. 学术规范：调整句式结构适配顶会写作规范，彻底修正所有语法错误。\n"
        "2. 词汇控制：使用标准学术书面语，禁止缩写形式（it's→it is），"
        "使用简洁易理解的词汇，避免名词所有格形式。\n"
        "3. 内容保持：不要展开领域缩写，保留 LaTeX 命令，保留已有格式。\n"
        "4. 结构要求：严禁列表化，保持完整段落。\n"
        "5. 输出格式：\n"
        "   - Part 1 [LaTeX]：润色后的英文 LaTeX 代码。\n"
        "   - Part 2 [Translation]：中文直译。\n"
        "   - Part 3 [Modification Log]：中文说明主要润色点。\n\n"
        f"# Input\n{text}"
    )


def _build_compress(text: str) -> str:
    return (
        "# Role\n"
        "你是一位专注于简洁性的顶级学术编辑。\n\n"
        "# Task\n"
        "请将我提供的【英文 LaTeX 代码片段】进行微幅缩减（减少约 5-15 个单词）。\n\n"
        "# Constraints\n"
        "1. 严禁大删大改，必须保留所有核心信息和技术细节。\n"
        "2. 缩减手段：句法压缩，剔除冗余填充词（如 in order to → to）。\n"
        "3. 保持 LaTeX 源码纯净，不要使用加粗斜体引号，不用破折号，不用列表。\n"
        "4. 输出格式：\n"
        "   - Part 1 [LaTeX]：缩减后的英文 LaTeX 代码。\n"
        "   - Part 2 [Translation]：中文直译。\n"
        "   - Part 3 [Modification Log]：中文说明调整。\n\n"
        f"# Input\n{text}"
    )


def _build_expand(text: str) -> str:
    return (
        "# Role\n"
        "你是一位专注于逻辑流畅度的顶级学术编辑。\n\n"
        "# Task\n"
        "请将我提供的【英文 LaTeX 代码片段】进行微幅扩写（增加约 5-15 个单词）。\n\n"
        "# Constraints\n"
        "1. 严禁恶意注水，不要添加无意义的形容词。\n"
        "2. 扩写手段：深度挖掘隐含结论/因果关系，增加必要连接词，表达升级。\n"
        "3. 保持 LaTeX 源码纯净，不要使用加粗斜体引号，不用破折号，不用列表。\n"
        "4. 输出格式：\n"
        "   - Part 1 [LaTeX]：扩写后的英文 LaTeX 代码。\n"
        "   - Part 2 [Translation]：中文直译。\n"
        "   - Part 3 [Modification Log]：中文说明调整。\n\n"
        f"# Input\n{text}"
    )


def _build_logic_check(text: str) -> str:
    return (
        "# Role\n"
        "你是一位负责论文终稿校对的学术助手。\n\n"
        "# Task\n"
        "请对我提供的【英文 LaTeX 代码片段】进行最后的一致性与逻辑核对。\n\n"
        "# Constraints\n"
        "1. 审查阈值：预设草稿已经过多轮修改，质量较高。"
        "仅在遇到致命逻辑断层、术语混乱或严重语法错误时才提出意见。\n"
        "2. 审查维度：致命逻辑矛盾、术语一致性、严重语病（Chinglish）。\n"
        "3. 输出格式：无问题则输出 [检测通过，无实质性问题]。"
        "有问题则用中文分点简要指出。\n\n"
        f"# Input\n{text}"
    )


def _build_deai(text: str) -> str:
    return (
        "# Role\n"
        "你是一位计算机科学领域的资深学术编辑，专注于提升论文的自然度。\n\n"
        "# Task\n"
        "请对我提供的【英文 LaTeX 代码片段】进行\u201c去 AI 化\u201d重写。\n\n"
        "# Constraints\n"
        "1. 词汇规范化：优先使用朴实精准的学术词汇。"
        "避免：leverage, delve into, tapestry, underscore, unveil 等被滥用的词。\n"
        "2. 结构自然化：严禁列表格式，移除机械连接词，减少破折号。\n"
        "3. 排版规范：禁用强调格式（加粗/斜体）。\n"
        "4. 修改阈值：如果原文已足够自然，保留原文。\n"
        "5. 输出格式：\n"
        "   - Part 1 [LaTeX]：重写后的代码。\n"
        "   - Part 2 [Translation]：中文直译。\n"
        "   - Part 3 [Modification Log]：调整说明或\u201c[检测通过]\u201d。\n\n"
        f"# Input\n{text}"
    )


def _build_fig_caption(text: str) -> str:
    return (
        "# Role\n"
        "你是一位经验丰富的学术编辑，擅长撰写精准规范的论文插图标题。\n\n"
        "# Task\n"
        "请将我提供的【中文描述】转化为符合顶级会议规范的【英文图标题】。\n\n"
        "# Constraints\n"
        "1. 名词性短语用 Title Case，完整句子用 Sentence case。\n"
        "2. 极简原则：去除冗余开头，直接描述图表内容。\n"
        "3. 只输出英文标题文本本身，不要包含 Figure 1: 前缀。\n\n"
        f"# Input\n{text}"
    )


def _build_table_caption(text: str) -> str:
    return (
        "# Role\n"
        "你是一位经验丰富的学术编辑，擅长撰写精准规范的论文表格标题。\n\n"
        "# Task\n"
        "请将我提供的【中文描述】转化为符合顶级会议规范的【英文表标题】。\n\n"
        "# Constraints\n"
        "1. 名词性短语用 Title Case，完整句子用 Sentence case。\n"
        "2. 常用句式：Comparison with, Ablation study on, Results on。\n"
        "3. 只输出英文标题文本本身，不要包含 Table 1: 前缀。\n\n"
        f"# Input\n{text}"
    )


def _build_experiment_analysis(text: str) -> str:
    return (
        "# Role\n"
        "你是一位具有敏锐洞察力的资深数据科学家。\n\n"
        "# Task\n"
        "请仔细阅读我提供的【实验数据】，挖掘关键特征和趋势，"
        "整理为符合顶级会议标准的 LaTeX 分析段落。\n\n"
        "# Constraints\n"
        "1. 数据真实性：所有结论必须严格基于输入数据，严禁编造。\n"
        "2. 分析深度：拒绝简单报账式描述，重点比较和趋势分析。\n"
        "3. 排版格式：严禁加粗斜体，使用 \\paragraph{核心结论} + 分析文本。\n"
        "4. 输出格式：\n"
        "   - Part 1 [LaTeX]：分析后的 LaTeX 代码。\n"
        "   - Part 2 [Translation]：中文直译。\n\n"
        f"# Input\n{text}"
    )


def _build_reviewer(text: str) -> str:
    return (
        "# Role\n"
        "你是一位以严苛著称的资深学术审稿人，熟悉计算机科学顶级会议评审标准。\n\n"
        "# Task\n"
        "请深入分析我提供的【论文内容】，撰写一份严厉但有建设性的审稿报告。\n\n"
        "# Constraints\n"
        "1. 默认态度：抱着拒稿的预设心态审查，除非论文亮点足以说服你。\n"
        "2. 拒绝客套，直接切入核心缺陷。\n"
        "3. 输出格式：\n"
        "   - Part 1 [Review Report]（中文）：\n"
        "     * Summary: 一句话总结\n"
        "     * Strengths: 1-2 点真正有价值的贡献\n"
        "     * Weaknesses (Critical): 3-5 个致命问题\n"
        "     * Rating: 1-10分\n"
        "   - Part 2 [Strategic Advice]：中文改稿建议和行动指南。\n\n"
        f"# Input\n{text}"
    )


def _build_chart_recommend(text: str) -> str:
    return (
        "# Role\n"
        "你是一位就职于顶级科学期刊的资深数据可视化专家。\n\n"
        "# Task\n"
        "请分析我提供的实验数据或实验目的，推荐 1-2 种最佳绘图方案。\n\n"
        "# Constraints\n"
        "1. 优先从学术标准图表中选择（柱状图、折线图、热力图、雷达图、"
        "散点图、ROC曲线、箱线图、小提琴图等）。\n"
        "2. 若数据组间差异巨大，建议补救方案（断裂轴、对数坐标、归一化）。\n"
        "3. 输出结构：推荐方案 → 核心理由 → 视觉设计规范。\n"
        "4. 用中文回答。\n\n"
        f"# Input\n{text}"
    )


_PROMPT_BUILDERS: dict[WritingAction, callable] = {
    WritingAction.ZH_TO_EN: _build_zh_to_en,
    WritingAction.EN_TO_ZH: _build_en_to_zh,
    WritingAction.ZH_POLISH: _build_zh_polish,
    WritingAction.EN_POLISH: _build_en_polish,
    WritingAction.COMPRESS: _build_compress,
    WritingAction.EXPAND: _build_expand,
    WritingAction.LOGIC_CHECK: _build_logic_check,
    WritingAction.DEAI: _build_deai,
    WritingAction.FIG_CAPTION: _build_fig_caption,
    WritingAction.TABLE_CAPTION: _build_table_caption,
    WritingAction.EXPERIMENT_ANALYSIS: _build_experiment_analysis,
    WritingAction.REVIEWER: _build_reviewer,
    WritingAction.CHART_RECOMMEND: _build_chart_recommend,
}


class WritingService:
    """学术写作助手服务"""

    def __init__(self) -> None:
        self.llm = LLMClient()

    @staticmethod
    def list_templates() -> list[dict]:
        """返回所有写作模板信息"""
        return [
            {
                "action": t.action.value,
                "label": t.label,
                "description": t.description,
                "icon": t.icon,
                "placeholder": t.placeholder,
            }
            for t in WRITING_TEMPLATES
        ]

    def process(
        self,
        action: str,
        text: str,
        *,
        max_tokens: int = 4096,
    ) -> dict:
        """执行写作操作"""
        try:
            writing_action = WritingAction(action)
        except ValueError:
            raise ValueError(f"未知的写作操作: {action}")

        builder = _PROMPT_BUILDERS.get(writing_action)
        if not builder:
            raise ValueError(f"写作操作 {action} 没有对应的 Prompt 构建器")

        prompt = builder(text)
        result: LLMResult = self.llm.summarize_text(
            prompt, stage="writing", max_tokens=max_tokens,
        )
        self.llm.trace_result(
            result,
            stage="writing",
            prompt_digest=f"{action}:{text[:80]}",
        )

        template = TEMPLATE_MAP[writing_action]
        return {
            "action": action,
            "label": template.label,
            "content": result.content,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "total_cost_usd": result.total_cost_usd,
        }

    def refine(
        self,
        messages: list[dict],
        *,
        max_tokens: int = 4096,
    ) -> dict:
        """基于对话历史进行多轮微调"""
        if not messages:
            raise ValueError("消息列表不能为空")

        parts: list[str] = [
            "你是一位资深的学术写作助手。以下是此前的对话记录，"
            "请根据用户的最新指令，在之前结果的基础上继续优化。\n"
            "请只输出优化后的完整内容，不要输出额外解释（除非用户明确要求）。\n\n"
        ]

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                parts.append(f"### 用户\n{content}\n")
            else:
                parts.append(f"### 助手\n{content}\n")

        prompt = "\n".join(parts)
        result: LLMResult = self.llm.summarize_text(
            prompt, stage="writing", max_tokens=max_tokens,
        )

        last_user = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user = msg.get("content", "")
                break

        self.llm.trace_result(
            result,
            stage="writing_refine",
            prompt_digest=f"refine:{last_user[:80]}",
        )

        return {
            "content": result.content,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "total_cost_usd": result.total_cost_usd,
        }
