"""arXiv 搜索与入库（业务在 application/commands；本文件只桥接进度到工具事件）"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from packages.ai.tools.types import ToolProgress, ToolResult

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

# 任务观察轮询间隔与总等待（import_selected 注册表 timeout_s=3600）
_POLL_INTERVAL_S = 3.0
_POLL_DEADLINE_S = 3600.0


def _search_arxiv(
    query: str,
    max_results: int = 20,
    days_back: int = 0,
    sort_by: str = "relevance",
) -> ToolResult:
    """搜索 arXiv，返回候选论文列表（不入库）

    days_back=0（默认）不限日期，适合按关键词检索经典/全时间段论文。
    想要最新增量时传 days_back=7/30。
    """
    from packages.application.commands.ingest import search_arxiv as app_search_arxiv

    try:
        candidates = app_search_arxiv(
            query=query, max_results=max_results, days_back=days_back, sort_by=sort_by
        )
    except Exception as exc:
        logger.exception("ArXiv search failed: %s", exc)
        return ToolResult(success=False, summary=f"ArXiv 搜索失败: {exc!s}")

    if not candidates:
        return ToolResult(
            success=True,
            data={"candidates": [], "count": 0, "query": query},
            summary="未找到相关论文",
        )

    return ToolResult(
        success=True,
        data={"candidates": candidates, "count": len(candidates), "query": query},
        summary=f"从 arXiv 搜索到 {len(candidates)} 篇候选论文",
    )


def _ingest_arxiv(
    query: str,
    arxiv_ids: list[str] | None = None,
) -> Iterator[ToolProgress | ToolResult]:
    """将用户选定的论文入库（任务语义：提交 import_selected 任务 + 轮询进度）

    入库领域写在权威面单事务 apply（Go applyIngestPapersResult / Python
    domain_apply）；本工具只提交任务并桥接 durable 观察面进度——不再直写。
    """
    from packages.application.commands.jobs import submit_job
    from packages.application.queries.tasks import get_task_info, get_task_result

    if not arxiv_ids:
        yield ToolResult(
            success=False,
            summary="请先用 search_arxiv 搜索，再提供要入库的 arxiv_ids 列表",
        )
        return

    yield ToolProgress(message="正在提交入库任务...", current=0, total=10)

    submitted = submit_job(
        kind="ImportSelected",
        capability="import_selected",
        title=f"Agent 收集: {query[:60]}",
        input_ref={"arxiv_ids": list(arxiv_ids), "query": query},
        idempotency_key=None,
        created_by="agent",
    )
    task_id = submitted["task_id"]

    # 轮询 durable 观察面（与 generate_wiki 同型）
    last_msg = ""
    deadline = time.monotonic() + _POLL_DEADLINE_S
    while time.monotonic() < deadline:
        time.sleep(_POLL_INTERVAL_S)
        status = get_task_info(task_id)
        if not status:
            break
        if status.get("finished"):
            if not status.get("success"):
                yield ToolResult(
                    success=False,
                    summary=f"入库失败: {status.get('error', '未知错误')}",
                )
                return
            break
        msg = status.get("message", "")
        pct = float(status.get("progress") or 0)
        if msg and msg != last_msg:
            yield ToolProgress(message=msg, current=max(1, min(9, int(pct * 10))), total=10)
            last_msg = msg
    else:
        yield ToolResult(
            success=False,
            data={"task_id": task_id},
            summary=f"入库超过 {_POLL_DEADLINE_S:.0f}s 未完成，任务仍在后台收敛（task_id={task_id}）",
        )
        return

    data = get_task_result(task_id) or {}
    total = int(data.get("total") or 0)
    topic_id = data.get("topic_id")
    topic_name = ""
    if topic_id:
        try:
            from packages.storage.db import session_scope
            from packages.storage.repositories import TopicRepository

            with session_scope() as session:
                topic = TopicRepository(session).get_by_id(str(topic_id))
                if topic:
                    topic_name = topic.name
        except Exception:  # noqa: BLE001
            logger.warning("topic 名称查询失败: %s", topic_id)

    if total == 0:
        yield ToolResult(
            success=False,
            data={"task_id": task_id, **data},
            summary="入库 0 篇：选中的 ID 未从 arXiv 返回或已存在于知识库",
        )
        return

    summary = f"入库 {total} 篇" + (f" → 主题「{topic_name}」" if topic_name else "")
    yield ToolProgress(message="入库完成", current=10, total=10)
    yield ToolResult(success=True, data={"task_id": task_id, **data}, summary=summary)
