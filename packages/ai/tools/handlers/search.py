"""搜索 / 论文详情 / 知识库 / 引用树 / 时间线 / 筛选 / 关键词建议。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from packages.ai.graph_service import GraphService
from packages.ai.rag_service import RAGService
from packages.ai.tools.base import _require_paper
from packages.ai.tools.types import ToolProgress, ToolResult
from packages.storage.db import session_scope
from packages.storage.repositories import PaperRepository

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)


def _search_papers(keyword: str, limit: int = 20) -> ToolResult:
    try:
        with session_scope() as session:
            papers = PaperRepository(session).full_text_candidates(query=keyword, limit=limit)
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
    except Exception as exc:
        logger.exception("search_papers failed: %s", exc)
        return ToolResult(success=False, summary=f"搜索论文失败: {exc!s}")


def _get_paper_detail(paper_id: str) -> ToolResult:
    p, err = _require_paper(paper_id)
    if err:
        return err
    # p 已是 _require_paper 解析出的完整论文对象（detached 但属性已加载）。
    # 不再用 UUID(paper_id) 重新查——短前缀会崩，且重复查询无意义。
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
    # 用 paper.id（完整 UUID），不用原始短前缀调 UUID()
    pid = UUID(paper.id)
    if not paper.embedding:
        return ToolResult(
            success=False,
            summary="该论文未向量化，请先调用 embed_paper",
        )
    try:
        ids = RAGService().similar_papers(pid, top_k=top_k)
        items = []
        with session_scope() as session:
            repo = PaperRepository(session)
            for sid in ids:
                try:
                    sp = repo.get_by_id(sid)
                    items.append(
                        {
                            "id": str(sp.id),
                            "title": sp.title,
                            "arxiv_id": sp.arxiv_id,
                            "read_status": sp.read_status.value,
                        }
                    )
                except Exception:
                    items.append({"id": str(sid), "title": "未知论文"})
        titles = ", ".join(it["title"][:30] for it in items[:3])
        return ToolResult(
            success=True,
            data={
                "paper_id": paper.id,
                "similar_ids": [str(x) for x in ids],
                "items": items,
            },
            summary=f"找到 {len(ids)} 篇相似论文: {titles}{'...' if len(ids) > 3 else ''}",
        )
    except Exception as exc:
        logger.exception("get_similar_papers failed: %s", exc)
        return ToolResult(success=False, summary=f"查找相似论文失败: {exc!s}")


def _ask_knowledge_base(
    question: str,
    top_k: int = 5,
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
    paper, err = _require_paper(paper_id)
    if err:
        return err
    try:
        # 用完整 UUID（paper.id），不用原始短前缀（citation_tree 内部用 paper.id 作 dict key）
        result = GraphService().citation_tree(root_paper_id=paper.id, depth=depth)
        node_count = len(result.get("nodes", []))
        edge_count = len(result.get("edges", []))
        return ToolResult(
            success=True,
            data=result,
            summary=f"引用树含 {node_count} 个节点、{edge_count} 条边",
        )
    except Exception as exc:
        logger.exception("get_citation_tree failed: %s", exc)
        return ToolResult(success=False, summary=f"引用树获取失败: {exc!s}")


def _get_timeline(keyword: str, limit: int = 100) -> ToolResult:
    try:
        result = GraphService().timeline(keyword=keyword, limit=limit)
        tl = result.get("timeline", [])
        years = sorted({p.get("year") for p in tl if p.get("year")})
        year_range = (
            f"{years[0]}-{years[-1]}" if len(years) >= 2 else (str(years[0]) if years else "无")
        )
        return ToolResult(
            success=True,
            data=result,
            summary=f"时间线: {len(tl)} 篇论文，覆盖 {year_range}",
        )
    except Exception as exc:
        logger.exception("get_timeline failed: %s", exc)
        return ToolResult(success=False, summary=f"时间线获取失败: {exc!s}")


def _suggest_keywords(description: str) -> ToolResult:
    """AI 生成 arXiv 搜索关键词建议"""
    from packages.ai.keyword_service import KeywordService

    try:
        suggestions = KeywordService().suggest(description.strip())
    except Exception as exc:
        logger.exception("Keyword suggestion failed: %s", exc)
        return ToolResult(success=False, summary=f"关键词建议生成失败: {exc!s}")
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


def _list_papers_by_filter(
    start_date: str | None = None,
    end_date: str | None = None,
    date_field: str = "created_at",
    status: str | None = None,
    topic_id: str | None = None,
    tag_ids: list[str] | None = None,
    search: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    limit: int = 100,
) -> ToolResult:
    try:
        with session_scope() as session:
            papers, total = PaperRepository(session).list_paginated(
                page=1,
                page_size=limit,
                start_date=start_date,
                end_date=end_date,
                date_field=date_field,
                status=status,
                topic_id=topic_id,
                tag_ids=tag_ids,
                search=search,
                sort_by=sort_by,
                sort_order=sort_order,
            )
        items = [
            {
                "paper_id": str(p.id),
                "title": p.title,
                "created_at": p.created_at.isoformat(),
                "publication_date": p.publication_date.isoformat() if p.publication_date else None,
                "read_status": p.read_status.value,
            }
            for p in papers
        ]
        return ToolResult(
            success=True,
            data={"items": items, "total": total},
            summary=f"找到 {total} 篇（返回前 {len(items)} 篇）",
        )
    except Exception as exc:
        logger.exception("list_papers_by_filter failed: %s", exc)
        return ToolResult(success=False, summary=f"筛选论文失败: {exc!s}")
