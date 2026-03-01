"""Pipeline / RAG / 任务追踪路由
@author Color2333
"""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from apps.api.deps import get_paper_title, iso_dt, pipelines, rag_service
from packages.domain.exceptions import NotFoundError
from packages.domain.schemas import AskRequest, AskResponse
from packages.domain.task_tracker import global_tracker
from packages.storage.db import session_scope
from packages.storage.repositories import PipelineRunRepository

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------- Pipeline ----------


@router.post("/pipelines/skim/{paper_id}")
def run_skim(paper_id: UUID) -> dict:

    tid = f"skim_{paper_id.hex[:8]}"
    title = get_paper_title(paper_id) or str(paper_id)[:8]
    global_tracker.start(tid, "skim", f"粗读: {title[:30]}", total=1)
    try:
        skim = pipelines.skim(paper_id)
        global_tracker.finish(tid, success=True)
        return skim.model_dump()
    except Exception as exc:
        global_tracker.finish(tid, success=False, error=str(exc)[:100])
        raise


@router.post("/pipelines/deep/{paper_id}")
def run_deep(paper_id: UUID) -> dict:

    tid = f"deep_{paper_id.hex[:8]}"
    title = get_paper_title(paper_id) or str(paper_id)[:8]
    global_tracker.start(tid, "deep_read", f"精读: {title[:30]}", total=1)
    try:
        deep = pipelines.deep_dive(paper_id)
        global_tracker.finish(tid, success=True)
        return deep.model_dump()
    except Exception as exc:
        global_tracker.finish(tid, success=False, error=str(exc)[:100])
        raise


@router.post("/pipelines/embed/{paper_id}")
def run_embed(paper_id: UUID) -> dict:

    tid = f"embed_{paper_id.hex[:8]}"
    title = get_paper_title(paper_id) or str(paper_id)[:8]
    global_tracker.start(tid, "embed", f"嵌入: {title[:30]}", total=1)
    try:
        pipelines.embed_paper(paper_id)
        global_tracker.finish(tid, success=True)
        return {"status": "embedded", "paper_id": str(paper_id)}
    except Exception as exc:
        global_tracker.finish(tid, success=False, error=str(exc)[:100])
        raise


@router.get("/pipelines/runs")
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
                    "created_at": iso_dt(r.created_at),
                }
                for r in runs
            ]
        }


# ---------- RAG ----------


@router.post("/rag/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    logger.info("RAG ask: question=%r", req.question[:80])
    return rag_service.ask(req.question, top_k=req.top_k)


@router.post("/rag/ask-iterative")
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


# ---------- 任务追踪 ----------


@router.get("/tasks/active")
def get_active_tasks() -> dict:
    """获取全局进行中的任务列表（跨页面可见）"""

    return {"tasks": global_tracker.get_active()}


@router.post("/tasks/track")
def track_task(body: dict) -> dict:
    """前端通知后端创建/更新/完成一个全局可见任务"""

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


@router.get("/tasks/{task_id}")
def get_task_status(task_id: str) -> dict:
    """查询任务进度"""
    status = global_tracker.get_task(task_id)
    if not status:
        raise NotFoundError(f"Task {task_id} not found")
    return status


@router.get("/tasks/{task_id}/result")
def get_task_result(task_id: str) -> dict:
    """获取已完成任务的结果"""
    status = global_tracker.get_task(task_id)
    if not status:
        raise NotFoundError(f"Task {task_id} not found")
    if not status.get("finished"):
        raise HTTPException(400, f"Task not finished yet")
    result = global_tracker.get_result(task_id)
    return result or {}
