"""Pipeline / RAG / 任务追踪路由
@author Color2333
"""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from apps.api.deps import rag_service
from packages.domain.exceptions import NotFoundError
from packages.domain.schemas import AskRequest, AskResponse

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------- Pipeline ----------


@router.post("/pipelines/skim/{paper_id}")
def run_skim(paper_id: UUID) -> dict:
    """粗读 — durable 任务化，立即返回 task_id（Executor 执行）"""
    from packages.application.commands.pipelines import start_skim

    return start_skim(paper_id)


@router.post("/pipelines/skim-batch")
def run_skim_batch(body: dict) -> dict:
    """批量粗读 — 单一 durable 任务（Executor 执行，带进度）"""
    from packages.application.commands.pipelines import start_skim_batch

    paper_ids = [str(p) for p in (body.get("paper_ids") or [])]
    if not paper_ids:
        raise HTTPException(status_code=422, detail="paper_ids is required")
    return start_skim_batch(paper_ids)


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
    """在途任务列表（durable store 唯一来源；C3 退出口后不再有内存 tracker）"""
    from packages.application.queries.tasks import list_active_tasks

    return {"tasks": list_active_tasks()}


@router.get("/tasks/{task_id}")
def get_task_status(task_id: str) -> dict:
    """查询任务进度（durable Task id 直接解析；历史行回退 external_ref）"""
    from packages.application.queries.tasks import get_task_info

    status = get_task_info(task_id)
    if not status:
        raise NotFoundError(f"Task {task_id} not found")
    return status


@router.get("/tasks/{task_id}/result")
def get_task_result(task_id: str) -> dict:
    """获取已完成任务的结果摘要（durable store）"""
    from packages.application.queries.tasks import get_task_info
    from packages.application.queries.tasks import get_task_result as app_result

    result = app_result(task_id)
    if result is not None:
        return result
    status = get_task_info(task_id)
    if not status:
        raise NotFoundError(f"Task {task_id} not found")
    if not status.get("finished"):
        raise HTTPException(400, "Task not finished yet")
    return {}
