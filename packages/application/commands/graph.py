"""引用图谱命令（B8，设计② StartCitationSync / StartAutoLink / StartDeepTrace）

tracker 提交为过渡（C3 转 durable Job）；facade 单例在本模块持有（lru_cache），
P1-3 后生成类命令（wiki/gaps）也落在本模块——commands 层自足，不回查 queries。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def _graph_service():
    from packages.ai.graph_service import GraphService

    return GraphService()


def start_incremental_citation_sync(
    *, paper_limit: int = 40, edge_limit_per_paper: int = 6
) -> dict[str, Any]:
    from packages.application.queries.graph import _graph_service
    from packages.domain.task_tracker import global_tracker

    def _fn(progress_callback=None):
        if progress_callback:
            progress_callback("正在同步增量引用...", 20, 100)
        result = _graph_service().sync_incremental(
            paper_limit=paper_limit, edge_limit_per_paper=edge_limit_per_paper
        )
        if progress_callback:
            progress_callback("增量引用同步完成", 90, 100)
        return result

    task_id = global_tracker.submit("citation_sync", "📊 增量引用同步", _fn, category="sync")
    return {"task_id": task_id, "message": "增量引用同步已启动", "status": "running"}


def start_topic_citation_sync(
    *, topic_id: str, paper_limit: int = 30, edge_limit_per_paper: int = 6
) -> dict[str, Any]:
    from packages.application.queries.graph import _graph_service
    from packages.domain.task_tracker import global_tracker
    from packages.storage.db import session_scope
    from packages.storage.repositories import TopicRepository

    topic_name = topic_id
    try:
        with session_scope() as session:
            topic = TopicRepository(session).get_by_id(topic_id)
            if topic:
                topic_name = topic.name
    except Exception:
        pass

    def _fn(progress_callback=None):
        if progress_callback:
            progress_callback("正在同步主题引用...", 20, 100)
        result = _graph_service().sync_citations_for_topic(
            topic_id=topic_id, paper_limit=paper_limit, edge_limit_per_paper=edge_limit_per_paper
        )
        if progress_callback:
            progress_callback("主题引用同步完成", 90, 100)
        return result

    task_id = global_tracker.submit(
        "citation_sync", f"📊 主题引用同步：{topic_name}", _fn, category="sync"
    )
    return {"task_id": task_id, "message": f"主题引用同步已启动: {topic_name}", "status": "running"}


def start_paper_citation_sync(*, paper_id: str, limit: int = 8) -> dict[str, Any]:
    from packages.application.queries.graph import _graph_service
    from packages.domain.task_tracker import global_tracker

    def _fn(progress_callback=None):
        if progress_callback:
            progress_callback("正在同步论文引用...", 20, 100)
        result = _graph_service().sync_citations_for_paper(paper_id=paper_id, limit=limit)
        if progress_callback:
            progress_callback("论文引用同步完成", 90, 100)
        return result

    task_id = global_tracker.submit(
        "citation_sync", f"📄 引用同步：{str(paper_id)[:30]}", _fn, category="sync"
    )
    return {"task_id": task_id, "message": "论文引用同步已启动", "status": "running"}


def auto_link_citations(paper_ids: list[str]) -> Any:
    """手动触发引用自动关联（含外部 API 副作用，同步执行）"""
    from packages.application.queries.graph import _graph_service

    return _graph_service().auto_link_citations(paper_ids)


def topic_deep_trace(*, topic_id: str) -> Any:
    """主题深度溯源（含外部 API 副作用，同步执行）"""
    from packages.application.queries.graph import _graph_service

    return _graph_service().topic_deep_trace(topic_id=topic_id)


# ---------- 生成类命令（P1-3 边界修正：LLM 成本 + 写库，不是只读查询）----------


def get_paper_wiki(*, paper_id: str) -> dict:
    """生成论文 Wiki（可能触发 LLM 与 generated_contents 写入）"""
    return _graph_service().paper_wiki(paper_id=paper_id)


def get_topic_wiki(*, keyword: str, limit: int = 120, progress_callback=None) -> dict:
    """生成主题 Wiki（可能触发 LLM）"""
    return _graph_service().topic_wiki(
        keyword=keyword, limit=limit, progress_callback=progress_callback
    )


def detect_research_gaps(*, keyword: str, limit: int = 100) -> dict:
    """研究空白识别（2×timeline + 2×LLM，最重图谱生成）"""
    return _graph_service().detect_research_gaps(keyword=keyword, limit=limit)
