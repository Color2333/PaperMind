"""arXiv 搜索与入库（业务在 application/commands/ingest.py；本文件只桥接进度到工具事件）"""

from __future__ import annotations

import logging
import queue
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from packages.ai.tools.types import ToolProgress, ToolResult

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

# REVIEW P2：有界执行器替代裸 daemon 线程（同批最多 1 个 agent 入库任务，
# 防止并发放大写库与 PDF 下载）；C3 起由 durable Job 取代。
_INGEST_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-ingest")
# 单次 events.get 的等待上限；入库长流程靠 progress 事件持续喂入即不会触发
EVENT_TIMEOUT_S = 300


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
    """将用户选定的论文入库 → 自动分配主题 → 自动向量化 → 自动粗读

    业务在 application/commands/ingest.import_selected_papers（含 tracker 与
    PDF 后台池）；此处把 progress 回调桥接为 ToolProgress 流。
    """
    from packages.application.commands.ingest import import_selected_papers

    if not arxiv_ids:
        yield ToolResult(
            success=False,
            summary="请先用 search_arxiv 搜索，再提供要入库的 arxiv_ids 列表",
        )
        return

    yield ToolProgress(message="正在准备入库...", current=0, total=0)

    events: queue.Queue = queue.Queue()
    # REVIEW P2：有界线程池（见模块头）替代裸 daemon 线程；入库一旦开始会完成到
    # 幂等终态，客户端断连只是停止进度流，不会造成半写状态。

    def _progress(msg: str, cur: int, tot: int) -> None:
        events.put(("p", (msg, cur, tot)))

    def _run():
        try:
            events.put(
                (
                    "done",
                    import_selected_papers(query=query, arxiv_ids=arxiv_ids, progress=_progress),
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("ingest_arxiv failed: %s", exc)
            events.put(("error", exc))

    future = _INGEST_POOL.submit(_run)

    while True:
        try:
            kind, payload = events.get(timeout=EVENT_TIMEOUT_S)
        except queue.Empty:
            if future.done():
                continue  # 结果恰好入队前超时——下一轮取到
            # 长时间无进度且未完成：视为执行载体异常，终止等待（任务本身幂等可重入）
            yield ToolResult(
                success=False,
                summary=f"入库超过 {EVENT_TIMEOUT_S}s 无进度，已停止等待（任务仍在后台收敛）",
            )
            return
        if kind == "p":
            msg, cur, tot = payload
            yield ToolProgress(message=msg, current=cur, total=tot)
        elif kind == "done":
            data = payload
            if data.get("status") == "failed" or data["total"] == 0:
                # REVIEW P1-2：完全失败不得报告为成功
                if data["failed"]:
                    summary = (
                        f"入库 0 篇（{len(data['failed'])} 篇失败: "
                        f"{data['failed'][0].get('error', '')[:80]}）"
                    )
                else:
                    summary = "入库 0 篇：" + data.get("note", "选中的 ID 未从 arXiv 返回")
                yield ToolResult(success=False, data=data, summary=summary)
                return
            summary = (
                f"入库 {data['total']} 篇 → 主题「{data['topic']}」，"
                f"向量化 {data['embedded']}，粗读 {data['skimmed']}"
                + (f"，{len(data['failed'])} 篇失败已跳过" if data["failed"] else "")
            )
            yield ToolResult(success=True, data=data, summary=summary)
            return
        else:
            yield ToolResult(success=False, summary=f"入库失败: {payload}")
            return
