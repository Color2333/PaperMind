"""Wiki 生成命令（B6；tracker 提交为过渡，C3 收敛为 durable Job）"""

from __future__ import annotations


def start_topic_wiki(*, keyword: str, limit: int = 120) -> str:
    """提交主题 Wiki 后台生成任务，返回 task_id"""
    from packages.application.queries.graph import get_topic_wiki
    from packages.domain.task_tracker import global_tracker

    return global_tracker.submit(
        task_type="topic_wiki",
        title=f"Wiki: {keyword}",
        fn=lambda progress_callback=None: get_topic_wiki(
            keyword=keyword, limit=limit, progress_callback=progress_callback
        ),
    )
