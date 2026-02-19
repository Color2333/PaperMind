"""
PaperMind API - FastAPI 入口
@author Bamzc
"""
import logging
import time
import uuid as _uuid
from datetime import UTC, datetime
from uuid import UUID

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
from packages.domain.schemas import (
    ReferenceImportReq, SuggestKeywordsReq, AIExplainReq,
    WritingProcessReq, WritingRefineReq, WritingMultimodalReq,
)
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
from packages.ai.task_manager import TaskManager
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


def _get_paper_title(paper_id: UUID) -> str | None:
    """快速获取论文标题"""
    try:
        with session_scope() as session:
            p = PaperRepository(session).get_by_id(paper_id)
            return (p.title or "")[:40]
    except Exception:
        return None


def _iso(dt: datetime | None) -> str | None:
    """确保返回带时区的 ISO 格式（SQLite 读出来的可能是 naive datetime）"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()

api_logger = logging.getLogger("papermind.api")


class RequestLogMiddleware(BaseHTTPMiddleware):
    """记录每个请求的方法、路径、状态码、耗时"""

    async def dispatch(self, request: Request, call_next):
        req_id = _uuid.uuid4().hex[:8]
        request.state.request_id = req_id
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        api_logger.info(
            "[%s] %s %s → %d (%.0fms)",
            req_id, request.method, request.url.path,
            response.status_code, elapsed_ms,
        )
        response.headers["X-Request-Id"] = req_id
        return response


settings = get_settings()
app = FastAPI(title=settings.app_name)
app.add_middleware(RequestLogMiddleware)
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

from packages.storage.db import run_migrations
run_migrations()

pipelines = PaperPipelines()
rag_service = RAGService()
brief_service = DailyBriefService()
graph_service = GraphService()
task_manager = TaskManager()


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
    sort_by: str = Query(default="submittedDate", regex="^(submittedDate|relevance|lastUpdatedDate)$"),
) -> dict:
    logger.info("ArXiv ingest: query=%r max_results=%d sort=%s", query, max_results, sort_by)
    count, inserted_ids = pipelines.ingest_arxiv(
        query=query, max_results=max_results, topic_id=topic_id, sort_by=sort_by,
    )
    # 查询插入论文的基本信息
    papers_info: list[dict] = []
    if inserted_ids:
        with session_scope() as session:
            repo = PaperRepository(session)
            for pid in inserted_ids[:50]:
                try:
                    p = repo.get_by_id(pid)
                    papers_info.append({
                        "id": p.id,
                        "title": p.title,
                        "arxiv_id": p.arxiv_id,
                        "publication_date": p.publication_date.isoformat() if p.publication_date else None,
                    })
                except Exception:
                    pass
    return {"ingested": count, "papers": papers_info}


@app.post("/ingest/references")
def ingest_references(body: ReferenceImportReq) -> dict:
    """一键导入参考文献 — 返回 task_id 用于轮询进度"""
    from packages.ai.pipelines import ReferenceImporter
    importer = ReferenceImporter()
    task_id = importer.start_import(
        source_paper_id=body.source_paper_id,
        source_paper_title=body.source_paper_title,
        entries=[dict(e) for e in body.entries],
        topic_ids=body.topic_ids,
    )
    return {"task_id": task_id, "total": len(body.entries)}


@app.get("/ingest/references/status/{task_id}")
def ingest_references_status(task_id: str) -> dict:
    """查询参考文献导入任务进度"""
    from packages.ai.pipelines import get_import_task
    task = get_import_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task


# ---------- 主题 ----------


def _topic_dict(t, session=None) -> dict:
    d = {
        "id": t.id,
        "name": t.name,
        "query": t.query,
        "enabled": t.enabled,
        "max_results_per_run": t.max_results_per_run,
        "retry_limit": t.retry_limit,
        "schedule_frequency": getattr(t, "schedule_frequency", "daily"),
        "schedule_time_utc": getattr(t, "schedule_time_utc", 21),
        "paper_count": 0,
        "last_run_at": None,
        "last_run_count": None,
    }
    if session is not None:
        from sqlalchemy import func, select
        from packages.storage.models import PaperTopic, CollectionAction
        # 论文计数
        cnt = session.scalar(
            select(func.count()).select_from(PaperTopic)
            .where(PaperTopic.topic_id == t.id)
        )
        d["paper_count"] = cnt or 0
        # 最近一次行动
        last_action = session.execute(
            select(CollectionAction)
            .where(CollectionAction.topic_id == t.id)
            .order_by(CollectionAction.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if last_action:
            d["last_run_at"] = last_action.created_at.isoformat() if last_action.created_at else None
            d["last_run_count"] = last_action.paper_count
    return d


@app.get("/topics")
def list_topics(enabled_only: bool = False) -> dict:
    with session_scope() as session:
        topics = TopicRepository(session).list_topics(
            enabled_only=enabled_only
        )
        return {"items": [_topic_dict(t, session) for t in topics]}


@app.post("/topics")
def upsert_topic(req: TopicCreate) -> dict:
    with session_scope() as session:
        topic = TopicRepository(session).upsert_topic(
            name=req.name,
            query=req.query,
            enabled=req.enabled,
            max_results_per_run=req.max_results_per_run,
            retry_limit=req.retry_limit,
            schedule_frequency=req.schedule_frequency,
            schedule_time_utc=req.schedule_time_utc,
        )
        return _topic_dict(topic, session)


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
                schedule_frequency=req.schedule_frequency,
                schedule_time_utc=req.schedule_time_utc,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=404, detail=str(exc)
            ) from exc
        return _topic_dict(topic, session)


@app.delete("/topics/{topic_id}")
def delete_topic(topic_id: str) -> dict:
    with session_scope() as session:
        TopicRepository(session).delete_topic(topic_id)
        return {"deleted": topic_id}


_fetch_tasks: dict[str, dict] = {}

@app.post("/topics/{topic_id}/fetch")
def manual_fetch_topic(topic_id: str) -> dict:
    """手动触发单个订阅的论文抓取（后台执行，立即返回）"""
    import threading
    from packages.ai.daily_runner import run_topic_ingest
    from packages.storage.models import TopicSubscription
    with session_scope() as session:
        topic = session.get(TopicSubscription, topic_id)
        if not topic:
            raise HTTPException(status_code=404, detail="订阅不存在")
        topic_name = topic.name

    if _fetch_tasks.get(topic_id, {}).get("running"):
        return {"status": "already_running", "topic_name": topic_name, "inserted": 0, "processed": 0}

    def _run():
        from packages.domain.task_tracker import global_tracker
        tid = f"fetch_{topic_id[:8]}"
        global_tracker.start(tid, "fetch", f"抓取: {topic_name[:30]}")
        _fetch_tasks[topic_id] = {"running": True}
        try:
            result = run_topic_ingest(topic_id)
            _fetch_tasks[topic_id] = {"running": False, **result}
            global_tracker.finish(tid, success=True)
        except Exception as exc:
            _fetch_tasks[topic_id] = {"running": False, "status": "failed", "error": str(exc)}
            global_tracker.finish(tid, success=False, error=str(exc)[:100])

    threading.Thread(target=_run, daemon=True).start()

    return {
        "status": "started",
        "topic_id": topic_id,
        "topic_name": topic_name,
        "inserted": 0,
        "processed": 0,
        "message": f"「{topic_name}」抓取已在后台启动",
    }


@app.get("/topics/{topic_id}/fetch-status")
def fetch_topic_status(topic_id: str) -> dict:
    """查询手动抓取的执行状态"""
    task = _fetch_tasks.get(topic_id)
    if not task:
        return {"status": "idle"}
    if task.get("running"):
        return {"status": "running"}
    with session_scope() as session:
        from packages.storage.models import TopicSubscription
        topic = session.get(TopicSubscription, topic_id)
        topic_info = _topic_dict(topic, session) if topic else {}
    return {**task, "topic": topic_info}


@app.post("/topics/suggest-keywords")
def suggest_keywords(req: SuggestKeywordsReq) -> dict:
    from packages.ai.keyword_service import KeywordService
    description = req.description
    if not description.strip():
        raise HTTPException(400, "description is required")
    suggestions = KeywordService().suggest(description.strip())
    return {"suggestions": suggestions}


# ---------- 引用同步 ----------
# 注意：固定路径必须在 {paper_id} 动态路径之前，否则会被错误匹配


@app.post("/citations/sync/incremental")
def sync_citations_incremental(
    paper_limit: int = Query(default=40, ge=1, le=200),
    edge_limit_per_paper: int = Query(default=6, ge=1, le=50),
) -> dict:
    return graph_service.sync_incremental(
        paper_limit=paper_limit,
        edge_limit_per_paper=edge_limit_per_paper,
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


@app.post("/citations/sync/{paper_id}")
def sync_citations(
    paper_id: str,
    limit: int = Query(default=8, ge=1, le=50),
) -> dict:
    return graph_service.sync_citations_for_paper(
        paper_id=paper_id, limit=limit
    )


# ---------- 图谱 ----------


@app.get("/graph/similarity-map")
def similarity_map(
    topic_id: str | None = None,
    limit: int = Query(default=200, ge=5, le=500),
) -> dict:
    """论文相似度 2D 散点图（UMAP 降维）"""
    return graph_service.similarity_map(topic_id=topic_id, limit=limit)


@app.get("/graph/citation-tree/{paper_id}")
def citation_tree(
    paper_id: str,
    depth: int = Query(default=2, ge=1, le=5),
) -> dict:
    return graph_service.citation_tree(
        root_paper_id=paper_id, depth=depth
    )


@app.get("/graph/citation-detail/{paper_id}")
def citation_detail(paper_id: str) -> dict:
    """获取单篇论文的丰富引用详情（含参考文献和被引列表）"""
    return graph_service.citation_detail(paper_id=paper_id)


@app.get("/graph/citation-network/topic/{topic_id}")
def topic_citation_network(topic_id: str) -> dict:
    """获取主题内论文的互引网络"""
    return graph_service.topic_citation_network(topic_id=topic_id)


@app.post("/graph/citation-network/topic/{topic_id}/deep-trace")
def topic_deep_trace(topic_id: str) -> dict:
    """对主题内论文执行深度溯源，拉取外部引用并进行共引分析"""
    return graph_service.topic_deep_trace(topic_id=topic_id)


@app.get("/graph/overview")
def graph_overview() -> dict:
    """全库引用概览 — 节点 + 边 + PageRank + 统计"""
    return graph_service.library_overview()


@app.get("/graph/bridges")
def graph_bridges() -> dict:
    """跨主题桥接论文"""
    return graph_service.cross_topic_bridges()


@app.get("/graph/frontier")
def graph_frontier(
    days: int = Query(default=90, ge=7, le=365),
) -> dict:
    """研究前沿检测"""
    return graph_service.research_frontier(days=days)


@app.get("/graph/cocitation-clusters")
def graph_cocitation_clusters(
    min_cocite: int = Query(default=2, ge=1, le=10),
) -> dict:
    """共引聚类分析"""
    return graph_service.cocitation_clusters(min_cocite=min_cocite)


@app.post("/graph/auto-link")
def graph_auto_link(paper_ids: list[str]) -> dict:
    """手动触发引用自动关联"""
    return graph_service.auto_link_citations(paper_ids)


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


@app.get("/graph/research-gaps")
def graph_research_gaps(
    keyword: str,
    limit: int = Query(default=120, ge=1, le=500),
) -> dict:
    return graph_service.detect_research_gaps(keyword=keyword, limit=limit)


@app.post("/papers/{paper_id}/reasoning")
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


# ---------- 异步任务 API ----------


def _run_topic_wiki_task(
    keyword: str,
    limit: int,
    progress_callback=None,
) -> dict:
    """后台执行 topic wiki 生成"""
    result = graph_service.topic_wiki(
        keyword=keyword, limit=limit,
        progress_callback=progress_callback,
    )
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


@app.post("/tasks/wiki/topic")
def start_topic_wiki_task(
    keyword: str,
    limit: int = Query(default=120, ge=1, le=500),
) -> dict:
    """提交后台 wiki 生成任务"""
    task_id = task_manager.submit(
        task_type="topic_wiki",
        title=f"Wiki: {keyword}",
        fn=_run_topic_wiki_task,
        keyword=keyword,
        limit=limit,
    )
    return {"task_id": task_id, "status": "pending"}


@app.get("/tasks/active")
def get_active_tasks() -> dict:
    """获取全局进行中的任务列表（跨页面可见）"""
    from packages.domain.task_tracker import global_tracker
    return {"tasks": global_tracker.get_active()}


@app.post("/tasks/track")
def track_task(body: dict) -> dict:
    """前端通知后端创建/更新/完成一个全局可见任务"""
    from packages.domain.task_tracker import global_tracker
    action = body.get("action", "start")
    task_id = body.get("task_id", "")
    if action == "start":
        global_tracker.start(
            task_id=task_id,
            task_type=body.get("task_type", "batch"),
            title=body.get("title", ""),
            total=body.get("total", 0),
        )
    elif action == "update":
        global_tracker.update(
            task_id=task_id,
            current=body.get("current", 0),
            message=body.get("message", ""),
            total=body.get("total"),
        )
    elif action == "finish":
        global_tracker.finish(
            task_id=task_id,
            success=body.get("success", True),
            error=body.get("error"),
        )
    return {"ok": True}


@app.get("/tasks/{task_id}")
def get_task_status(task_id: str) -> dict:
    """查询任务进度"""
    status = task_manager.get_status(task_id)
    if not status:
        raise HTTPException(404, f"Task {task_id} not found")
    return status


@app.get("/tasks/{task_id}/result")
def get_task_result(task_id: str) -> dict:
    """获取已完成任务的结果"""
    status = task_manager.get_status(task_id)
    if not status:
        raise HTTPException(404, f"Task {task_id} not found")
    if status["status"] != "completed":
        raise HTTPException(400, f"Task not completed: {status['status']}")
    result = task_manager.get_result(task_id)
    return result or {}


@app.get("/tasks")
def list_tasks(
    task_type: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    """列出任务"""
    return {"tasks": task_manager.list_tasks(task_type=task_type, limit=limit)}


# ---------- Pipeline ----------


@app.post("/pipelines/skim/{paper_id}")
def run_skim(paper_id: UUID) -> dict:
    from packages.domain.task_tracker import global_tracker
    tid = f"skim_{paper_id.hex[:8]}"
    title = _get_paper_title(paper_id) or str(paper_id)[:8]
    global_tracker.start(tid, "skim", f"粗读: {title[:30]}", total=1)
    try:
        skim = pipelines.skim(paper_id)
        global_tracker.finish(tid, success=True)
        return skim.model_dump()
    except Exception as exc:
        global_tracker.finish(tid, success=False, error=str(exc)[:100])
        raise


@app.post("/pipelines/deep/{paper_id}")
def run_deep(paper_id: UUID) -> dict:
    from packages.domain.task_tracker import global_tracker
    tid = f"deep_{paper_id.hex[:8]}"
    title = _get_paper_title(paper_id) or str(paper_id)[:8]
    global_tracker.start(tid, "deep_read", f"精读: {title[:30]}", total=1)
    try:
        deep = pipelines.deep_dive(paper_id)
        global_tracker.finish(tid, success=True)
        return deep.model_dump()
    except Exception as exc:
        global_tracker.finish(tid, success=False, error=str(exc)[:100])
        raise


@app.post("/pipelines/embed/{paper_id}")
def run_embed(paper_id: UUID) -> dict:
    from packages.domain.task_tracker import global_tracker
    tid = f"embed_{paper_id.hex[:8]}"
    title = _get_paper_title(paper_id) or str(paper_id)[:8]
    global_tracker.start(tid, "embed", f"嵌入: {title[:30]}", total=1)
    try:
        pipelines.embed_paper(paper_id)
        global_tracker.finish(tid, success=True)
        return {"status": "embedded", "paper_id": str(paper_id)}
    except Exception as exc:
        global_tracker.finish(tid, success=False, error=str(exc)[:100])
        raise


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


@app.post("/rag/ask-iterative")
def ask_iterative(
    req: AskRequest,
    max_rounds: int = Query(default=3, ge=1, le=5),
) -> dict:
    """多轮迭代 RAG"""
    logger.info("RAG iterative ask: question=%r max_rounds=%d", req.question[:80], max_rounds)
    resp = rag_service.ask_iterative(
        question=req.question,
        max_rounds=max_rounds,
        initial_top_k=req.top_k,
    )
    return resp.model_dump(mode="json")


@app.get("/papers/{paper_id}/similar")
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
                    items.append({
                        "id": str(p.id),
                        "title": p.title,
                        "arxiv_id": p.arxiv_id,
                        "read_status": p.read_status.value if p.read_status else "unread",
                    })
                except Exception:
                    items.append({"id": str(pid), "title": str(pid), "arxiv_id": None, "read_status": "unread"})
    return {
        "paper_id": str(paper_id),
        "similar_ids": [str(x) for x in ids],
        "items": items,
    }


# ---------- 论文 ----------


@app.get("/papers/folder-stats")
def paper_folder_stats() -> dict:
    """论文文件夹统计"""
    with session_scope() as session:
        repo = PaperRepository(session)
        return repo.folder_stats()


def _paper_list_response(papers: list, repo: "PaperRepository") -> dict:
    """论文列表统一序列化"""
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
                "favorited": getattr(p, "favorited", False),
                "categories": (p.metadata_json or {}).get("categories", []),
                "keywords": (p.metadata_json or {}).get("keywords", []),
                "title_zh": (p.metadata_json or {}).get("title_zh", ""),
                "abstract_zh": (p.metadata_json or {}).get("abstract_zh", ""),
                "topics": topic_map.get(str(p.id), []),
            }
            for p in papers
        ]
    }


@app.get("/papers/latest")
def latest(
    limit: int = Query(default=50, ge=1, le=500),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    topic_id: str | None = Query(default=None),
    folder: str | None = Query(default=None),
    date: str | None = Query(default=None),
    search: str | None = Query(default=None),
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
        )
        resp = _paper_list_response(papers, repo)
        resp["total"] = total
        resp["page"] = page
        resp["page_size"] = page_size
        resp["total_pages"] = max(1, (total + page_size - 1) // page_size)
        return resp


@app.get("/papers/recommended")
def recommended_papers(top_k: int = Query(default=10, ge=1, le=50)) -> dict:
    from packages.ai.recommendation_service import RecommendationService
    return {"items": RecommendationService().recommend(top_k=top_k)}


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
        # 查询已有分析报告
        from packages.storage.models import AnalysisReport as AR
        from sqlalchemy import select as _sel
        ar = session.execute(
            _sel(AR).where(AR.paper_id == str(p.id))
        ).scalar_one_or_none()
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


@app.patch("/papers/{paper_id}/favorite")
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
        return {"id": str(p.id), "favorited": p.favorited}


# ---------- PDF 服务 ----------


@app.post("/papers/{paper_id}/download-pdf")
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


@app.get("/papers/{paper_id}/pdf")
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


@app.post("/papers/{paper_id}/ai/explain")
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
        "summarize": (
            f"请用中文简要总结以下内容的核心观点（3-5 句话）：\n\n{text[:3000]}"
        ),
    }
    prompt = prompts.get(action, prompts["explain"])

    from packages.integrations.llm_client import LLMClient
    llm = LLMClient()
    result = llm.summarize_text(prompt, stage="rag", max_tokens=1024)
    llm.trace_result(result, stage="pdf_reader_ai", prompt_digest=f"{action}:{text[:80]}", paper_id=str(paper_id))
    return {"action": action, "result": result.content}


# ---------- 图表解读 ----------


@app.get("/papers/{paper_id}/figures")
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


@app.get("/papers/{paper_id}/figures/{figure_id}/image")
def get_figure_image(paper_id: UUID, figure_id: str):
    """返回图表原始图片文件"""
    from packages.storage.db import session_scope
    from packages.storage.models import ImageAnalysis
    from sqlalchemy import select

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


@app.post("/papers/{paper_id}/figures/analyze")
def analyze_paper_figures(
    paper_id: UUID,
    max_figures: int = Query(default=10, ge=1, le=30),
) -> dict:
    """提取并解读论文中的图表"""
    from packages.ai.figure_service import FigureService
    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            paper = repo.get_by_id(paper_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not paper.pdf_path:
            raise HTTPException(status_code=400, detail="论文没有 PDF 文件")
        pdf_path = paper.pdf_path  # 在 session 内取出
    svc = FigureService()
    try:
        results = svc.analyze_paper_figures(paper_id, pdf_path, max_figures)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"图表解读失败: {exc}") from exc
    # 分析完成后，从 DB 获取带 id 的完整结果（含 image_url）
    from packages.ai.figure_service import FigureService as FS2
    items = FS2.get_paper_analyses(paper_id)
    for item in items:
        if item.get("has_image"):
            item["image_url"] = f"/papers/{paper_id}/figures/{item['id']}/image"
        else:
            item["image_url"] = None
    return {
        "paper_id": str(paper_id),
        "count": len(items),
        "items": items,
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
        try:
            gc = repo.get_by_id(content_id)
        except ValueError:
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
        try:
            repo.get_by_id(content_id)
        except ValueError:
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


@app.post("/jobs/batch-process-unread")
def batch_process_unread(
    max_papers: int = Query(default=50, ge=1, le=200),
) -> dict:
    """一键对未读论文执行 embed + skim（并行）"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from packages.ai.daily_runner import _process_paper, PAPER_CONCURRENCY

    with session_scope() as session:
        repo = PaperRepository(session)
        unread = repo.list_by_read_status(ReadStatus.unread, limit=max_papers)
        # 过滤掉已经有 embedding 且已粗读的
        target_ids = []
        for p in unread:
            needs_embed = p.embedding is None
            needs_skim = p.read_status == ReadStatus.unread
            if needs_embed or needs_skim:
                target_ids.append(p.id)

    if not target_ids:
        return {"processed": 0, "total_unread": 0, "message": "没有需要处理的未读论文"}

    processed = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=PAPER_CONCURRENCY) as pool:
        futs = {pool.submit(_process_paper, pid): pid for pid in target_ids}
        for fut in as_completed(futs):
            try:
                fut.result()
                processed += 1
            except Exception as exc:
                failed += 1
                pid = futs[fut]
                logger.warning("batch process %s failed: %s", str(pid)[:8], exc)

    return {
        "processed": processed,
        "failed": failed,
        "total": len(target_ids),
        "message": f"处理完成：{processed} 成功，{failed} 失败",
    }


# ---------- 行动记录 ----------


@app.get("/actions")
def list_actions(
    action_type: str | None = None,
    topic_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """列出论文入库行动记录"""
    from packages.storage.repositories import ActionRepository
    with session_scope() as session:
        repo = ActionRepository(session)
        actions, total = repo.list_actions(
            action_type=action_type, topic_id=topic_id,
            limit=limit, offset=offset,
        )
        return {
            "items": [
                {
                    "id": a.id,
                    "action_type": a.action_type,
                    "title": a.title,
                    "query": a.query,
                    "topic_id": a.topic_id,
                    "paper_count": a.paper_count,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in actions
            ],
            "total": total,
        }


@app.get("/actions/{action_id}")
def get_action_detail(action_id: str) -> dict:
    """获取行动详情"""
    from packages.storage.repositories import ActionRepository
    with session_scope() as session:
        repo = ActionRepository(session)
        action = repo.get_action(action_id)
        if not action:
            raise HTTPException(status_code=404, detail="行动记录不存在")
        return {
            "id": action.id,
            "action_type": action.action_type,
            "title": action.title,
            "query": action.query,
            "topic_id": action.topic_id,
            "paper_count": action.paper_count,
            "created_at": action.created_at.isoformat() if action.created_at else None,
        }


@app.get("/actions/{action_id}/papers")
def get_action_papers(
    action_id: str,
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    """获取某次行动关联的论文列表"""
    from packages.storage.repositories import ActionRepository
    with session_scope() as session:
        repo = ActionRepository(session)
        papers = repo.get_papers_by_action(action_id, limit=limit)
        return {
            "action_id": action_id,
            "items": [
                {
                    "id": p.id,
                    "title": p.title,
                    "arxiv_id": p.arxiv_id,
                    "publication_date": p.publication_date.isoformat() if p.publication_date else None,
                    "read_status": p.read_status,
                }
                for p in papers
            ],
        }


# ---------- 推荐 & 趋势 ----------


@app.get("/trends/hot")
def hot_keywords(
    days: int = Query(default=7, ge=1, le=30),
    top_k: int = Query(default=15, ge=1, le=50),
) -> dict:
    from packages.ai.recommendation_service import TrendService
    items = TrendService().detect_hot_keywords(days=days, top_k=top_k)
    return {"items": items}


@app.get("/trends/emerging")
def emerging_trends(days: int = Query(default=14, ge=7, le=60)) -> dict:
    from packages.ai.recommendation_service import TrendService
    return TrendService().detect_trends(days=days)


@app.get("/today")
def today_summary() -> dict:
    from packages.ai.recommendation_service import TrendService
    return TrendService().get_today_summary()


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
    from packages.integrations.llm_client import invalidate_llm_config_cache
    with session_scope() as session:
        LLMConfigRepository(session).deactivate_all()
        invalidate_llm_config_cache()
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
    from packages.integrations.llm_client import invalidate_llm_config_cache
    with session_scope() as session:
        try:
            cfg = LLMConfigRepository(session).activate(
                config_id
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=404, detail=str(exc)
            ) from exc
        invalidate_llm_config_cache()
        return _cfg_to_out(cfg)


# ---------- 写作助手 ----------


@app.get("/writing/templates")
def writing_templates() -> dict:
    """获取所有写作模板列表"""
    from packages.ai.writing_service import WritingService
    return {"items": WritingService.list_templates()}


@app.post("/writing/process")
def writing_process(body: WritingProcessReq) -> dict:
    """执行写作操作"""
    from packages.ai.writing_service import WritingService
    action = body.action
    text = body.content.strip() or body.topic.strip()
    if not action:
        raise HTTPException(status_code=400, detail="action is required")
    if not text:
        raise HTTPException(status_code=400, detail="text/content is required")
    try:
        return WritingService().process(action, text)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/writing/refine")
def writing_refine(body: WritingRefineReq) -> dict:
    """基于对话历史多轮微调"""
    from packages.ai.writing_service import WritingService
    messages = body.messages
    if not messages:
        raise HTTPException(status_code=400, detail="messages is required")
    try:
        return WritingService().refine(messages)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/writing/process-multimodal")
def writing_process_multimodal(body: WritingMultimodalReq) -> dict:
    """多模态写作操作（图片 + 文本）"""
    from packages.ai.writing_service import WritingService
    if not body.image_base64:
        raise HTTPException(status_code=400, detail="image_base64 is required")
    try:
        return WritingService().process_with_image(
            action=body.action,
            text=body.content.strip(),
            image_base64=body.image_base64,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


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