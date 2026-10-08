"""论文导入命令（B6；设计② ImportPaper）

直写路径已退役（proposal 模式去重收尾）：入库领域写在权威面单事务 apply
（Go applyIngestPapersResult / Python domain_apply），网络抓取作为纯计算留在
task_handlers 的 proposal handler；调用方（API/agent 工具）提交 durable 任务
并经任务观察面轮询。本模块保留搜索命令与已退役包装。
"""

from __future__ import annotations

import logging
from uuid import UUID

logger = logging.getLogger(__name__)


def search_arxiv(
    *, query: str, max_results: int = 20, days_back: int = 0, sort_by: str = "relevance"
) -> list[dict]:
    """搜索 arXiv 候选（不入库）；返回候选 canonical 列表"""
    from packages.integrations.arxiv_client import ArxivClient

    papers = ArxivClient().fetch_latest(
        query=query, max_results=max_results, sort_by=sort_by, days_back=days_back
    )
    return [
        {
            # REVIEW P2：候选的序号字段是既有协议的一部分（旧 CLI/UI 按序号展示），保留
            "index": i,
            "arxiv_id": p.arxiv_id,
            "title": p.title,
            "abstract": (p.abstract or "")[:300],
            "publication_date": str(p.publication_date) if p.publication_date else None,
            "categories": (p.metadata or {}).get("categories", []),
            "authors": (p.metadata or {}).get("authors", [])[:5],
        }
        for i, p in enumerate(papers, 1)
    ]


def import_ieee(*, query: str, max_results: int = 20, topic_id: str | None = None) -> dict:
    """[已退役直写路径] 兼容保留：转调 ingest_ieee proposal handler（纯计算 +
    只读去重，领域写在权威面 apply）。需要 IEEE_API_KEY；未配置抛 RuntimeError。"""
    from packages.ai.task_handlers import ingest_ieee_proposal

    return ingest_ieee_proposal(
        query=query,
        max_results=max_results,
        topic_id=topic_id,
        action_type="manual_collect",
    )


def describe_ingested_papers(inserted_ids: list[str], *, limit: int = 50) -> list[dict]:
    """入库后返回论文基本信息（/ingest/arxiv 响应形状）"""
    from packages.storage.db import session_scope
    from packages.storage.repositories import PaperRepository

    papers_info: list[dict] = []
    with session_scope() as session:
        repo = PaperRepository(session)
        for pid in inserted_ids[:limit]:
            try:
                p = repo.get_by_id(UUID(pid))
                papers_info.append(
                    {
                        "id": p.id,
                        "title": p.title,
                        "arxiv_id": p.arxiv_id,
                        "publication_date": p.publication_date.isoformat()
                        if p.publication_date
                        else None,
                    }
                )
            except Exception:
                pass
    return papers_info
