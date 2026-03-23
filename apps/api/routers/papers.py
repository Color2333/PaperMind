"""论文管理路由
@author Color2333
"""

from pathlib import Path
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from apps.api.deps import cache, paper_list_response, rag_service
from packages.domain.schemas import AIExplainReq
from packages.domain.task_tracker import global_tracker
from packages.storage.db import session_scope
from packages.storage.repositories import PaperRepository

# 全局 HTTP 客户端复用（避免每次请求创建新客户端）
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """获取或创建全局 HTTP 客户端"""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
    return _http_client


router = APIRouter()


@router.get("/papers/folder-stats")
def paper_folder_stats() -> dict:
    """论文文件夹统计（30s 缓存）"""
    cached = cache.get("folder_stats")
    if cached is not None:
        return cached
    with session_scope() as session:
        repo = PaperRepository(session)
        result = repo.folder_stats()
    cache.set("folder_stats", result, ttl=30)
    return result


@router.get("/papers/latest")
def latest(
    limit: int = Query(default=50, ge=1, le=500),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    topic_id: str | None = Query(default=None),
    folder: str | None = Query(default=None),
    date: str | None = Query(default=None),
    search: str | None = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc"),
    category: str | None = Query(default=None),
) -> dict:
    with session_scope() as session:
        repo = PaperRepository(session)
        papers, total = repo.list_paginated(
            page=page,
            page_size=page_size,
            folder=folder,
            topic_id=topic_id,
            status=status,
            date_str=date,
            search=search.strip() if search else None,
            sort_by=sort_by
            if sort_by in ("created_at", "publication_date", "title")
            else "created_at",
            sort_order=sort_order if sort_order in ("asc", "desc") else "desc",
            category=category,
        )
        resp = paper_list_response(papers, repo)
        resp["total"] = total
        resp["page"] = page
        resp["page_size"] = page_size
        resp["total_pages"] = max(1, (total + page_size - 1) // page_size)
        return resp


@router.get("/papers/recommended")
def recommended_papers(top_k: int = Query(default=10, ge=1, le=50)) -> dict:
    from packages.ai.recommendation_service import RecommendationService

    return {"items": RecommendationService().recommend(top_k=top_k)}


@router.post("/papers/search-multi")
async def search_multi(
    query: str,
    channels: list[str] = Query(default=["arxiv"]),
    max_results_per_channel: int = Query(default=50, ge=1, le=100),
    topic_id: str | None = Query(default=None),
) -> dict:
    """多渠道并行搜索论文"""
    import asyncio
    import logging

    from packages.integrations.aggregator import ResultAggregator
    from packages.integrations.registry import ChannelRegistry

    logger = logging.getLogger(__name__)

    ChannelRegistry.register_default_channels()

    async def fetch_channel(ch: str) -> tuple[str, list, dict]:
        try:
            channel = ChannelRegistry.get(ch)
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
                "authors": r.paper.metadata.get("authors", []),
                "year": r.paper.publication_date.year if r.paper.publication_date else None,
                "venue": r.paper.metadata.get("venue"),
                "abstract": r.paper.abstract,
                "sources": r.sources,
            }
            for i, r in enumerate(aggregated)
        ],
        "channel_stats": channel_stats,
    }


@router.get("/papers/suggest-channels")
def suggest_channels(query: str) -> dict:
    """根据关键词推荐合适的渠道"""
    from packages.integrations.registry import ChannelRegistry
    from packages.worker.smart_router import suggest_channels as get_suggestion

    ChannelRegistry.register_default_channels()
    available = ChannelRegistry.list_channels()

    recommended, alternatives, reasoning = get_suggestion(query, available)

    return {
        "recommended": recommended,
        "alternatives": alternatives,
        "reasoning": reasoning,
    }


@router.get("/papers/proxy-arxiv-pdf/{arxiv_id:path}")
async def proxy_arxiv_pdf(arxiv_id: str):
    """代理访问 arXiv PDF（解决 CORS 问题）"""

    # 清理 arxiv_id（移除版本号）
    clean_id = arxiv_id.split("v")[0]
    arxiv_url = f"https://arxiv.org/pdf/{clean_id}.pdf"

    try:
        # 使用后端服务器访问 arXiv（绕过 CORS）
        client = _get_http_client()
        response = await client.get(arxiv_url, follow_redirects=True)

        if response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"arXiv 论文不存在：{clean_id}")

        if response.status_code != 200:
            raise HTTPException(status_code=500, detail=f"arXiv 访问失败：{response.status_code}")

        # 返回 PDF 内容
        from fastapi.responses import Response

        return Response(
            content=response.content,
            media_type="application/pdf",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Content-Disposition": f'inline; filename="{clean_id}.pdf"',
                "Cache-Control": "public, max-age=3600",
            },
        )
    except httpx.TimeoutException as err:
        raise HTTPException(status_code=504, detail="arXiv 请求超时") from err
    except httpx.RequestError as exc:
        raise HTTPException(status_code=500, detail=f"arXiv 访问失败：{str(exc)}") from exc


@router.get("/papers/{paper_id}")
def paper_detail(paper_id: UUID) -> dict:
    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            p = repo.get_by_id(paper_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        topic_map = repo.get_topic_names_for_papers([str(p.id)])
        # 查询已有分析报告
        from sqlalchemy import select as _sel

        from packages.storage.models import AnalysisReport as AR

        ar = session.execute(_sel(AR).where(AR.paper_id == str(p.id))).scalar_one_or_none()
        skim_data = None
        deep_data = None
        if ar:
            if ar.summary_md:
                skim_data = {
                    "summary_md": ar.summary_md,
                    "skim_score": ar.skim_score,
                    "key_insights": ar.key_insights or {},
                }
            if ar.deep_dive_md:
                deep_data = {
                    "deep_dive_md": ar.deep_dive_md,
                    "key_insights": ar.key_insights or {},
                }
        return {
            "id": str(p.id),
            "title": p.title,
            "arxiv_id": p.arxiv_id,
            "abstract": p.abstract,
            "publication_date": str(p.publication_date) if p.publication_date else None,
            "read_status": p.read_status.value,
            "pdf_path": p.pdf_path,
            "favorited": getattr(p, "favorited", False),
            "categories": (p.metadata_json or {}).get("categories", []),
            "authors": (p.metadata_json or {}).get("authors", []),
            "keywords": (p.metadata_json or {}).get("keywords", []),
            "title_zh": (p.metadata_json or {}).get("title_zh", ""),
            "abstract_zh": (p.metadata_json or {}).get("abstract_zh", ""),
            "topics": topic_map.get(str(p.id), []),
            "metadata": p.metadata_json,
            "has_embedding": p.embedding is not None,
            "skim_report": skim_data,
            "deep_report": deep_data,
        }


@router.patch("/papers/{paper_id}/favorite")
def toggle_favorite(paper_id: UUID) -> dict:
    """切换论文收藏状态"""
    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            p = repo.get_by_id(paper_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        current = getattr(p, "favorited", False)
        p.favorited = not current
        session.commit()
        cache.invalidate("folder_stats")
        return {"id": str(p.id), "favorited": p.favorited}


# ---------- PDF 服务 ----------


@router.post("/papers/{paper_id}/download-pdf")
def download_paper_pdf(paper_id: UUID) -> dict:
    """从 arXiv 下载论文 PDF"""
    from packages.integrations.arxiv_client import ArxivClient

    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            paper = repo.get_by_id(paper_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if paper.pdf_path and Path(paper.pdf_path).exists():
            return {"status": "exists", "pdf_path": paper.pdf_path}
        if not paper.arxiv_id or paper.arxiv_id.startswith("ss-"):
            raise HTTPException(status_code=400, detail="该论文没有有效的 arXiv ID，无法下载 PDF")
        try:
            pdf_path = ArxivClient().download_pdf(paper.arxiv_id)
            repo.set_pdf_path(paper_id, pdf_path)
            return {"status": "downloaded", "pdf_path": pdf_path}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"PDF 下载失败: {exc}") from exc


@router.get("/papers/{paper_id}/pdf")
def serve_paper_pdf(paper_id: UUID) -> FileResponse:
    """提供论文 PDF 文件下载/预览"""
    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            paper = repo.get_by_id(paper_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        pdf_path = paper.pdf_path
    if not pdf_path:
        raise HTTPException(status_code=404, detail="论文没有 PDF 文件")
    full_path = Path(pdf_path)
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="PDF 文件不存在")
    return FileResponse(
        path=str(full_path),
        media_type="application/pdf",
        headers={"Access-Control-Allow-Origin": "*"},
    )


@router.post("/papers/{paper_id}/ai/explain")
def ai_explain_text(paper_id: UUID, body: AIExplainReq) -> dict:
    """AI 解释/翻译选中文本"""
    text = body.text.strip()
    action = body.action
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    prompts = {
        "explain": (
            f"你是学术论文解读专家。请用中文简洁解释以下学术文本的含义，"
            f"包括专业术语解释和核心意思。如果是公式，解释公式的含义和各变量。\n\n"
            f"文本：{text[:2000]}"
        ),
        "translate": (
            f"请将以下学术文本翻译为流畅的中文，保留专业术语的英文原文（括号标注）。\n\n"
            f"文本：{text[:2000]}"
        ),
        "summarize": (f"请用中文简要总结以下内容的核心观点（3-5 句话）：\n\n{text[:3000]}"),
    }
    prompt = prompts.get(action, prompts["explain"])

    from packages.integrations.llm_client import LLMClient

    llm = LLMClient()
    result = llm.summarize_text(prompt, stage="rag", max_tokens=1024)
    llm.trace_result(
        result, stage="pdf_reader_ai", prompt_digest=f"{action}:{text[:80]}", paper_id=str(paper_id)
    )
    return {"action": action, "result": result.content}


# ---------- 图表解读 ----------


@router.get("/papers/{paper_id}/figures")
def get_paper_figures(paper_id: UUID) -> dict:
    """获取论文已有的图表解读"""
    from packages.ai.figure_service import FigureService

    items = FigureService.get_paper_analyses(paper_id)
    for item in items:
        if item.get("has_image"):
            item["image_url"] = f"/papers/{paper_id}/figures/{item['id']}/image"
        else:
            item["image_url"] = None
    return {"items": items}


@router.get("/papers/{paper_id}/figures/{figure_id}/image")
def get_figure_image(paper_id: UUID, figure_id: str):
    """返回图表原始图片文件"""
    from sqlalchemy import select

    from packages.storage.db import session_scope
    from packages.storage.models import ImageAnalysis

    with session_scope() as session:
        row = session.execute(
            select(ImageAnalysis).where(
                ImageAnalysis.id == figure_id,
                ImageAnalysis.paper_id == str(paper_id),
            )
        ).scalar_one_or_none()

        if not row or not row.image_path:
            raise HTTPException(status_code=404, detail="图片不存在")

        img_path = Path(row.image_path)
        if not img_path.exists():
            raise HTTPException(status_code=404, detail="图片文件丢失")

        return FileResponse(img_path, media_type="image/png")


@router.post("/papers/{paper_id}/figures/analyze")
def analyze_paper_figures(
    paper_id: UUID,
    max_figures: int = Query(default=10, ge=1, le=30),
) -> dict:
    """提取并解读论文中的图表（异步任务）"""

    # 先验证论文和 PDF
    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            paper = repo.get_by_id(paper_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not paper.pdf_path:
            raise HTTPException(status_code=400, detail="论文没有 PDF 文件")
        pdf_path = paper.pdf_path
        paper_title = paper.title[:50]

    # 提交后台任务
    def _analyze_fn(progress_callback=None):
        from packages.ai.figure_service import FigureService

        if progress_callback:
            progress_callback("正在提取图表...", 10, 100)
        svc = FigureService()
        results = svc.analyze_paper_figures(paper_id, pdf_path, max_figures)

        total_figures = len(results)
        if progress_callback and total_figures > 0:
            progress_callback(f"正在生成解读 ({total_figures} 个图表)...", 50, 100)

        # 分析完成后，从 DB 获取带 id 的完整结果
        from packages.ai.figure_service import FigureService as FS2

        items = FS2.get_paper_analyses(paper_id)
        for i, item in enumerate(items):
            if item.get("has_image"):
                item["image_url"] = f"/papers/{paper_id}/figures/{item['id']}/image"
            else:
                item["image_url"] = None
            if progress_callback:
                progress_callback(
                    f"解读中 ({i + 1}/{total_figures})...",
                    50 + int((i + 1) / total_figures * 45),
                    100,
                )

        if progress_callback:
            progress_callback("图表分析完成", 95, 100)
        return {"paper_id": str(paper_id), "count": len(items), "items": items}

    task_id = global_tracker.submit(
        task_type="figure_analysis",
        title=f"📊 图表分析：{paper_title}",
        fn=_analyze_fn,
        total=max_figures,
    )
    return {
        "task_id": task_id,
        "status": "started",
        "message": "图表分析已启动，正在处理...",
    }


@router.get("/papers/{paper_id}/similar")
def similar(
    paper_id: UUID,
    top_k: int = Query(default=5, ge=1, le=20),
) -> dict:
    ids = rag_service.similar_papers(paper_id, top_k=top_k)
    items = []
    if ids:
        with session_scope() as session:
            repo = PaperRepository(session)
            for pid in ids:
                try:
                    p = repo.get_by_id(pid)
                    items.append(
                        {
                            "id": str(p.id),
                            "title": p.title,
                            "arxiv_id": p.arxiv_id,
                            "read_status": p.read_status.value if p.read_status else "unread",
                        }
                    )
                except Exception:
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


@router.post("/papers/{paper_id}/reasoning")
def paper_reasoning(paper_id: UUID) -> dict:
    """推理链深度分析"""
    from packages.ai.reasoning_service import ReasoningService

    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            repo.get_by_id(paper_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ReasoningService().analyze(paper_id)


# ========== IEEE 渠道专用路由（MVP 阶段新增）==========


@router.post("/papers/ingest/ieee")
def ingest_ieee_papers(
    query: str = Query(..., min_length=1, max_length=500, description="IEEE 搜索关键词"),
    max_results: int = Query(default=20, ge=1, le=100, description="最大结果数"),
    topic_id: str | None = Query(default=None, description="可选的主题 ID"),
) -> dict:
    """
    【MVP】IEEE 论文摄取接口

    注意：
    - 需要 IEEE API Key 配置（.env 中设置 IEEE_API_KEY）
    - 手动触发，不影响现有 ArXiv 流程
    - IEEE PDF 暂不支持下载

    Args:
        query: IEEE 搜索关键词
        max_results: 最大结果数（默认 20）
        topic_id: 可选的主题 ID

    Returns:
        dict: {status, total_fetched, inserted_ids, new_count}

    示例:
    ```bash
    curl -X POST "http://localhost:8002/papers/ingest/ieee?query=deep+learning&max_results=10"
    ```
    """
    import logging

    from packages.ai.pipelines import PaperPipelines
    from packages.domain.enums import ActionType

    logger = logging.getLogger(__name__)
    pipelines = PaperPipelines()

    try:
        total, inserted_ids, new_count = pipelines.ingest_ieee(
            query=query,
            max_results=max_results,
            topic_id=topic_id,
            action_type=ActionType.manual_collect,
        )

        return {
            "status": "success",
            "total_fetched": total,
            "inserted_ids": inserted_ids,
            "new_count": new_count,
            "message": f"✅ IEEE 摄取完成：{new_count} 篇新论文",
        }

    except RuntimeError as exc:
        # IEEE API Key 未配置
        logger.error("IEEE 摄取失败：%s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"IEEE 服务不可用：{str(exc)}。请在 .env 中设置 IEEE_API_KEY 环境变量。",
        ) from exc

    except Exception as exc:
        logger.error("IEEE 摄取失败：%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"IEEE 摄取失败：{str(exc)}",
        ) from exc
