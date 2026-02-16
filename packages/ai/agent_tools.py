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
        name="ingest_arxiv",
        description="从 arXiv 拉取论文并写入数据库",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "arXiv 搜索查询"},
                "max_results": {
                    "type": "integer",
                    "description": "最大拉取数量",
                    "default": 20,
                },
            },
            "required": ["query"],
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
        description="管理主题订阅：启用或禁用定时自动搜集",
        parameters={
            "type": "object",
            "properties": {
                "topic_name": {
                    "type": "string",
                    "description": "主题名称",
                },
                "enabled": {
                    "type": "boolean",
                    "description": "true=启用定时搜集，false=仅一次",
                },
            },
            "required": ["topic_name", "enabled"],
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
        "ingest_arxiv": _ingest_arxiv,
        "skim_paper": _skim_paper,
        "deep_read_paper": _deep_read_paper,
        "embed_paper": _embed_paper,
        "generate_wiki": _generate_wiki,
        "generate_daily_brief": _generate_daily_brief,
        "manage_subscription": _manage_subscription,
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
    try:
        pid = UUID(paper_id)
    except ValueError:
        return ToolResult(success=False, summary="无效的 paper_id 格式")
    with session_scope() as session:
        try:
            p = PaperRepository(session).get_by_id(pid)
        except ValueError:
            return ToolResult(
                success=False,
                summary=f"论文 {paper_id[:8]}... 不存在",
            )
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
    try:
        pid = UUID(paper_id)
    except ValueError:
        return ToolResult(success=False, summary="无效的 paper_id 格式")
    # 先检查论文存在和向量
    with session_scope() as session:
        try:
            paper = PaperRepository(session).get_by_id(pid)
        except ValueError:
            return ToolResult(
                success=False,
                summary=f"论文 {paper_id[:8]}... 不存在",
            )
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


def _ask_knowledge_base(question: str, top_k: int = 5) -> ToolResult:
    # 先检查知识库是否有论文
    with session_scope() as session:
        repo = PaperRepository(session)
        sample = repo.list_latest(limit=1)
        if not sample:
            return ToolResult(
                success=False,
                summary="知识库为空，请先用 ingest_arxiv 导入论文",
            )
    try:
        resp = RAGService().ask(question, top_k=top_k)
    except Exception as exc:
        logger.exception("RAG ask failed: %s", exc)
        return ToolResult(
            success=False,
            summary=f"知识问答失败: {exc!s}",
        )
    evidence = getattr(resp, "evidence", []) or []
    # 构建可保存的 markdown 报告
    md_parts = [f"# 知识问答：{question}\n", resp.answer, "\n\n---\n## 引用来源\n"]
    for ev in evidence[:8]:
        md_parts.append(f"- **{ev.get('title', '未知')}**\n  {ev.get('snippet', '')[:200]}\n")
    markdown = "\n".join(md_parts)
    return ToolResult(
        success=True,
        data={
            "answer": resp.answer,
            "cited_paper_ids": [str(x) for x in resp.cited_paper_ids],
            "evidence": evidence[:5],
            "title": f"知识问答：{question[:40]}",
            "markdown": markdown,
        },
        summary=f"已回答，引用 {len(resp.cited_paper_ids)} 篇论文",
    )


def _get_citation_tree(paper_id: str, depth: int = 2) -> ToolResult:
    try:
        pid = UUID(paper_id)
    except ValueError:
        return ToolResult(success=False, summary="无效的 paper_id 格式")
    # 先校验论文存在
    with session_scope() as session:
        try:
            PaperRepository(session).get_by_id(pid)
        except ValueError:
            return ToolResult(
                success=False,
                summary=f"论文 {paper_id[:8]}... 不存在",
            )
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


def _ingest_arxiv(
    query: str, max_results: int = 20
) -> Iterator[ToolProgress | ToolResult]:
    """摄入论文 → 自动分配主题 → 自动向量化 → 自动粗读（带进度）"""
    pipelines = PaperPipelines()
    topic_name = query.strip()

    yield ToolProgress(message="正在搜索 arXiv...", current=0, total=0)

    # 1) 查找或创建 Topic（默认 enabled=False，仅搜一次）
    topic_id: str | None = None
    is_new_topic = False
    try:
        with session_scope() as session:
            topic_repo = TopicRepository(session)
            topic = topic_repo.get_by_name(topic_name)
            if not topic:
                topic = topic_repo.upsert_topic(
                    name=topic_name,
                    query=topic_name,
                    enabled=False,
                )
                is_new_topic = True
            topic_id = topic.id
    except Exception as exc:
        logger.warning("Auto-create topic '%s' failed: %s", topic_name, exc)

    # 2) 摄入论文
    inserted_ids = pipelines.ingest_arxiv_with_ids(
        query=query, max_results=max_results, topic_id=topic_id
    )
    if not inserted_ids:
        yield ToolResult(
            success=True,
            data={
                "ingested": 0, "query": query, "topic": topic_name,
                "suggest_subscribe": False,
            },
            summary="未发现新论文（可能已全部入库）",
        )
        return

    total = len(inserted_ids)
    yield ToolProgress(
        message=f"找到 {total} 篇论文，开始向量化和粗读...",
        current=0, total=total,
    )

    # 3) 自动向量化 + 粗读
    embed_ok, embed_skip = 0, 0
    skim_ok, skim_skip = 0, 0

    for i, pid_str in enumerate(inserted_ids, 1):
        pid = UUID(pid_str)
        with session_scope() as sess:
            p = PaperRepository(sess).get_by_id(pid)
            p_title = (p.title or "")[:40]
            already_embedded = p.embedding is not None
            already_skimmed = p.read_status.value != "unread"

        yield ToolProgress(
            message=f"处理 {i}/{total}: {p_title}...",
            current=i, total=total,
        )

        if not already_embedded:
            try:
                pipelines.embed_paper(pid)
                embed_ok += 1
            except Exception as exc:
                logger.warning("embed %s failed: %s", pid_str[:8], exc)
        else:
            embed_skip += 1

        if not already_skimmed:
            try:
                pipelines.skim(pid)
                skim_ok += 1
            except Exception as exc:
                logger.warning("skim %s failed: %s", pid_str[:8], exc)
        else:
            skim_skip += 1

    existed = max(embed_skip, skim_skip)
    part2 = (
        f"（新处理 {embed_ok}，已有 {existed}）"
        if existed
        else f"，向量化 {embed_ok}，粗读 {skim_ok}"
    )
    yield ToolResult(
        success=True,
        data={
            "total": total,
            "new_processed": embed_ok,
            "already_existed": existed,
            "query": query,
            "topic": topic_name,
            "embedded": embed_ok,
            "embed_skipped": embed_skip,
            "skimmed": skim_ok,
            "skim_skipped": skim_skip,
            "paper_ids": inserted_ids[:10],
            "suggest_subscribe": is_new_topic,
        },
        summary=(
            f"找到 {total} 篇 → 主题「{topic_name}」{part2}"
        ),
    )


def _manage_subscription(topic_name: str, enabled: bool) -> ToolResult:
    """启用或禁用主题的定时自动搜集"""
    with session_scope() as session:
        topic_repo = TopicRepository(session)
        topic = topic_repo.get_by_name(topic_name.strip())
        if not topic:
            return ToolResult(
                success=False,
                summary=f"主题「{topic_name}」不存在",
            )
        topic.enabled = enabled
        action = "启用定时搜集" if enabled else "关闭定时搜集"
    return ToolResult(
        success=True,
        data={
            "topic": topic_name,
            "enabled": enabled,
        },
        summary=f"已{action}：{topic_name}",
    )


def _skim_paper(paper_id: str) -> ToolResult:
    try:
        pid = UUID(paper_id)
    except ValueError:
        return ToolResult(success=False, summary="无效的 paper_id 格式")
    # 先检查论文是否存在
    with session_scope() as session:
        try:
            paper = PaperRepository(session).get_by_id(pid)
        except ValueError:
            return ToolResult(
                success=False,
                summary=f"论文 {paper_id[:8]}... 不存在",
            )
        if not paper.abstract:
            return ToolResult(
                success=False,
                summary="该论文缺少摘要，无法执行粗读",
            )
    report = PaperPipelines().skim(pid)
    one_liner = report.one_liner
    return ToolResult(
        success=True,
        data=report.model_dump(),
        summary=f"粗读完成: {one_liner[:80]}" + ("..." if len(one_liner) > 80 else ""),
    )


def _deep_read_paper(paper_id: str) -> ToolResult:
    try:
        pid = UUID(paper_id)
    except ValueError:
        return ToolResult(success=False, summary="无效的 paper_id 格式")
    # 先检查论文是否存在和 arxiv_id
    with session_scope() as session:
        try:
            paper = PaperRepository(session).get_by_id(pid)
        except ValueError:
            return ToolResult(
                success=False,
                summary=f"论文 {paper_id[:8]}... 不存在",
            )
        if not paper.arxiv_id and not paper.pdf_path:
            return ToolResult(
                success=False,
                summary="该论文无 arXiv ID 且无 PDF，无法精读",
            )
    report = PaperPipelines().deep_dive(pid)
    return ToolResult(
        success=True,
        data=report.model_dump(),
        summary="精读完成",
    )


def _embed_paper(paper_id: str) -> ToolResult:
    try:
        pid = UUID(paper_id)
    except ValueError:
        return ToolResult(success=False, summary="无效的 paper_id 格式")
    # 先检查论文存在性和内容
    with session_scope() as session:
        try:
            paper = PaperRepository(session).get_by_id(pid)
        except ValueError:
            return ToolResult(
                success=False,
                summary=f"论文 {paper_id[:8]}... 不存在",
            )
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


def _generate_wiki(type: str, keyword_or_id: str) -> ToolResult:
    if type == "topic":
        # 先检查是否有相关论文
        with session_scope() as session:
            papers = PaperRepository(session).full_text_candidates(
                query=keyword_or_id, limit=3
            )
            if not papers:
                return ToolResult(
                    success=False,
                    summary=(
                        f"知识库中没有与 '{keyword_or_id}' "
                        "相关的论文，请先导入"
                    ),
                )
        result = GraphService().topic_wiki(
            keyword=keyword_or_id, limit=120
        )
    elif type == "paper":
        try:
            pid = UUID(keyword_or_id)
        except ValueError:
            return ToolResult(
                success=False,
                summary="无效的 paper_id 格式",
            )
        with session_scope() as session:
            try:
                PaperRepository(session).get_by_id(pid)
            except ValueError:
                return ToolResult(
                    success=False,
                    summary=f"论文 {keyword_or_id[:8]}... 不存在",
                )
        result = GraphService().paper_wiki(paper_id=keyword_or_id)
    else:
        return ToolResult(
            success=False,
            summary=f"无效的 type: {type}，应为 topic 或 paper",
        )
    return ToolResult(
        success=True,
        data=result,
        summary=f"已生成 {type} wiki",
    )


def _generate_daily_brief(recipient: str = "") -> ToolResult:
    from datetime import UTC, datetime

    from packages.integrations.notifier import NotificationService
    from packages.storage.repositories import GeneratedContentRepository

    svc = DailyBriefService()
    # 只调一次 build_html，避免重复生成
    html_content = svc.build_html()
    ts_label = datetime.now(UTC).strftime("%Y-%m-%d")
    ts_file = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    # 保存文件
    notifier = NotificationService()
    saved_path = notifier.save_brief_html(
        f"daily_brief_{ts_file}.html", html_content
    )

    # 发送邮件（可选）
    email_sent = False
    clean_recipient = recipient.strip() if recipient else ""
    if clean_recipient:
        email_sent = notifier.send_email_html(
            clean_recipient, "PaperMind Daily Brief", html_content
        )

    # 持久化到数据库（带重试，避免 database locked）
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

    return ToolResult(
        success=True,
        data={
            "saved_path": saved_path,
            "email_sent": email_sent,
            "html": html_content,
            "title": f"Daily Brief: {ts_label}",
        },
        summary="简报已生成" + ("并发送" if email_sent else ""),
    )
