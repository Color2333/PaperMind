"""PaperMind MCP server —— 挂载到现有 FastAPI，供 hermes agent 接入。

Streamable HTTP transport（MCP 2025-06-18 规范），Bearer 静态 token 鉴权。
暴露论文查询 / 每日简报 / 论文推荐 / 触发处理任务四类工具，复用现有 service 单例。

@author Color2333
"""

from __future__ import annotations

import os

from fastmcp import FastMCP

# 独立静态 token（hermes 常驻用，免续期）。未配置时 MCP 端点不启用鉴权（仅开发用）。
_MCP_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")

if _MCP_TOKEN:
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    _verifier = StaticTokenVerifier(
        tokens={
            _MCP_TOKEN: {
                "client_id": "hermes-agent",
                "sub": "hermes",
                "scopes": ["read", "write"],
            }
        },
        required_scopes=["read"],
    )
    mcp = FastMCP("papermind-mcp", auth=_verifier)
else:
    # 未配 token：开发模式不鉴权（生产必须配 MCP_AUTH_TOKEN）
    mcp = FastMCP("papermind-mcp")


# ---------- 工具实现（复用项目 service/repo，不重写业务逻辑）----------


def _to_text(content: str | dict) -> str:
    """把内容转成适合 MCP tool 返回的 JSON 文本（hermes 用文本即可）。"""
    import json

    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


@mcp.tool
def search_papers(query: str = "", limit: int = 10, topic_id: str = "") -> dict:
    """在 PaperMind 论文库中检索论文。

    Args:
        query: 自由文本检索词（匹配标题/摘要/arxiv_id），空则按时间倒序。
        limit: 最多返回条数，默认 10，上限 50。
        topic_id: 可选，按主题过滤。
    """
    from apps.api.deps import paper_list_response
    from packages.storage.db import session_scope
    from packages.storage.repositories import PaperRepository

    limit = max(1, min(limit, 50))
    with session_scope() as session:
        repo = PaperRepository(session)
        papers, total = repo.list_paginated(
            page=1, page_size=limit, search=query or None, topic_id=topic_id or None
        )
        resp = paper_list_response(papers, repo)
    resp["total"] = total
    return resp


@mcp.tool
def get_paper(paper_id: str) -> dict:
    """获取单篇论文详情（含 skim 摘要/精读内容/主题/标签）。

    Args:
        paper_id: 论文 UUID。
    """
    from uuid import UUID

    from sqlalchemy import select

    from packages.storage.db import session_scope
    from packages.storage.models import AnalysisReport
    from packages.storage.repositories import PaperRepository

    try:
        pid = UUID(paper_id)
    except ValueError as e:
        return {"error": f"无效的 paper_id: {e}"}

    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            p = repo.get_by_id(pid)
        except ValueError:
            return {"error": "论文不存在"}
        report = session.execute(
            select(AnalysisReport).where(AnalysisReport.paper_id == pid)
        ).scalar_one_or_none()
        topics = repo.get_topic_names_for_papers([str(pid)]).get(str(pid), [])
        tags = repo.get_tags_for_papers([str(pid)]).get(str(pid), [])
        return {
            "id": str(p.id),
            "title": p.title,
            "arxiv_id": p.arxiv_id,
            "abstract": p.abstract,
            "read_status": p.read_status.value,
            "publication_date": str(p.publication_date) if p.publication_date else None,
            "topics": topics,
            "tags": tags,
            "title_zh": (p.metadata_json or {}).get("title_zh", ""),
            "abstract_zh": (p.metadata_json or {}).get("abstract_zh", ""),
            "skim_summary": report.summary_md if report else None,
            "skim_score": report.skim_score if report else None,
            "deep_dive": report.deep_dive_md if report else None,
        }


@mcp.tool
def get_daily_brief(limit: int = 30) -> str:
    """生成并返回今日研究简报（纯文本摘要版，含高分论文/推荐/趋势）。

    Args:
        limit: 简报论文数量，默认 30。
    """
    from apps.api.deps import brief_service

    html = brief_service.build_html(limit=limit)
    # 从 HTML 提取纯文本摘要（去标签），hermes 用文本更友好
    import re

    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    # 截断避免过长（MCP tool 输出有上限）
    return text[:8000] if len(text) > 8000 else text


@mcp.tool
def recommend_papers(top_k: int = 10) -> dict:
    """基于已读论文 embedding 的个性化推荐。

    Args:
        top_k: 返回数量，默认 10，上限 30。
    """
    from packages.ai.recommendation_service import RecommendationService

    top_k = max(1, min(top_k, 30))
    recs = RecommendationService().recommend(top_k=top_k)
    return {"count": len(recs), "items": recs}


@mcp.tool
def find_similar(paper_id: str, top_k: int = 5) -> dict:
    """查找与指定论文相似的其他论文（基于 embedding 余弦相似度）。

    Args:
        paper_id: 种子论文 UUID。
        top_k: 返回数量，默认 5，上限 20。
    """
    from uuid import UUID

    from apps.api.deps import rag_service

    try:
        pid = UUID(paper_id)
    except ValueError as e:
        return {"error": f"无效的 paper_id: {e}"}

    top_k = max(1, min(top_k, 20))
    similar_ids = rag_service.similar_papers(pid, top_k=top_k)
    if not similar_ids:
        return {"count": 0, "items": [], "note": "无相似论文或种子论文无 embedding"}

    from packages.storage.db import session_scope
    from packages.storage.repositories import PaperRepository

    with session_scope() as session:
        repo = PaperRepository(session)
        papers = repo.list_by_ids([str(i) for i in similar_ids])
        return {
            "count": len(papers),
            "seed_paper_id": paper_id,
            "items": [{"id": str(p.id), "title": p.title, "arxiv_id": p.arxiv_id} for p in papers],
        }


@mcp.tool
def trigger_skim(paper_id: str) -> dict:
    """触发单篇论文粗读（skim），返回 skim 结果（一句话/创新点/分数）。

    Args:
        paper_id: 论文 UUID。
    """
    from uuid import UUID

    from apps.api.deps import pipelines

    try:
        pid = UUID(paper_id)
    except ValueError as e:
        return {"error": f"无效的 paper_id: {e}"}

    try:
        result = pipelines.skim(pid)
        return {
            "paper_id": paper_id,
            "success": True,
            "one_liner": result.one_liner,
            "innovations": result.innovations,
            "keywords": result.keywords,
            "title_zh": result.title_zh,
            "abstract_zh": result.abstract_zh,
            "relevance_score": result.relevance_score,
        }
    except Exception as e:
        return {"paper_id": paper_id, "success": False, "error": str(e)}


@mcp.tool
def trigger_embed(paper_id: str) -> dict:
    """触发单篇论文嵌入（重新计算 embedding 并落库）。

    Args:
        paper_id: 论文 UUID。
    """
    from uuid import UUID

    from apps.api.deps import pipelines

    try:
        pid = UUID(paper_id)
    except ValueError as e:
        return {"error": f"无效的 paper_id: {e}"}

    try:
        pipelines.embed_paper(pid)
        return {"paper_id": paper_id, "success": True, "note": "嵌入完成"}
    except Exception as e:
        return {"paper_id": paper_id, "success": False, "error": str(e)}


@mcp.tool
def trigger_daily_job() -> dict:
    """触发每日抓取+简报任务（异步，立即返回 task_id，用 get_task_status 查进度）。

    返回的 task_id 可用 get_task_status 工具轮询状态。
    """
    from packages.ai.daily_runner import run_daily_brief, run_daily_ingest
    from packages.domain.task_tracker import global_tracker

    def _run_daily(progress_callback=None):
        ingest = run_daily_ingest()
        brief = run_daily_brief()
        return {"ingest": ingest, "brief": brief}

    task_id = global_tracker.submit(
        task_type="mcp_daily",
        title="MCP 触发的每日抓取+简报",
        fn=_run_daily,
        total=2,
        category="mcp",
    )
    return {"task_id": task_id, "status": "started", "message": "用 get_task_status 查进度"}


@mcp.tool
def get_task_status(task_id: str) -> dict:
    """查询异步任务状态（trigger_daily_job 返回的 task_id）。

    Args:
        task_id: 任务 ID。
    """
    from packages.domain.task_tracker import global_tracker

    info = global_tracker.get_task(task_id)
    if not info:
        return {"error": "任务不存在或已过期"}
    result = global_tracker.get_result(task_id)
    return {
        "task_id": task_id,
        "status": info.status if hasattr(info, "status") else str(info.get("status")),
        "progress": info.progress if hasattr(info, "progress") else info.get("progress"),
        "message": info.message if hasattr(info, "message") else info.get("message"),
        "result": result,
    }


def get_mcp_asgi_app():
    """返回可挂载到 FastAPI 的 ASGI 子 app（端点挂到 /mcp 后为 /mcp/）。"""
    return mcp.http_app(path="/")
