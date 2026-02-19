"""
Agent 工具注册表和执行函数
@author Bamzc
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from uuid import UUID

from packages.ai.brief_service import DailyBriefService
from packages.ai.graph_service import GraphService
from packages.ai.pipelines import PaperPipelines
from packages.ai.rag_service import RAGService
from packages.storage.db import check_db_connection, session_scope
from packages.storage.repositories import (
    PaperRepository,
    PipelineRunRepository,
    TopicRepository,
)

logger = logging.getLogger(__name__)


def _parse_uuid(val: str) -> UUID | None:
    """解析 UUID 字符串，失败返回 None"""
    try:
        return UUID(val)
    except ValueError:
        return None


def _require_paper(paper_id: str):
    """校验 paper_id 格式 + 查库，返回 (paper, ToolResult|None)"""
    pid = _parse_uuid(paper_id)
    if pid is None:
        return None, ToolResult(success=False, summary="无效的 paper_id 格式")
    with session_scope() as session:
        try:
            paper = PaperRepository(session).get_by_id(pid)
            return paper, None
        except ValueError:
            return None, ToolResult(
                success=False,
                summary=f"论文 {paper_id[:8]}... 不存在",
            )


@dataclass
class ToolResult:
    success: bool
    data: dict = field(default_factory=dict)
    summary: str = ""


@dataclass
class ToolProgress:
    """工具执行中间进度事件"""
    message: str
    current: int = 0
    total: int = 0


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict
    requires_confirm: bool = False


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
                        "zh_to_en", "en_to_zh", "zh_polish", "en_polish",
                        "compress", "expand", "logic_check", "deai",
                        "fig_caption", "table_caption",
                        "experiment_analysis", "reviewer", "chart_recommend",
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
    }


def execute_tool(name: str, arguments: dict) -> ToolResult:
    """同步执行工具（忽略中间进度）"""
    fn = _get_tool_handlers().get(name)
    if not fn:
        return ToolResult(success=False, summary=f"未知工具: {name}")
    try:
        result = fn(**arguments)
        if hasattr(result, "__next__"):
            final = ToolResult(success=False, summary="工具未返回结果")
            for item in result:
                if isinstance(item, ToolResult):
                    final = item
            return final
        return result
    except Exception as exc:
        logger.exception("Tool %s failed: %s", name, exc)
        return ToolResult(success=False, summary=str(exc))


def execute_tool_stream(
    name: str, arguments: dict
) -> Iterator[ToolProgress | ToolResult]:
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


def _search_papers(keyword: str, limit: int = 20) -> ToolResult:
    with session_scope() as session:
        papers = PaperRepository(session).full_text_candidates(
            query=keyword, limit=limit
        )
        items = [
            {
                "id": str(p.id),
                "title": p.title,
                "arxiv_id": p.arxiv_id,
                "abstract": (p.abstract or "")[:500],
                "publication_date": str(p.publication_date) if p.publication_date else None,
                "read_status": p.read_status.value,
                "categories": (p.metadata_json or {}).get("categories", []),
            }
            for p in papers
        ]
    return ToolResult(
        success=True,
        data={"papers": items, "count": len(items)},
        summary=f"搜索到 {len(items)} 篇论文",
    )


def _get_paper_detail(paper_id: str) -> ToolResult:
    p, err = _require_paper(paper_id)
    if err:
        return err
    with session_scope() as session:
        p = PaperRepository(session).get_by_id(UUID(paper_id))
        title = p.title or ""
        data = {
            "id": str(p.id),
            "title": title,
            "arxiv_id": p.arxiv_id,
            "abstract": (p.abstract or "")[:1000],
            "publication_date": str(p.publication_date) if p.publication_date else None,
            "read_status": p.read_status.value,
            "pdf_path": p.pdf_path,
            "has_embedding": p.embedding is not None,
            "categories": (p.metadata_json or {}).get("categories", []),
            "authors": (p.metadata_json or {}).get("authors", []),
        }
        return ToolResult(
            success=True,
            data=data,
            summary=f"论文: {title[:60]}" + ("..." if len(title) > 60 else ""),
        )


def _get_similar_papers(paper_id: str, top_k: int = 5) -> ToolResult:
    paper, err = _require_paper(paper_id)
    if err:
        return err
    pid = UUID(paper_id)
    if not paper.embedding:
        return ToolResult(
            success=False,
            summary="该论文未向量化，请先调用 embed_paper",
        )
    ids = RAGService().similar_papers(pid, top_k=top_k)
    return ToolResult(
        success=True,
        data={
            "paper_id": paper_id,
            "similar_ids": [str(x) for x in ids],
        },
        summary=f"找到 {len(ids)} 篇相似论文",
    )


def _ask_knowledge_base(
    question: str, top_k: int = 5,
) -> Iterator[ToolProgress | ToolResult]:
    """迭代 RAG：多轮检索 + 自动评估答案质量"""
    with session_scope() as session:
        repo = PaperRepository(session)
        sample = repo.list_latest(limit=1)
        if not sample:
            yield ToolResult(
                success=False,
                summary="知识库为空，请先用 ingest_arxiv 导入论文",
            )
            return

    progress_msgs: list[str] = []

    def on_progress(msg: str) -> None:
        progress_msgs.append(msg)

    try:
        yield ToolProgress(message=f"开始迭代 RAG 检索：{question[:50]}...")
        resp = RAGService().ask_iterative(
            question=question,
            max_rounds=3,
            initial_top_k=top_k,
            on_progress=on_progress,
        )
        # 逐条发送进度
        for msg in progress_msgs:
            yield ToolProgress(message=msg)
    except Exception as exc:
        logger.exception("RAG iterative failed: %s", exc)
        yield ToolResult(success=False, summary=f"知识问答失败: {exc!s}")
        return

    evidence = getattr(resp, "evidence", []) or []
    rounds = getattr(resp, "rounds", 1)
    md_parts = [f"# 知识问答：{question}\n", resp.answer, "\n\n---\n## 引用来源\n"]
    for ev in evidence[:8]:
        md_parts.append(f"- **{ev.get('title', '未知')}**\n  {ev.get('snippet', '')[:200]}\n")
    if rounds > 1:
        md_parts.append(f"\n> 经过 {rounds} 轮迭代检索优化答案\n")
    markdown = "\n".join(md_parts)
    yield ToolResult(
        success=True,
        data={
            "answer": resp.answer,
            "cited_paper_ids": [str(x) for x in resp.cited_paper_ids],
            "evidence": evidence[:5],
            "rounds": rounds,
            "title": f"知识问答：{question[:40]}",
            "markdown": markdown,
        },
        summary=f"已回答，引用 {len(resp.cited_paper_ids)} 篇论文（{rounds} 轮检索）",
    )


def _get_citation_tree(paper_id: str, depth: int = 2) -> ToolResult:
    _, err = _require_paper(paper_id)
    if err:
        return err
    result = GraphService().citation_tree(
        root_paper_id=paper_id, depth=depth
    )
    node_count = len(result.get("nodes", []))
    return ToolResult(
        success=True,
        data=result,
        summary=f"引用树含 {node_count} 个节点",
    )


def _get_timeline(keyword: str, limit: int = 100) -> ToolResult:
    result = GraphService().timeline(keyword=keyword, limit=limit)
    return ToolResult(
        success=True,
        data=result,
        summary="已获取时间线",
    )


def _list_topics() -> ToolResult:
    with session_scope() as session:
        topics = TopicRepository(session).list_topics(enabled_only=False)
        items = [
            {
                "id": str(t.id),
                "name": t.name,
                "query": t.query,
                "enabled": t.enabled,
                "max_results_per_run": t.max_results_per_run,
                "retry_limit": t.retry_limit,
            }
            for t in topics
        ]
    return ToolResult(
        success=True,
        data={"topics": items, "count": len(items)},
        summary=f"共 {len(items)} 个主题",
    )


def _get_system_status() -> ToolResult:
    from sqlalchemy import func
    from sqlalchemy import select as sa_select

    from packages.storage.models import Paper, TopicSubscription

    db_ok = check_db_connection()
    with session_scope() as session:
        paper_count = session.execute(
            sa_select(func.count()).select_from(Paper)
        ).scalar() or 0
        embedded_count = session.execute(
            sa_select(func.count()).select_from(Paper).where(
                Paper.embedding.is_not(None)
            )
        ).scalar() or 0
        topic_count = session.execute(
            sa_select(func.count()).select_from(TopicSubscription)
        ).scalar() or 0
        run_repo = PipelineRunRepository(session)
        runs = run_repo.list_latest(limit=10)
    return ToolResult(
        success=True,
        data={
            "db_connected": db_ok,
            "paper_count": paper_count,
            "embedded_count": embedded_count,
            "topic_count": topic_count,
            "recent_runs_count": len(runs),
            "recent_runs": [
                {
                    "pipeline": r.pipeline_name,
                    "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                    "created_at": str(r.created_at) if r.created_at else None,
                }
                for r in runs[:5]
            ],
        },
        summary=(
            f"论文 {paper_count} 篇（{embedded_count} 已向量化），"
            f"主题 {topic_count} 个"
            + ("" if db_ok else " ⚠️数据库异常")
        ),
    )


def _search_arxiv(query: str, max_results: int = 20) -> ToolResult:
    """搜索 arXiv，返回候选论文列表（不入库）"""
    from packages.integrations.arxiv_client import ArxivClient

    try:
        papers = ArxivClient().fetch_latest(query=query, max_results=max_results)
    except Exception as exc:
        logger.exception("ArXiv search failed: %s", exc)
        return ToolResult(success=False, summary=f"ArXiv 搜索失败: {exc!s}")

    if not papers:
        return ToolResult(
            success=True,
            data={"candidates": [], "count": 0, "query": query},
            summary="未找到相关论文",
        )

    candidates = []
    for i, p in enumerate(papers, 1):
        candidates.append({
            "index": i,
            "arxiv_id": p.arxiv_id,
            "title": p.title,
            "abstract": (p.abstract or "")[:300],
            "publication_date": str(p.publication_date) if p.publication_date else None,
            "categories": (p.metadata or {}).get("categories", []),
            "authors": (p.metadata or {}).get("authors", [])[:5],
        })

    return ToolResult(
        success=True,
        data={"candidates": candidates, "count": len(candidates), "query": query},
        summary=f"从 arXiv 搜索到 {len(candidates)} 篇候选论文",
    )


def _ingest_arxiv(
    query: str, arxiv_ids: list[str] | None = None,
) -> Iterator[ToolProgress | ToolResult]:
    """将用户选定的论文入库 → 自动分配主题 → 自动向量化 → 自动粗读"""
    from packages.integrations.arxiv_client import ArxivClient

    pipelines = PaperPipelines()
    topic_name = query.strip()

    if not arxiv_ids:
        yield ToolResult(
            success=False,
            summary="请先用 search_arxiv 搜索，再提供要入库的 arxiv_ids 列表",
        )
        return

    yield ToolProgress(message="正在准备入库...", current=0, total=0)

    # 查找或创建 Topic
    topic_id: str | None = None
    is_new_topic = False
    try:
        with session_scope() as session:
            topic_repo = TopicRepository(session)
            topic = topic_repo.get_by_name(topic_name)
            if not topic:
                topic = topic_repo.upsert_topic(
                    name=topic_name, query=topic_name, enabled=False,
                )
                is_new_topic = True
            topic_id = topic.id
    except Exception as exc:
        logger.warning("Auto-create topic '%s' failed: %s", topic_name, exc)

    # 从 arXiv 拉取选中论文的完整信息并入库
    arxiv_client = ArxivClient()
    selected_set = set(arxiv_ids)
    inserted_ids: list[str] = []

    yield ToolProgress(
        message=f"正在下载 {len(selected_set)} 篇选中论文...",
        current=0, total=len(selected_set),
    )

    # 分批搜索获取论文元数据
    all_papers = arxiv_client.fetch_latest(query=query, max_results=50)
    selected_papers = [p for p in all_papers if p.arxiv_id in selected_set]

    # 补充搜索结果中没有的（可能 ID 不在前50条中），逐个按 ID 拉取
    found_ids = {p.arxiv_id for p in selected_papers}
    missing_ids = selected_set - found_ids
    for mid in missing_ids:
        try:
            extra = arxiv_client.fetch_latest(query=f"id:{mid}", max_results=1)
            selected_papers.extend(extra)
        except Exception:
            logger.warning("Failed to fetch arxiv paper %s", mid)

    failed_papers: list[dict] = []
    ingested_papers: list[dict] = []

    with session_scope() as session:
        repo = PaperRepository(session)
        from packages.storage.repositories import PipelineRunRepository, ActionRepository
        from packages.domain.enums import ActionType
        run_repo = PipelineRunRepository(session)
        action_repo = ActionRepository(session)
        note = f"selected {len(arxiv_ids)} from query={query}"
        run = run_repo.start("ingest_arxiv", decision_note=note)
        try:
            for idx, paper in enumerate(selected_papers, 1):
                try:
                    saved = repo.upsert_paper(paper)
                    if topic_id:
                        repo.link_to_topic(saved.id, topic_id)
                    inserted_ids.append(saved.id)
                    try:
                        pdf_path = arxiv_client.download_pdf(paper.arxiv_id)
                        repo.set_pdf_path(saved.id, pdf_path)
                    except Exception:
                        pass
                    ingested_papers.append({
                        "arxiv_id": paper.arxiv_id,
                        "title": (paper.title or "")[:80],
                        "status": "ok",
                    })
                except Exception as exc:
                    logger.warning("Ingest paper %s failed: %s", paper.arxiv_id, exc)
                    failed_papers.append({
                        "arxiv_id": paper.arxiv_id,
                        "title": (paper.title or "")[:80],
                        "error": str(exc)[:120],
                        "status": "failed",
                    })
                yield ToolProgress(
                    message=f"入库 {idx}/{len(selected_papers)}: {(paper.title or '')[:40]}",
                    current=idx, total=len(selected_papers),
                )

            if inserted_ids:
                action_repo.create_action(
                    action_type=ActionType.agent_collect,
                    title=f"Agent 收集: {query[:80]}",
                    paper_ids=inserted_ids,
                    query=query,
                    topic_id=topic_id,
                )

            run_repo.finish(run.id)
        except Exception as exc:
            run_repo.fail(run.id, str(exc))
            raise

    if not inserted_ids:
        yield ToolResult(
            success=len(failed_papers) == 0,
            data={
                "ingested": 0, "query": query, "suggest_subscribe": False,
                "failed": failed_papers,
            },
            summary=f"未能入库任何论文" + (f"，{len(failed_papers)} 篇失败" if failed_papers else ""),
        )
        return

    total = len(inserted_ids)
    yield ToolProgress(
        message=f"入库 {total} 篇，开始向量化和粗读...",
        current=0, total=total,
    )

    # 向量化 + 粗读（论文间 + 论文内双重并行）
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # 最多 3 篇论文同时处理，每篇 2 个 API 调用 → 最多 6 并发
    PAPER_CONCURRENCY = 3

    # 获取所有论文标题（在 session 内）
    paper_titles: dict[str, str] = {}
    with session_scope() as sess:
        for pid_str in inserted_ids:
            try:
                p = PaperRepository(sess).get_by_id(UUID(pid_str))
                paper_titles[pid_str] = (p.title or "")[:40]
            except Exception:
                paper_titles[pid_str] = pid_str[:8]

    def _process_one(pid_str: str) -> tuple[bool, bool]:
        """单篇论文：embed ∥ skim 并行"""
        pid = UUID(pid_str)
        e_ok, s_ok = False, False
        with ThreadPoolExecutor(max_workers=2) as inner:
            fe = inner.submit(pipelines.embed_paper, pid)
            fs = inner.submit(pipelines.skim, pid)
            for fut in as_completed([fe, fs]):
                try:
                    fut.result()
                    if fut is fe:
                        e_ok = True
                    else:
                        s_ok = True
                except Exception as exc:
                    label = "embed" if fut is fe else "skim"
                    logger.warning(
                        "%s %s failed: %s",
                        label, pid_str[:8], exc,
                    )
        return e_ok, s_ok

    embed_ok, skim_ok, done = 0, 0, 0
    with ThreadPoolExecutor(max_workers=PAPER_CONCURRENCY) as pool:
        future_map = {
            pool.submit(_process_one, pid_str): pid_str
            for pid_str in inserted_ids
        }
        for fut in as_completed(future_map):
            pid_str = future_map[fut]
            done += 1
            title = paper_titles.get(pid_str, pid_str[:8])
            try:
                e_ok_i, s_ok_i = fut.result()
                embed_ok += int(e_ok_i)
                skim_ok += int(s_ok_i)
            except Exception as exc:
                logger.warning(
                    "paper %s failed: %s", pid_str[:8], exc
                )
            yield ToolProgress(
                message=f"完成 {done}/{total}: {title}",
                current=done, total=total,
            )

    yield ToolResult(
        success=True,
        data={
            "total": total,
            "embedded": embed_ok,
            "skimmed": skim_ok,
            "query": query,
            "topic": topic_name,
            "paper_ids": inserted_ids[:10],
            "suggest_subscribe": is_new_topic,
            "ingested": ingested_papers,
            "failed": failed_papers,
        },
        summary=(
            f"入库 {total} 篇 → 主题「{topic_name}」，"
            f"向量化 {embed_ok}，粗读 {skim_ok}"
            + (f"，{len(failed_papers)} 篇失败已跳过" if failed_papers else "")
        ),
    )


def _manage_subscription(
    topic_name: str,
    enabled: bool,
    schedule_frequency: str | None = None,
    schedule_time_beijing: int | None = None,
) -> ToolResult:
    """管理主题订阅：启用/禁用、设置频率和时间"""
    freq_map = {
        "daily": "每天",
        "twice_daily": "每天两次",
        "weekdays": "工作日",
        "weekly": "每周",
    }
    with session_scope() as session:
        topic_repo = TopicRepository(session)
        topic = topic_repo.get_by_name(topic_name.strip())
        if not topic:
            return ToolResult(
                success=False,
                summary=f"主题「{topic_name}」不存在",
            )
        topic.enabled = enabled
        if schedule_frequency and schedule_frequency in freq_map:
            topic.schedule_frequency = schedule_frequency
        if schedule_time_beijing is not None:
            utc_hour = (schedule_time_beijing - 8) % 24
            topic.schedule_time_utc = max(0, min(23, utc_hour))

        freq_label = freq_map.get(topic.schedule_frequency, topic.schedule_frequency)
        bj_hour = (topic.schedule_time_utc + 8) % 24
        action = "启用定时搜集" if enabled else "关闭定时搜集"
        schedule_info = f"（{freq_label} · 北京时间 {bj_hour:02d}:00）"

    return ToolResult(
        success=True,
        data={
            "topic": topic_name,
            "enabled": enabled,
            "schedule_frequency": schedule_frequency or "daily",
            "schedule_time_beijing": (schedule_time_beijing
                                      if schedule_time_beijing is not None
                                      else 5),
        },
        summary=f"已{action}：{topic_name} {schedule_info}",
    )


def _suggest_keywords(description: str) -> ToolResult:
    """AI 生成 arXiv 搜索关键词建议"""
    from packages.ai.keyword_service import KeywordService
    try:
        suggestions = KeywordService().suggest(description.strip())
    except Exception as exc:
        logger.exception("Keyword suggestion failed: %s", exc)
        return ToolResult(
            success=False, summary=f"关键词建议生成失败: {exc!s}"
        )
    if not suggestions:
        return ToolResult(
            success=True,
            data={"suggestions": []},
            summary="未能生成有效的关键词建议",
        )
    return ToolResult(
        success=True,
        data={"suggestions": suggestions},
        summary=f"生成了 {len(suggestions)} 组搜索关键词建议",
    )


def _skim_paper(paper_id: str) -> ToolResult:
    paper, err = _require_paper(paper_id)
    if err:
        return err
    if not paper.abstract:
        return ToolResult(success=False, summary="该论文缺少摘要，无法执行粗读")
    pid = UUID(paper_id)
    report = PaperPipelines().skim(pid)
    one_liner = report.one_liner
    return ToolResult(
        success=True,
        data=report.model_dump(),
        summary=f"粗读完成: {one_liner[:80]}" + ("..." if len(one_liner) > 80 else ""),
    )


def _deep_read_paper(paper_id: str) -> ToolResult:
    paper, err = _require_paper(paper_id)
    if err:
        return err
    if not paper.arxiv_id and not paper.pdf_path:
        return ToolResult(success=False, summary="该论文无 arXiv ID 且无 PDF，无法精读")
    pid = UUID(paper_id)
    report = PaperPipelines().deep_dive(pid)
    return ToolResult(
        success=True,
        data=report.model_dump(),
        summary="精读完成",
    )


def _embed_paper(paper_id: str) -> ToolResult:
    paper, err = _require_paper(paper_id)
    if err:
        return err
    pid = UUID(paper_id)
    if paper.embedding:
        return ToolResult(
            success=True,
            data={"paper_id": paper_id, "status": "already_embedded"},
            summary="该论文已有向量，跳过",
        )
    if not paper.title and not paper.abstract:
        return ToolResult(
            success=False,
            summary="该论文缺少标题和摘要，无法向量化",
        )
    PaperPipelines().embed_paper(pid)
    return ToolResult(
        success=True,
        data={"paper_id": paper_id, "status": "embedded"},
        summary="向量化完成",
    )


def _generate_wiki(type: str, keyword_or_id: str):
    """Wiki 生成 - generator，yield 进度和最终结果"""
    import time

    from packages.ai.task_manager import TaskManager

    if type == "topic":
        with session_scope() as session:
            papers = PaperRepository(session).full_text_candidates(
                query=keyword_or_id, limit=3
            )
            if not papers:
                yield ToolResult(
                    success=False,
                    summary=(
                        f"知识库中没有与 '{keyword_or_id}' "
                        "相关的论文，请先导入"
                    ),
                )
                return

        # 提交后台任务
        tm = TaskManager()
        gs = GraphService()
        task_id = tm.submit(
            task_type="topic_wiki",
            title=f"Wiki: {keyword_or_id}",
            fn=lambda progress_callback=None: gs.topic_wiki(
                keyword=keyword_or_id, limit=120,
                progress_callback=progress_callback,
            ),
        )
        yield ToolProgress(
            message=f"已提交后台任务，正在为「{keyword_or_id}」生成 Wiki...",
            current=1, total=10,
        )

        # 轮询进度
        last_msg = ""
        while True:
            time.sleep(3)
            status = tm.get_status(task_id)
            if not status:
                break
            s = status["status"]
            if s == "completed":
                break
            if s == "failed":
                yield ToolResult(
                    success=False,
                    summary=f"Wiki 生成失败: {status.get('error', '未知错误')}",
                )
                return
            msg = status.get("message", "")
            pct = status.get("progress", 0)
            step = max(1, min(9, int(pct * 10)))
            if msg and msg != last_msg:
                yield ToolProgress(message=msg, current=step, total=10)
                last_msg = msg

        result = tm.get_result(task_id) or {}
        result["title"] = f"Wiki: {keyword_or_id}"
        yield ToolProgress(message="Wiki 生成完毕", current=10, total=10)
    elif type == "paper":
        try:
            pid = UUID(keyword_or_id)
        except ValueError:
            yield ToolResult(success=False, summary="无效的 paper_id 格式")
            return
        with session_scope() as session:
            try:
                paper = PaperRepository(session).get_by_id(pid)
                paper_title = paper.title
            except ValueError:
                yield ToolResult(success=False, summary=f"论文 {keyword_or_id[:8]}... 不存在")
                return
        yield ToolProgress(message=f"正在为论文生成 Wiki...", current=1, total=2)
        result = GraphService().paper_wiki(paper_id=keyword_or_id)
        result["title"] = f"Wiki: {paper_title[:40]}"
        yield ToolProgress(message="Wiki 生成完毕，正在渲染...", current=2, total=2)
    else:
        yield ToolResult(success=False, summary=f"无效的 type: {type}，应为 topic 或 paper")
        return
    yield ToolResult(
        success=True,
        data=result,
        summary=f"已生成 {type} wiki",
    )


def _generate_daily_brief(recipient: str = ""):
    """简报生成 - generator，yield 进度和最终结果"""
    from datetime import UTC, datetime

    from packages.integrations.notifier import NotificationService
    from packages.storage.repositories import GeneratedContentRepository

    yield ToolProgress(message="正在收集今日论文数据...", current=1, total=4)
    svc = DailyBriefService()

    yield ToolProgress(message="正在生成简报内容...", current=2, total=4)
    html_content = svc.build_html()
    ts_label = datetime.now(UTC).strftime("%Y-%m-%d")
    ts_file = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    yield ToolProgress(message="正在保存简报...", current=3, total=4)
    notifier = NotificationService()
    saved_path = notifier.save_brief_html(
        f"daily_brief_{ts_file}.html", html_content
    )

    email_sent = False
    clean_recipient = recipient.strip() if recipient else ""
    if clean_recipient:
        yield ToolProgress(message="正在发送邮件...", current=4, total=4)
        email_sent = notifier.send_email_html(
            clean_recipient, "PaperMind Daily Brief", html_content
        )

    db_saved = False
    for attempt in range(3):
        try:
            with session_scope() as session:
                repo = GeneratedContentRepository(session)
                repo.create(
                    content_type="daily_brief",
                    title=f"Daily Brief: {ts_label}",
                    markdown=html_content,
                )
            db_saved = True
            break
        except Exception as exc:
            logger.warning("简报保存到数据库失败 (attempt %d): %s", attempt + 1, exc)
            import time
            time.sleep(1)

    if not db_saved:
        logger.error("简报保存到数据库最终失败，但文件已保存: %s", saved_path)

    yield ToolResult(
        success=True,
        data={
            "saved_path": saved_path,
            "email_sent": email_sent,
            "html": html_content,
            "title": f"研究简报: {ts_label}",
        },
        summary="简报已生成" + ("并发送" if email_sent else ""),
    )


def _reasoning_analysis(paper_id: str) -> ToolResult:
    """推理链深度分析"""
    from packages.ai.reasoning_service import ReasoningService

    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            paper = repo.get_by_id(UUID(paper_id))
        except (ValueError, Exception) as exc:
            return ToolResult(success=False, summary=f"论文不存在: {exc}")
        title = paper.title

    svc = ReasoningService()
    try:
        result = svc.analyze(UUID(paper_id))
    except Exception as exc:
        return ToolResult(success=False, summary=f"推理链分析失败: {exc}")

    reasoning = result.get("reasoning", {})
    steps = reasoning.get("reasoning_steps", [])
    impact = reasoning.get("impact_assessment", {})

    step_lines = []
    for s in steps[:6]:
        step_lines.append(f"**{s.get('step', '')}**: {s.get('conclusion', '')}")

    scores_text = (
        f"创新性={impact.get('novelty_score', 0):.1f} "
        f"严谨性={impact.get('rigor_score', 0):.1f} "
        f"影响力={impact.get('impact_score', 0):.1f}"
    )

    summary = (
        f"「{title}」推理链分析完成\n\n"
        + "\n".join(step_lines)
        + f"\n\n**评分**: {scores_text}\n\n"
        + f"**综合评估**: {impact.get('overall_assessment', '')[:500]}"
    )

    return ToolResult(
        success=True,
        data=reasoning,
        summary=summary,
    )


def _identify_research_gaps(keyword: str, limit: int = 100) -> ToolResult:
    """识别研究空白"""
    from packages.ai.graph_service import GraphService

    svc = GraphService()
    try:
        result = svc.detect_research_gaps(keyword=keyword, limit=limit)
    except Exception as exc:
        return ToolResult(success=False, summary=f"研究空白分析失败: {exc}")

    analysis = result.get("analysis", {})
    gaps = analysis.get("research_gaps", [])
    trend = analysis.get("trend_analysis", {})
    network = result.get("network_stats", {})

    gap_lines = []
    for i, g in enumerate(gaps[:5], 1):
        conf = g.get("confidence", 0)
        diff = g.get("difficulty", "?")
        gap_lines.append(
            f"{i}. **{g.get('gap_title', '')}** (置信度={conf:.0%}, 难度={diff})\n"
            f"   {g.get('description', '')[:200]}"
        )

    hot = ", ".join(trend.get("hot_directions", [])[:5])
    emerging = ", ".join(trend.get("emerging_opportunities", [])[:5])

    summary = (
        f"「{keyword}」领域研究空白分析\n\n"
        f"**网络规模**: {network.get('total_papers', 0)} 论文, "
        f"{network.get('edge_count', 0)} 引用边, "
        f"密度={network.get('density', 0):.4f}\n\n"
        f"**识别到 {len(gaps)} 个研究空白**:\n"
        + "\n".join(gap_lines)
        + f"\n\n**热门方向**: {hot}\n"
        + f"**新兴机会**: {emerging}\n\n"
        + f"**总结**: {analysis.get('overall_summary', '')[:500]}"
    )

    return ToolResult(
        success=True,
        data={"network_stats": network, "analysis": analysis},
        summary=summary,
    )


def _analyze_figures(paper_id: str, max_figures: int = 10) -> ToolResult:
    """提取并解读论文图表"""
    from packages.ai.figure_service import FigureService

    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            paper = repo.get_by_id(UUID(paper_id))
        except (ValueError, Exception) as exc:
            return ToolResult(success=False, summary=f"论文不存在: {exc}")
        if not paper.pdf_path:
            return ToolResult(success=False, summary="论文没有 PDF 文件，无法提取图表")
        pdf_path = paper.pdf_path
        title = paper.title

    svc = FigureService()
    try:
        results = svc.analyze_paper_figures(
            UUID(paper_id), pdf_path, max_figures=max_figures,
        )
    except Exception as exc:
        return ToolResult(success=False, summary=f"图表解读失败: {exc}")

    if not results:
        return ToolResult(
            success=True,
            data={"count": 0, "figures": []},
            summary=f"论文「{title}」中未检测到可解读的图表",
        )

    figures_data = [
        {
            "page": r.page_number,
            "type": r.image_type,
            "caption": r.caption,
            "description": r.description[:500],
        }
        for r in results
    ]

    return ToolResult(
        success=True,
        data={"count": len(results), "figures": figures_data},
        summary=f"已解读「{title}」中的 {len(results)} 张图表",
    )


def _writing_assist(action: str, text: str) -> ToolResult:
    """学术写作助手"""
    from packages.ai.writing_service import WritingService, TEMPLATE_MAP, WritingAction

    try:
        wa = WritingAction(action)
    except ValueError:
        return ToolResult(success=False, summary=f"未知的写作操作: {action}")

    template = TEMPLATE_MAP.get(wa)
    label = template.label if template else action

    try:
        result = WritingService().process(action, text)
    except Exception as exc:
        logger.exception("Writing assist failed: %s", exc)
        return ToolResult(success=False, summary=f"写作助手执行失败: {exc!s}")

    content = result.get("content", "")
    return ToolResult(
        success=True,
        data={
            "action": action,
            "label": label,
            "content": content,
            "input_tokens": result.get("input_tokens"),
            "output_tokens": result.get("output_tokens"),
        },
        summary=f"「{label}」处理完成:\n\n{content[:2000]}",
    )
