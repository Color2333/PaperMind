"""
PaperMind API - FastAPI 入口
@author Bamzc
"""
import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from packages.ai.agent_service import (
    confirm_action,
    reject_action,
    stream_chat,
)
from packages.ai.brief_service import DailyBriefService
from packages.ai.daily_runner import (
    run_daily_brief,
    run_daily_ingest,
    run_weekly_graph_maintenance,
)
from packages.ai.graph_service import GraphService
from packages.ai.pipelines import PaperPipelines
from packages.ai.rag_service import RAGService
from packages.config import get_settings
from packages.domain.enums import ReadStatus
from packages.domain.schemas import (
    AgentChatRequest,
    AskRequest,
    AskResponse,
    DailyBriefRequest,
    LLMProviderCreate,
    LLMProviderUpdate,
    TopicCreate,
    TopicUpdate,
)
from packages.storage.db import check_db_connection, session_scope
from packages.storage.repositories import (
    GeneratedContentRepository,
    LLMConfigRepository,
    PaperRepository,
    PipelineRunRepository,
    PromptTraceRepository,
    TopicRepository,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _iso(dt: datetime | None) -> str | None:
    """确保返回带时区的 ISO 格式（SQLite 读出来的可能是 naive datetime）"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()

settings = get_settings()
app = FastAPI(title=settings.app_name)
origins = [
    x.strip()
    for x in settings.cors_allow_origins.split(",")
    if x.strip()
]
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins if origins != ["*"] else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

pipelines = PaperPipelines()
rag_service = RAGService()
brief_service = DailyBriefService()
graph_service = GraphService()


def _brief_date() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


# ---------- 系统 ----------


@app.get("/health")
def health() -> dict:
    db_ok = check_db_connection()
    status = "ok" if db_ok else "degraded"
    return {
        "status": status,
        "app": settings.app_name,
        "env": settings.app_env,
        "db": "connected" if db_ok else "unreachable",
    }


@app.get("/system/status")
def system_status() -> dict:
    with session_scope() as session:
        topics = TopicRepository(session).list_topics(enabled_only=False)
        papers = PaperRepository(session).list_latest(limit=200)
        runs = PipelineRunRepository(session).list_latest(limit=50)
        failed = [r for r in runs if r.status.value == "failed"]
        return {
            "health": health(),
            "counts": {
                "topics": len(topics),
                "enabled_topics": len([t for t in topics if t.enabled]),
                "papers_latest_200": len(papers),
                "runs_latest_50": len(runs),
                "failed_runs_latest_50": len(failed),
            },
            "latest_run": (
                {
                    "pipeline_name": runs[0].pipeline_name,
                    "status": runs[0].status.value,
                    "created_at": _iso(runs[0].created_at),
                    "error_message": runs[0].error_message,
                }
                if runs
                else None
            ),
        }


# ---------- 摄入 ----------


@app.post("/ingest/arxiv")
def ingest_arxiv(
    query: str,
    max_results: int = Query(default=20, ge=1, le=200),
    topic_id: str | None = None,
) -> dict:
    logger.info("ArXiv ingest: query=%r max_results=%d", query, max_results)
    count = pipelines.ingest_arxiv(
        query=query, max_results=max_results, topic_id=topic_id
    )
    return {"ingested": count}


# ---------- 主题 ----------


@app.get("/topics")
def list_topics(enabled_only: bool = False) -> dict:
    with session_scope() as session:
        topics = TopicRepository(session).list_topics(
            enabled_only=enabled_only
        )
        return {
            "items": [
                {
                    "id": t.id,
                    "name": t.name,
                    "query": t.query,
                    "enabled": t.enabled,
                    "max_results_per_run": t.max_results_per_run,
                    "retry_limit": t.retry_limit,
                }
                for t in topics
            ]
        }


@app.post("/topics")
def upsert_topic(req: TopicCreate) -> dict:
    with session_scope() as session:
        topic = TopicRepository(session).upsert_topic(
            name=req.name,
            query=req.query,
            enabled=req.enabled,
            max_results_per_run=req.max_results_per_run,
            retry_limit=req.retry_limit,
        )
        return {
            "id": topic.id,
            "name": topic.name,
            "query": topic.query,
            "enabled": topic.enabled,
            "max_results_per_run": topic.max_results_per_run,
            "retry_limit": topic.retry_limit,
        }


@app.patch("/topics/{topic_id}")
def update_topic(topic_id: str, req: TopicUpdate) -> dict:
    with session_scope() as session:
        try:
            topic = TopicRepository(session).update_topic(
                topic_id,
                query=req.query,
                enabled=req.enabled,
                max_results_per_run=req.max_results_per_run,
                retry_limit=req.retry_limit,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=404, detail=str(exc)
            ) from exc
        return {
            "id": topic.id,
            "name": topic.name,
            "query": topic.query,
            "enabled": topic.enabled,
            "max_results_per_run": topic.max_results_per_run,
            "retry_limit": topic.retry_limit,
        }


@app.delete("/topics/{topic_id}")
def delete_topic(topic_id: str) -> dict:
    with session_scope() as session:
        TopicRepository(session).delete_topic(topic_id)
        return {"deleted": topic_id}


# ---------- 引用同步 ----------


@app.post("/citations/sync/{paper_id}")
def sync_citations(
    paper_id: str,
    limit: int = Query(default=8, ge=1, le=50),
) -> dict:
    return graph_service.sync_citations_for_paper(
        paper_id=paper_id, limit=limit
    )


@app.post("/citations/sync/topic/{topic_id}")
def sync_citations_for_topic(
    topic_id: str,
    paper_limit: int = Query(default=30, ge=1, le=200),
    edge_limit_per_paper: int = Query(default=6, ge=1, le=50),
) -> dict:
    try:
        return graph_service.sync_citations_for_topic(
            topic_id=topic_id,
            paper_limit=paper_limit,
            edge_limit_per_paper=edge_limit_per_paper,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/citations/sync/incremental")
def sync_citations_incremental(
    paper_limit: int = Query(default=40, ge=1, le=200),
    edge_limit_per_paper: int = Query(default=6, ge=1, le=50),
) -> dict:
    return graph_service.sync_incremental(
        paper_limit=paper_limit,
        edge_limit_per_paper=edge_limit_per_paper,
    )


# ---------- 图谱 ----------


@app.get("/graph/citation-tree/{paper_id}")
def citation_tree(
    paper_id: str,
    depth: int = Query(default=2, ge=1, le=5),
) -> dict:
    return graph_service.citation_tree(
        root_paper_id=paper_id, depth=depth
    )


@app.get("/graph/timeline")
def graph_timeline(
    keyword: str,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    return graph_service.timeline(keyword=keyword, limit=limit)


@app.get("/graph/quality")
def graph_quality(
    keyword: str,
    limit: int = Query(default=120, ge=1, le=500),
) -> dict:
    return graph_service.quality_metrics(keyword=keyword, limit=limit)


@app.get("/graph/evolution/weekly")
def graph_weekly_evolution(
    keyword: str,
    limit: int = Query(default=160, ge=1, le=500),
) -> dict:
    return graph_service.weekly_evolution(keyword=keyword, limit=limit)


@app.get("/graph/survey")
def graph_survey(
    keyword: str,
    limit: int = Query(default=120, ge=1, le=500),
) -> dict:
    return graph_service.survey(keyword=keyword, limit=limit)


# ---------- Wiki ----------


@app.get("/wiki/paper/{paper_id}")
def wiki_paper(paper_id: str) -> dict:
    result = graph_service.paper_wiki(paper_id=paper_id)
    with session_scope() as session:
        repo = GeneratedContentRepository(session)
        gc = repo.create(
            content_type="paper_wiki",
            title=f"Paper Wiki: {result.get('title', paper_id)}",
            markdown=result.get("markdown", ""),
            paper_id=paper_id,
            metadata_json={
                k: v for k, v in result.items() if k != "markdown"
            },
        )
        result["content_id"] = gc.id
    return result


@app.get("/wiki/topic")
def wiki_topic(
    keyword: str,
    limit: int = Query(default=120, ge=1, le=500),
) -> dict:
    result = graph_service.topic_wiki(keyword=keyword, limit=limit)
    with session_scope() as session:
        repo = GeneratedContentRepository(session)
        gc = repo.create(
            content_type="topic_wiki",
            title=f"Topic Wiki: {keyword}",
            markdown=result.get("markdown", ""),
            keyword=keyword,
            metadata_json={
                k: v for k, v in result.items() if k != "markdown"
            },
        )
        result["content_id"] = gc.id
    return result


# ---------- Pipeline ----------


@app.post("/pipelines/skim/{paper_id}")
def run_skim(paper_id: UUID) -> dict:
    logger.info("Skim pipeline: paper_id=%s", paper_id)
    skim = pipelines.skim(paper_id)
    return skim.model_dump()


@app.post("/pipelines/deep/{paper_id}")
def run_deep(paper_id: UUID) -> dict:
    logger.info("Deep-dive pipeline: paper_id=%s", paper_id)
    deep = pipelines.deep_dive(paper_id)
    return deep.model_dump()


@app.post("/pipelines/embed/{paper_id}")
def run_embed(paper_id: UUID) -> dict:
    pipelines.embed_paper(paper_id)
    return {"status": "embedded", "paper_id": str(paper_id)}


@app.get("/pipelines/runs")
def list_pipeline_runs(
    limit: int = Query(default=30, ge=1, le=200),
) -> dict:
    with session_scope() as session:
        runs = PipelineRunRepository(session).list_latest(limit=limit)
        return {
            "items": [
                {
                    "id": r.id,
                    "pipeline_name": r.pipeline_name,
                    "paper_id": r.paper_id,
                    "status": r.status.value,
                    "decision_note": r.decision_note,
                    "elapsed_ms": r.elapsed_ms,
                    "error_message": r.error_message,
                    "created_at": _iso(r.created_at),
                }
                for r in runs
            ]
        }


# ---------- RAG ----------


@app.post("/rag/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    logger.info("RAG ask: question=%r", req.question[:80])
    return rag_service.ask(req.question, top_k=req.top_k)


@app.get("/papers/{paper_id}/similar")
def similar(
    paper_id: UUID,
    top_k: int = Query(default=5, ge=1, le=20),
) -> dict:
    ids = rag_service.similar_papers(paper_id, top_k=top_k)
    return {
        "paper_id": str(paper_id),
        "similar_ids": [str(x) for x in ids],
    }


# ---------- 论文 ----------


@app.get("/papers/latest")
def latest(
    limit: int = Query(default=20, ge=1, le=500),
    status: str | None = Query(default=None),
    topic_id: str | None = Query(default=None),
) -> dict:
    with session_scope() as session:
        repo = PaperRepository(session)
        if topic_id:
            papers = repo.list_by_topic(topic_id, limit=limit)
        elif status and status in ("unread", "skimmed", "deep_read"):
            papers = repo.list_by_read_status(
                ReadStatus(status), limit=limit
            )
        else:
            papers = repo.list_latest(limit=limit)
        paper_ids = [str(p.id) for p in papers]
        topic_map = repo.get_topic_names_for_papers(paper_ids)
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
                    "categories": (p.metadata_json or {}).get("categories", []),
                    "keywords": (p.metadata_json or {}).get("keywords", []),
                    "title_zh": (p.metadata_json or {}).get("title_zh", ""),
                    "abstract_zh": (p.metadata_json or {}).get("abstract_zh", ""),
                    "topics": topic_map.get(str(p.id), []),
                }
                for p in papers
            ]
        }


@app.get("/papers/{paper_id}")
def paper_detail(paper_id: UUID) -> dict:
    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            p = repo.get_by_id(paper_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=404, detail=str(exc)
            ) from exc
        topic_map = repo.get_topic_names_for_papers([str(p.id)])
        return {
            "id": str(p.id),
            "title": p.title,
            "arxiv_id": p.arxiv_id,
            "abstract": p.abstract,
            "publication_date": str(p.publication_date) if p.publication_date else None,
            "read_status": p.read_status.value,
            "pdf_path": p.pdf_path,
            "categories": (p.metadata_json or {}).get("categories", []),
            "authors": (p.metadata_json or {}).get("authors", []),
            "keywords": (p.metadata_json or {}).get("keywords", []),
            "title_zh": (p.metadata_json or {}).get("title_zh", ""),
            "abstract_zh": (p.metadata_json or {}).get("abstract_zh", ""),
            "topics": topic_map.get(str(p.id), []),
            "metadata": p.metadata_json,
            "has_embedding": p.embedding is not None,
        }


# ---------- 简报 ----------


@app.post("/brief/daily")
def daily_brief(req: DailyBriefRequest) -> dict:
    recipient = req.recipient or settings.notify_default_to
    html_content = brief_service.build_html()
    result = brief_service.publish(recipient=recipient)
    with session_scope() as session:
        repo = GeneratedContentRepository(session)
        ts = _brief_date()
        gc = repo.create(
            content_type="daily_brief",
            title=f"Daily Brief: {ts}",
            markdown=html_content,
            metadata_json={
                "saved_path": result.get("saved_path", ""),
                "email_sent": result.get("email_sent", False),
            },
        )
        result["content_id"] = gc.id
    return result


# ---------- 生成内容历史 ----------


@app.get("/generated/list")
def generated_list(
    type: str = Query(..., description="content_type: topic_wiki|paper_wiki|daily_brief"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    with session_scope() as session:
        repo = GeneratedContentRepository(session)
        items = repo.list_by_type(type, limit=limit)
        return {
            "items": [
                {
                    "id": gc.id,
                    "content_type": gc.content_type,
                    "title": gc.title,
                    "keyword": gc.keyword,
                    "paper_id": gc.paper_id,
                    "created_at": _iso(gc.created_at),
                }
                for gc in items
            ]
        }


@app.get("/generated/{content_id}")
def generated_detail(content_id: str) -> dict:
    with session_scope() as session:
        repo = GeneratedContentRepository(session)
        gc = repo.get_by_id(content_id)
        if gc is None:
            raise HTTPException(status_code=404, detail="Content not found")
        return {
            "id": gc.id,
            "content_type": gc.content_type,
            "title": gc.title,
            "keyword": gc.keyword,
            "paper_id": gc.paper_id,
            "markdown": gc.markdown,
            "metadata_json": gc.metadata_json,
            "created_at": _iso(gc.created_at),
        }


@app.delete("/generated/{content_id}")
def generated_delete(content_id: str) -> dict:
    with session_scope() as session:
        repo = GeneratedContentRepository(session)
        gc = repo.get_by_id(content_id)
        if gc is None:
            raise HTTPException(status_code=404, detail="Content not found")
        repo.delete(content_id)
    return {"deleted": content_id}


# ---------- 定时任务 ----------


@app.post("/jobs/daily/run-once")
def run_daily_once() -> dict:
    logger.info("Manual daily job triggered")
    ingest = run_daily_ingest()
    brief = run_daily_brief()
    return {"ingest": ingest, "brief": brief}


@app.post("/jobs/graph/weekly-run-once")
def run_weekly_graph_once() -> dict:
    logger.info("Manual weekly graph job triggered")
    return run_weekly_graph_maintenance()


# ---------- 指标 ----------


@app.get("/metrics/costs")
def cost_metrics(days: int = Query(default=7, ge=1, le=90)) -> dict:
    with session_scope() as session:
        return PromptTraceRepository(session).summarize_costs(days=days)


# ---------- LLM 配置管理 ----------


def _mask_key(key: str) -> str:
    """API Key 脱敏：只显示前4和后4"""
    if len(key) <= 12:
        return key[:2] + "****" + key[-2:]
    return key[:4] + "****" + key[-4:]


def _cfg_to_out(cfg) -> dict:
    return {
        "id": cfg.id,
        "name": cfg.name,
        "provider": cfg.provider,
        "api_key_masked": _mask_key(cfg.api_key),
        "api_base_url": cfg.api_base_url,
        "model_skim": cfg.model_skim,
        "model_deep": cfg.model_deep,
        "model_vision": cfg.model_vision,
        "model_embedding": cfg.model_embedding,
        "model_fallback": cfg.model_fallback,
        "is_active": cfg.is_active,
    }


@app.get("/settings/llm-providers")
def list_llm_providers() -> dict:
    with session_scope() as session:
        cfgs = LLMConfigRepository(session).list_all()
        return {"items": [_cfg_to_out(c) for c in cfgs]}


@app.get("/settings/llm-providers/active")
def get_active_llm_config() -> dict:
    """获取当前生效的 LLM 配置信息（固定路径，必须在动态路径之前）"""
    with session_scope() as session:
        active = LLMConfigRepository(session).get_active()
        if active:
            return {
                "source": "database",
                "config": _cfg_to_out(active),
            }
    return {
        "source": "env",
        "config": {
            "provider": settings.llm_provider,
            "model_skim": settings.llm_model_skim,
            "model_deep": settings.llm_model_deep,
            "model_vision": getattr(
                settings, "llm_model_vision", None
            ),
            "model_embedding": settings.embedding_model,
            "model_fallback": settings.llm_model_fallback,
            "is_active": True,
        },
    }


@app.post("/settings/llm-providers/deactivate")
def deactivate_llm_providers() -> dict:
    """取消所有配置激活，回退到 .env 默认配置"""
    with session_scope() as session:
        LLMConfigRepository(session).deactivate_all()
        return {
            "status": "ok",
            "message": "All deactivated, using .env defaults",
        }


@app.post("/settings/llm-providers")
def create_llm_provider(req: LLMProviderCreate) -> dict:
    with session_scope() as session:
        cfg = LLMConfigRepository(session).create(
            name=req.name,
            provider=req.provider,
            api_key=req.api_key,
            api_base_url=req.api_base_url,
            model_skim=req.model_skim,
            model_deep=req.model_deep,
            model_vision=req.model_vision,
            model_embedding=req.model_embedding,
            model_fallback=req.model_fallback,
        )
        return _cfg_to_out(cfg)


@app.patch("/settings/llm-providers/{config_id}")
def update_llm_provider(
    config_id: str, req: LLMProviderUpdate
) -> dict:
    with session_scope() as session:
        try:
            cfg = LLMConfigRepository(session).update(
                config_id,
                name=req.name,
                provider=req.provider,
                api_key=req.api_key,
                api_base_url=req.api_base_url,
                model_skim=req.model_skim,
                model_deep=req.model_deep,
                model_vision=req.model_vision,
                model_embedding=req.model_embedding,
                model_fallback=req.model_fallback,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=404, detail=str(exc)
            ) from exc
        return _cfg_to_out(cfg)


@app.delete("/settings/llm-providers/{config_id}")
def delete_llm_provider(config_id: str) -> dict:
    with session_scope() as session:
        LLMConfigRepository(session).delete(config_id)
        return {"deleted": config_id}


@app.post("/settings/llm-providers/{config_id}/activate")
def activate_llm_provider(config_id: str) -> dict:
    with session_scope() as session:
        try:
            cfg = LLMConfigRepository(session).activate(
                config_id
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=404, detail=str(exc)
            ) from exc
        return _cfg_to_out(cfg)


# ---------- Agent ----------


_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-store",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
    "X-Content-Type-Options": "nosniff",
}


@app.post("/agent/chat")
async def agent_chat(req: AgentChatRequest):
    """Agent 对话 - SSE 流式响应"""
    msgs = [m.model_dump() for m in req.messages]
    return StreamingResponse(
        stream_chat(msgs, confirmed_action_id=req.confirmed_action_id),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@app.post("/agent/confirm/{action_id}")
async def agent_confirm(action_id: str):
    """确认执行 Agent 挂起的操作"""
    return StreamingResponse(
        confirm_action(action_id),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@app.post("/agent/reject/{action_id}")
async def agent_reject(action_id: str):
    """拒绝 Agent 挂起的操作"""
    return StreamingResponse(
        reject_action(action_id),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )