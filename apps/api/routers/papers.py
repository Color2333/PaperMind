"""论文管理路由
@author Color2333
"""

from pathlib import Path
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from apps.api.deps import cache
from packages.application.queries import papers as papers_queries
from packages.domain.exceptions import NotFoundError
from packages.domain.schemas import AIExplainReq
from packages.storage.db import session_scope
from packages.storage.repositories import PaperRepository
from packages.storage.repositories.stats import get_folder_stats

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
        result = get_folder_stats(session)
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
    tag_ids: list[str] | None = Query(default=None),
) -> dict:
    with session_scope() as session:
        return papers_queries.list_papers(
            session,
            page=page,
            page_size=page_size,
            folder=folder,
            topic_id=topic_id,
            status=status,
            date=date,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            category=category,
            tag_ids=tag_ids,
        )


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
    return await papers_queries.search_multi(
        query=query,
        channels=channels,
        max_results_per_channel=max_results_per_channel,
        topic_id=topic_id,
    )


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
        try:
            return papers_queries.get_paper(session, paper_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/papers/{paper_id}/favorite")
def toggle_favorite(paper_id: UUID) -> dict:
    """切换论文收藏状态"""
    from packages.application.commands.papers import toggle_paper_flag
    from packages.domain.exceptions import NotFoundError

    with session_scope() as session:
        try:
            result = toggle_paper_flag(session, paper_id=paper_id, field="favorited")
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    cache.invalidate("folder_stats")
    return result


@router.patch("/papers/{paper_id}/reject")
def toggle_reject(paper_id: UUID) -> dict:
    """切换论文"不感兴趣"状态（推荐系统负反馈）"""
    from packages.ai.recommendation_service import invalidate_recommendations
    from packages.application.commands.papers import toggle_paper_flag
    from packages.domain.exceptions import NotFoundError

    with session_scope() as session:
        try:
            result = toggle_paper_flag(session, paper_id=paper_id, field="rejected")
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    # 失效 folder_stats（左侧文件夹计数）+ 推荐缓存（被拒论文立即从推荐列表移除，
    # 否则 recommend:{top_k} / today_summary 最长 5min 仍含该论文）
    cache.invalidate("folder_stats")
    invalidate_recommendations()
    return result


# ---------- PDF 服务 ----------


@router.post("/papers/{paper_id}/download-pdf")
def download_paper_pdf(paper_id: UUID) -> dict:
    """从 arXiv 下载论文 PDF"""
    from packages.application.commands.papers import download_source
    from packages.domain.exceptions import NotFoundError, ValidationError

    try:
        return download_source(paper_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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


@router.get("/papers/{paper_id}/segments")
def get_paper_segments(paper_id: UUID) -> dict:
    """获取论文分段（用于全文对照翻译）- 包含页码信息"""
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

    try:
        import fitz

        doc = fitz.open(str(full_path))
        paragraphs: list[dict] = []
        para_idx = 0
        max_pages = 30

        for page_num in range(min(max_pages, len(doc))):
            page = doc.load_page(page_num)
            page_text = page.get_text("text").strip()
            if not page_text:
                continue

            blocks = page_text.split("\n\n")
            for block in blocks:
                block = block.strip()
                if len(block) < 20:
                    continue
                para_idx += 1
                paragraphs.append(
                    {
                        "id": f"p-{para_idx}",
                        "type": "paragraph",
                        "content": block[:2000],
                        "pageNumber": page_num + 1,
                    }
                )

        doc.close()
        return {"segments": paragraphs}
    except Exception as e:
        return {"segments": [], "error": str(e)}


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
    from packages.application.commands.papers import start_figure_analysis
    from packages.domain.exceptions import NotFoundError, ValidationError

    try:
        return start_figure_analysis(paper_id, max_figures=max_figures)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/papers/{paper_id}/similar")
def similar(
    paper_id: UUID,
    top_k: int = Query(default=5, ge=1, le=20),
) -> dict:
    with session_scope() as session:
        try:
            return papers_queries.get_similar_papers(session, paper_id, top_k=top_k)
        except NotFoundError as exc:
            # get_by_id 在论文不存在时抛，统一转 404（此前返回 500）
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/papers/{paper_id}/duplicates")
def paper_duplicates(
    paper_id: UUID,
    threshold: float = Query(default=0.92, ge=0.5, le=1.0),
) -> dict:
    """检测与库内论文相似度 > threshold 的疑似重复（同一工作的 arxiv 多版本）"""
    from packages.ai.pipelines import PaperPipelines

    pipelines = PaperPipelines()
    try:
        return pipelines.detect_duplicates(paper_id, threshold=threshold)
    except ValueError as exc:
        # get_by_id 在论文不存在时抛 ValueError，统一转 404（此前返回 500）
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/papers/{paper_id}/reasoning")
def paper_reasoning(paper_id: UUID) -> dict:
    """推理链深度分析"""
    from packages.application.commands.analysis import paper_reasoning_report
    from packages.domain.exceptions import NotFoundError

    try:
        return paper_reasoning_report(paper_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ========== IEEE 渠道专用路由（MVP 阶段新增）==========


@router.post("/papers/ingest/ieee")
def ingest_ieee_papers(
    query: str = Query(..., min_length=1, max_length=500, description="IEEE 搜索关键词"),
    max_results: int = Query(default=20, ge=1, le=100, description="最大结果数"),
    topic_id: str | None = Query(default=None, description="可选的主题 ID"),
) -> dict:
    """
    【MVP】IEEE 论文摄取接口（任务化）

    注意：
    - 需要 IEEE API Key 配置（.env 中设置 IEEE_API_KEY）
    - 手动触发，不影响现有 ArXiv 流程
    - IEEE PDF 暂不支持下载

    Args:
        query: IEEE 搜索关键词
        max_results: 最大结果数（默认 20）
        topic_id: 可选的主题 ID

    Returns:
        dict: {task_id, job_id}——结果经 /tasks/{task_id}/result 轮询

    示例:
    ```bash
    curl -X POST "http://localhost:8002/papers/ingest/ieee?query=deep+learning&max_results=10"
    ```
    """
    import logging

    from packages.application.commands.jobs import submit_job

    logger = logging.getLogger(__name__)

    logger.info(
        "IEEE ingest(task): query=%r max_results=%d topic_id=%s",
        query,
        max_results,
        topic_id,
    )
    # 去重第五刀：同步直写 → 提交 ingest_ieee 任务（manifest A 档，Go 权威调度 +
    # 单事务 apply）；结果经 /tasks/{id}/result 轮询（IEEE_API_KEY 未配置由
    # handler 显式失败，任务观察面可见）
    submitted = submit_job(
        kind="IeeeIngest",
        capability="ingest_ieee",
        title=f"IEEE 摄入: {query[:60]}",
        input_ref={
            "query": query,
            "max_results": max_results,
            "topic_id": topic_id,
            "action_type": "manual_collect",
        },
        idempotency_key=None,
        timeout_s=600,
        created_by="api",
    )
    return {"task_id": submitted["task_id"], "job_id": submitted["job_id"]}
