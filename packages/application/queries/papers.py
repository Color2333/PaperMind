"""论文只读查询（B2，设计②批次一：SearchPapers/GetPaper/ListPapers/GetSimilarPapers）

从 apps/api/routers/papers.py 原样下沉；HTTP 响应逐字段兼容（含 404 detail 形状，
由 router 把 NotFoundError 转回 HTTPException）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from packages.domain.exceptions import NotFoundError
from packages.storage.models import AnalysisReport
from packages.storage.repositories import PaperRepository

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_SORT_FIELDS = ("created_at", "publication_date", "title")


def _serialize_papers(papers: list, repo: PaperRepository) -> dict:
    """论文列表统一序列化（自 deps.paper_list_response 下沉，逐字段一致）"""
    paper_ids = [str(p.id) for p in papers]
    topic_map = repo.get_topic_names_for_papers(paper_ids)
    tag_map = repo.get_tags_for_papers(paper_ids)
    return {
        "items": [
            {
                "id": str(p.id),
                "title": p.title,
                "arxiv_id": p.arxiv_id,
                "abstract": p.abstract,
                "publication_date": str(p.publication_date) if p.publication_date else None,
                "read_status": p.read_status.value,
                "pdf_path": p.pdf_path,
                "has_embedding": p.embedding is not None,
                "favorited": getattr(p, "favorited", False),
                "categories": (p.metadata_json or {}).get("categories", []),
                "keywords": (p.metadata_json or {}).get("keywords", []),
                "title_zh": (p.metadata_json or {}).get("title_zh", ""),
                "abstract_zh": (p.metadata_json or {}).get("abstract_zh", ""),
                "topics": topic_map.get(str(p.id), []),
                "tags": tag_map.get(str(p.id), []),
            }
            for p in papers
        ]
    }


def list_papers(
    session: Session,
    *,
    page: int,
    page_size: int,
    folder: str | None = None,
    topic_id: str | None = None,
    status: str | None = None,
    date: str | None = None,
    search: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    category: str | None = None,
    tag_ids: list[str] | None = None,
) -> dict:
    repo = PaperRepository(session)
    papers, total = repo.list_paginated(
        page=page,
        page_size=page_size,
        folder=folder,
        topic_id=topic_id,
        status=status,
        date_str=date,
        search=search.strip() if search else None,
        sort_by=sort_by if sort_by in _SORT_FIELDS else "created_at",
        sort_order=sort_order if sort_order in ("asc", "desc") else "desc",
        category=category,
        tag_ids=tag_ids,
    )
    resp = _serialize_papers(papers, repo)
    resp["total"] = total
    resp["page"] = page
    resp["page_size"] = page_size
    resp["total_pages"] = max(1, (total + page_size - 1) // page_size)
    return resp


def get_paper(session: Session, paper_id: UUID | str) -> dict:
    repo = PaperRepository(session)
    try:
        paper = repo.get_by_id(paper_id)
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc
    topic_map = repo.get_topic_names_for_papers([str(paper.id)])
    tag_map = repo.get_tags_for_papers([str(paper.id)])
    report = session.execute(
        select(AnalysisReport).where(AnalysisReport.paper_id == str(paper.id))
    ).scalar_one_or_none()
    skim_data = None
    deep_data = None
    if report:
        if report.summary_md:
            skim_data = {
                "summary_md": report.summary_md,
                "skim_score": report.skim_score,
                "key_insights": report.key_insights or {},
            }
        if report.deep_dive_md:
            deep_data = {
                "deep_dive_md": report.deep_dive_md,
                "key_insights": report.key_insights or {},
            }
    return {
        "id": str(paper.id),
        "title": paper.title,
        "arxiv_id": paper.arxiv_id,
        "abstract": paper.abstract,
        "publication_date": str(paper.publication_date) if paper.publication_date else None,
        "read_status": paper.read_status.value,
        "pdf_path": paper.pdf_path,
        "favorited": getattr(paper, "favorited", False),
        "rejected": getattr(paper, "rejected", False),
        "categories": (paper.metadata_json or {}).get("categories", []),
        "authors": (paper.metadata_json or {}).get("authors", []),
        "keywords": (paper.metadata_json or {}).get("keywords", []),
        "title_zh": (paper.metadata_json or {}).get("title_zh", ""),
        "abstract_zh": (paper.metadata_json or {}).get("abstract_zh", ""),
        "topics": topic_map.get(str(paper.id), []),
        "tags": tag_map.get(str(paper.id), []),
        "metadata": paper.metadata_json,
        "has_embedding": paper.embedding is not None,
        "skim_report": skim_data,
        "deep_report": deep_data,
    }


async def search_multi(
    *,
    query: str,
    channels: list[str],
    max_results_per_channel: int = 50,
    topic_id: str | None = None,
) -> dict:
    """多渠道并行搜索（外部渠道聚合，无 DB 依赖；渠道注册表可注入 fake 便于测试）"""
    import asyncio

    from packages.config import get_settings
    from packages.integrations.aggregator import ResultAggregator
    from packages.integrations.registry import ChannelRegistry

    ChannelRegistry.register_default_channels()
    settings = get_settings()

    async def fetch_channel(ch: str) -> tuple[str, list, dict]:
        try:
            # Semantic Scholar 的 api_key 需从 Settings 注入（客户端仅 env 兜底）
            kwargs: dict = {}
            if ch == "semantic_scholar":
                kwargs["api_key"] = settings.semantic_scholar_api_key
            channel = ChannelRegistry.get(ch, **kwargs)
            if not channel:
                return ch, [], {"error": "channel not found"}
            papers = await asyncio.to_thread(channel.fetch, query, max_results_per_channel)
            return ch, papers, {"total": len(papers)}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Channel %s failed: %s", ch, exc)
            return ch, [], {"error": str(exc)}

    tasks = [fetch_channel(ch) for ch in channels]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    aggregator = ResultAggregator()
    channel_stats: dict[str, dict[str, int | str]] = {}

    for result in results:
        if isinstance(result, Exception):
            logger.error("Channel task failed: %s", result)
            continue
        ch, papers, meta = result
        channel_stats[ch] = {"total": 0, "new": 0, "duplicates": 0}
        if "error" in meta:
            channel_stats[ch]["error"] = meta["error"]
        else:
            channel_stats[ch]["total"] = meta.get("total", 0)
            aggregator.add_results(ch, papers, meta)

    aggregated = aggregator.get_sorted_results()

    return {
        "papers": [
            {
                "id": f"temp-{i}",
                "title": r.paper.title,
                "authors": (r.paper.metadata_json or {}).get("authors", []),
                "year": r.paper.publication_date.year if r.paper.publication_date else None,
                "venue": (r.paper.metadata_json or {}).get("venue"),
                "abstract": r.paper.abstract,
                "sources": r.sources,
            }
            for i, r in enumerate(aggregated)
        ],
        "channel_stats": channel_stats,
    }


def get_similar_papers(session: Session, paper_id: UUID | str, *, top_k: int = 5) -> dict:
    """embedding 相似论文（复用领域服务 RAGService；论文不存在 → NotFoundError）"""
    from packages.ai.rag_service import RAGService

    try:
        ids = RAGService().similar_papers(paper_id, top_k=top_k)
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc
    items = []
    if ids:
        repo = PaperRepository(session)
        by_id = {str(p.id): p for p in repo.list_by_ids([str(i) for i in ids])}
        for pid in ids:
            paper = by_id.get(str(pid))
            if paper is not None:
                items.append(
                    {
                        "id": str(paper.id),
                        "title": paper.title,
                        "arxiv_id": paper.arxiv_id,
                        "read_status": paper.read_status.value if paper.read_status else "unread",
                    }
                )
            else:
                items.append(
                    {
                        "id": str(pid),
                        "title": str(pid),
                        "arxiv_id": None,
                        "read_status": "unread",
                    }
                )
    return {
        "paper_id": str(paper_id),
        "similar_ids": [str(x) for x in ids],
        "items": items,
    }


__all__ = ["get_paper", "get_similar_papers", "list_papers", "search_multi"]
