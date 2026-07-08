"""工具注册表、OpenAI 工具格式转换、工具分发与流式执行。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from packages.ai.tools.handlers.batch import (
    _batch_deep_read_papers,
    _batch_embed_papers,
    _batch_skim_papers,
    _get_batch_job_status,
)
from packages.ai.tools.handlers.figures import _analyze_figures
from packages.ai.tools.handlers.ingest import _ingest_arxiv, _search_arxiv
from packages.ai.tools.handlers.read import _deep_read_paper, _embed_paper, _skim_paper
from packages.ai.tools.handlers.reasoning import _reasoning_analysis
from packages.ai.tools.handlers.search import (
    _ask_knowledge_base,
    _get_citation_tree,
    _get_paper_detail,
    _get_similar_papers,
    _get_timeline,
    _list_papers_by_filter,
    _search_papers,
    _suggest_keywords,
)
from packages.ai.tools.handlers.subscription import _list_topics, _manage_subscription
from packages.ai.tools.handlers.system import _get_system_status
from packages.ai.tools.handlers.wiki_brief import (
    _generate_daily_brief,
    _generate_wiki,
    _identify_research_gaps,
)
from packages.ai.tools.handlers.writing import _writing_assist
from packages.ai.tools.types import ToolDef, ToolProgress, ToolResult

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)


TOOL_REGISTRY: list[ToolDef] = [
    ToolDef(
        name="search_papers",
        description="在数据库中按关键词搜索论文（标题和摘要全文匹配）",
        parameters={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词"},
                "limit": {
                    "type": "integer",
                    "description": "返回数量上限",
                    "default": 20,
                },
            },
            "required": ["keyword"],
        },
        requires_confirm=False,
    ),
    ToolDef(
        name="get_paper_detail",
        description="获取单篇论文的详细信息",
        parameters={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string", "description": "论文 UUID"},
            },
            "required": ["paper_id"],
        },
        requires_confirm=False,
    ),
    ToolDef(
        name="get_similar_papers",
        description="基于向量相似度获取与指定论文相似的论文 ID 列表",
        parameters={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string", "description": "论文 UUID"},
                "top_k": {
                    "type": "integer",
                    "description": "返回数量",
                    "default": 5,
                },
            },
            "required": ["paper_id"],
        },
        requires_confirm=False,
    ),
    ToolDef(
        name="ask_knowledge_base",
        description="基于 RAG 向知识库提问，返回答案及引用论文 ID",
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "问题内容"},
                "top_k": {
                    "type": "integer",
                    "description": "检索论文数量",
                    "default": 5,
                },
            },
            "required": ["question"],
        },
        requires_confirm=False,
    ),
    ToolDef(
        name="get_citation_tree",
        description="获取论文的引用树结构",
        parameters={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string", "description": "论文 UUID"},
                "depth": {
                    "type": "integer",
                    "description": "树深度",
                    "default": 2,
                },
            },
            "required": ["paper_id"],
        },
        requires_confirm=False,
    ),
    ToolDef(
        name="get_timeline",
        description="按关键词获取论文时间线",
        parameters={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "关键词"},
                "limit": {
                    "type": "integer",
                    "description": "返回数量上限",
                    "default": 100,
                },
            },
            "required": ["keyword"],
        },
        requires_confirm=False,
    ),
    ToolDef(
        name="list_topics",
        description="列出所有主题订阅",
        parameters={"type": "object", "properties": {}},
        requires_confirm=False,
    ),
    ToolDef(
        name="get_system_status",
        description="检查系统状态：数据库连接、论文数、主题数、Pipeline 运行数",
        parameters={"type": "object", "properties": {}},
        requires_confirm=False,
    ),
    ToolDef(
        name="search_arxiv",
        description="搜索 arXiv 论文，返回候选列表供用户筛选（不入库）",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "arXiv 搜索查询"},
                "max_results": {
                    "type": "integer",
                    "description": "最大搜索数量",
                    "default": 20,
                },
                "days_back": {
                    "type": "integer",
                    "description": (
                        "只检索最近 N 天提交的论文（默认 0 = 不限日期，可搜到经典/老论文）。"
                        "需要最新增量时传 7 或 30。"
                    ),
                    "default": 0,
                },
                "sort_by": {
                    "type": "string",
                    "description": "排序方式：relevance（相关性，默认）/ submittedDate（最新优先）",
                    "default": "relevance",
                },
            },
            "required": ["query"],
        },
        requires_confirm=False,
    ),
    ToolDef(
        name="ingest_arxiv",
        description="将用户选定的 arXiv 论文入库（需提供 arxiv_ids 列表）",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "原始搜索查询（用于主题关联）"},
                "arxiv_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要入库的 arXiv ID 列表",
                },
            },
            "required": ["query", "arxiv_ids"],
        },
        requires_confirm=True,
    ),
    ToolDef(
        name="skim_paper",
        description="对论文执行粗读 Pipeline",
        parameters={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string", "description": "论文 UUID"},
            },
            "required": ["paper_id"],
        },
        requires_confirm=True,
    ),
    ToolDef(
        name="deep_read_paper",
        description="对论文执行精读 Pipeline",
        parameters={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string", "description": "论文 UUID"},
            },
            "required": ["paper_id"],
        },
        requires_confirm=True,
    ),
    ToolDef(
        name="embed_paper",
        description="对论文执行向量化嵌入",
        parameters={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string", "description": "论文 UUID"},
            },
            "required": ["paper_id"],
        },
        requires_confirm=True,
    ),
    ToolDef(
        name="generate_wiki",
        description="生成主题或论文的 Wiki 内容",
        parameters={
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "description": "wiki 类型：topic 或 paper",
                    "enum": ["topic", "paper"],
                },
                "keyword_or_id": {
                    "type": "string",
                    "description": "topic 时为关键词，paper 时为论文 UUID",
                },
            },
            "required": ["type", "keyword_or_id"],
        },
        requires_confirm=True,
    ),
    ToolDef(
        name="generate_daily_brief",
        description="生成并发布每日简报",
        parameters={
            "type": "object",
            "properties": {
                "recipient": {
                    "type": "string",
                    "description": "邮件接收人，空则仅保存不发送",
                    "default": "",
                },
            },
        },
        requires_confirm=True,
    ),
    ToolDef(
        name="manage_subscription",
        description="管理主题订阅：启用/禁用、设置频率和时间",
        parameters={
            "type": "object",
            "properties": {
                "topic_name": {
                    "type": "string",
                    "description": "主题名称",
                },
                "enabled": {
                    "type": "boolean",
                    "description": "true=启用定时搜集，false=关闭",
                },
                "schedule_frequency": {
                    "type": "string",
                    "enum": ["daily", "twice_daily", "weekdays", "weekly"],
                    "description": "搜集频率：每天/每天两次/工作日/每周",
                },
                "schedule_time_beijing": {
                    "type": "integer",
                    "description": "北京时间执行小时（0-23），默认 5 点",
                },
            },
            "required": ["topic_name", "enabled"],
        },
        requires_confirm=True,
    ),
    ToolDef(
        name="suggest_keywords",
        description="根据用户自然语言描述，AI 生成 arXiv 搜索关键词建议",
        parameters={
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "用户的研究兴趣描述（自然语言）",
                },
            },
            "required": ["description"],
        },
        requires_confirm=False,
    ),
    ToolDef(
        name="reasoning_analysis",
        description="对论文进行推理链深度分析：方法推导链、实验验证链、创新性多维评估",
        parameters={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string", "description": "论文 UUID"},
            },
            "required": ["paper_id"],
        },
        requires_confirm=True,
    ),
    ToolDef(
        name="identify_research_gaps",
        description="分析领域引用网络的稀疏区域，识别研究空白和未探索方向",
        parameters={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "领域关键词"},
                "limit": {
                    "type": "integer",
                    "description": "分析论文数量",
                    "default": 100,
                },
            },
            "required": ["keyword"],
        },
        requires_confirm=False,
    ),
    ToolDef(
        name="writing_assist",
        description="学术写作助手：支持中转英、英转中、英文润色、中文润色、缩写、扩写、逻辑检查、去AI味、生成图/表标题、实验分析、审稿视角、图表推荐",
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "zh_to_en",
                        "en_to_zh",
                        "zh_polish",
                        "en_polish",
                        "compress",
                        "expand",
                        "logic_check",
                        "deai",
                        "fig_caption",
                        "table_caption",
                        "experiment_analysis",
                        "reviewer",
                        "chart_recommend",
                    ],
                    "description": "写作操作类型",
                },
                "text": {
                    "type": "string",
                    "description": "要处理的文本内容",
                },
            },
            "required": ["action", "text"],
        },
        requires_confirm=False,
    ),
    ToolDef(
        name="analyze_figures",
        description="提取并解读论文 PDF 中的图表和公式，用 Vision 模型生成解读报告",
        parameters={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string", "description": "论文 UUID"},
                "max_figures": {
                    "type": "integer",
                    "description": "最大提取图表数量",
                    "default": 10,
                },
            },
            "required": ["paper_id"],
        },
        requires_confirm=True,
    ),
    ToolDef(
        name="list_papers_by_filter",
        description="按日期范围/状态/主题/标签/分类组合筛选论文，优先用它按日期筛选，不要用 search_papers + keyword 传日期",
        parameters={
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": '起始日期 ISO 格式 "2026-05-01"',
                },
                "end_date": {
                    "type": "string",
                    "description": '结束日期 ISO 格式 "2026-05-31"',
                },
                "date_field": {
                    "type": "string",
                    "description": '日期字段 "created_at" 或 "publication_date"',
                    "default": "created_at",
                },
                "status": {
                    "type": "string",
                    "description": "阅读状态：unread / skimmed / deep_read",
                },
                "topic_id": {"type": "string", "description": "主题 UUID"},
                "tag_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "标签 UUID 列表",
                },
                "search": {"type": "string", "description": "文本搜索（标题/摘要）"},
                "sort_by": {
                    "type": "string",
                    "description": "排序字段",
                    "default": "created_at",
                },
                "sort_order": {
                    "type": "string",
                    "description": "排序方向 asc/desc",
                    "default": "desc",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回数量上限",
                    "default": 100,
                },
            },
        },
        requires_confirm=False,
    ),
    ToolDef(
        name="batch_skim_papers",
        description="批量粗读多篇论文，传入 paper_ids 列表一次性入队，立刻返回 job_id",
        parameters={
            "type": "object",
            "properties": {
                "paper_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "论文 UUID 列表",
                },
            },
            "required": ["paper_ids"],
        },
        requires_confirm=True,
    ),
    ToolDef(
        name="batch_deep_read_papers",
        description="批量精读多篇论文，传入 paper_ids 列表一次性入队，立刻返回 job_id",
        parameters={
            "type": "object",
            "properties": {
                "paper_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "论文 UUID 列表",
                },
            },
            "required": ["paper_ids"],
        },
        requires_confirm=True,
    ),
    ToolDef(
        name="batch_embed_papers",
        description="批量向量化多篇论文，传入 paper_ids 列表一次性入队，立刻返回 job_id",
        parameters={
            "type": "object",
            "properties": {
                "paper_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "论文 UUID 列表",
                },
            },
            "required": ["paper_ids"],
        },
        requires_confirm=True,
    ),
    ToolDef(
        name="get_batch_job_status",
        description="查询批量任务进度（done/total/failed），用户问'跑完了吗'时调用",
        parameters={
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "批量任务 ID"},
            },
            "required": ["job_id"],
        },
        requires_confirm=False,
    ),
]


def get_openai_tools() -> list[dict]:
    """将 TOOL_REGISTRY 转为 OpenAI function calling 格式"""
    out: list[dict] = []
    for t in TOOL_REGISTRY:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
        )
    return out


def _get_tool_handlers() -> dict:
    return {
        "search_papers": _search_papers,
        "get_paper_detail": _get_paper_detail,
        "get_similar_papers": _get_similar_papers,
        "ask_knowledge_base": _ask_knowledge_base,
        "get_citation_tree": _get_citation_tree,
        "get_timeline": _get_timeline,
        "list_topics": _list_topics,
        "get_system_status": _get_system_status,
        "search_arxiv": _search_arxiv,
        "ingest_arxiv": _ingest_arxiv,
        "skim_paper": _skim_paper,
        "deep_read_paper": _deep_read_paper,
        "embed_paper": _embed_paper,
        "generate_wiki": _generate_wiki,
        "generate_daily_brief": _generate_daily_brief,
        "manage_subscription": _manage_subscription,
        "suggest_keywords": _suggest_keywords,
        "analyze_figures": _analyze_figures,
        "reasoning_analysis": _reasoning_analysis,
        "identify_research_gaps": _identify_research_gaps,
        "writing_assist": _writing_assist,
        "list_papers_by_filter": _list_papers_by_filter,
        "batch_skim_papers": _batch_skim_papers,
        "batch_deep_read_papers": _batch_deep_read_papers,
        "batch_embed_papers": _batch_embed_papers,
        "get_batch_job_status": _get_batch_job_status,
    }


def execute_tool_stream(name: str, arguments: dict) -> Iterator[ToolProgress | ToolResult]:
    """流式执行工具，yield 进度事件和最终结果"""
    fn = _get_tool_handlers().get(name)
    if not fn:
        yield ToolResult(success=False, summary=f"未知工具: {name}")
        return
    try:
        result = fn(**arguments)
        if hasattr(result, "__next__"):
            yield from result
        else:
            yield result
    except Exception as exc:
        logger.exception("Tool %s failed: %s", name, exc)
        yield ToolResult(success=False, summary=str(exc))
