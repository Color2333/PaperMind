"""Pipeline / RAG / 任务追踪路由
@author Color2333
"""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from apps.api.deps import rag_service
from packages.domain.exceptions import NotFoundError
from packages.domain.schemas import AskRequest, AskResponse
from packages.domain.task_tracker import global_tracker

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------- Pipeline ----------


@router.post("/pipelines/skim/{paper_id}")
def run_skim(paper_id: UUID) -> dict:
    """粗读 — 后台任务化，立即返回 task_id（此前同步阻塞 5-30s 占请求线程）"""
    from packages.application.commands.pipelines import start_skim

    return start_skim(paper_id)


@router.post("/pipelines/deep/{paper_id}")
def run_deep(paper_id: UUID) -> dict:
    """精读 — 后台任务化，立即返回 task_id（此前同步阻塞 30s-2min 占请求线程）"""
    from packages.application.commands.pipelines import start_deep_read

    return start_deep_read(paper_id)


@router.post("/pipelines/embed/{paper_id}")
def run_embed(paper_id: UUID) -> dict:
    """嵌入 — 后台任务化，立即返回 task_id（此前同步阻塞 0.5-3s 占请求线程）"""
    from packages.application.commands.pipelines import start_embed

    return start_embed(paper_id)


@router.get("/pipelines/runs")
def list_pipeline_runs(
    limit: int = Query(default=30, ge=1, le=200),
) -> dict:
    from packages.application.queries.tasks import list_pipeline_runs as app_list_runs

    return app_list_runs(limit=limit)


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
    """获取全局进行中的任务列表（tracker + durable 在途合并；C10 并入 Jobs）"""
    from packages.application.queries.tasks import (
        list_active_tasks,
        list_durable_active_tasks,
    )
    from packages.storage.db import session_scope

    with session_scope() as session:
        durable = list_durable_active_tasks(session)
    merged = {t["task_id"]: t for t in list_active_tasks()}
    for t in durable:
        merged.setdefault(t["task_id"], t)
    return {"tasks": list(merged.values())}


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
    """查询任务进度（durability 优先，tracker 兜底；C10 并入 Jobs）"""
    from packages.application.queries.tasks import get_task_info, resolve_task_unified
    from packages.storage.db import session_scope

    with session_scope() as session:
        durable = resolve_task_unified(session, task_id)
    if durable is not None:
        return durable
    status = get_task_info(task_id)
    if not status:
        raise NotFoundError(f"Task {task_id} not found")
    return status


@router.get("/tasks/{task_id}/result")
def get_task_result(task_id: str) -> dict:
    """获取已完成任务的结果（durability 优先，tracker 兜底）"""
    from packages.application.queries.tasks import (
        get_task_info,
        get_task_result_by_ref,
    )
    from packages.application.queries.tasks import (
        get_task_result as app_result,
    )
    from packages.storage.db import session_scope

    with session_scope() as session:
        durable_result = get_task_result_by_ref(session, task_id)
    if durable_result is not None:
        return durable_result
    status = get_task_info(task_id)
    if not status:
        raise NotFoundError(f"Task {task_id} not found")
    if not status.get("finished"):
        raise HTTPException(400, "Task not finished yet")
    return app_result(task_id) or {}
