"""Wiki 生成命令（B6；tracker 提交为过渡，C3 收敛为 durable Job）"""

from __future__ import annotations


def start_topic_wiki(*, keyword: str, limit: int = 120) -> str:
    """提交主题 Wiki 后台生成任务，返回 task_id（MCP 语义：不落库）"""
    from packages.application.commands.graph import get_topic_wiki
    from packages.domain.task_tracker import global_tracker

    return global_tracker.submit(
        task_type="topic_wiki",
        title=f"Wiki: {keyword}",
        fn=lambda progress_callback=None: get_topic_wiki(
            keyword=keyword, limit=limit, progress_callback=progress_callback
        ),
    )


def start_topic_wiki_with_save(*, keyword: str, limit: int = 120) -> dict:
    """提交主题 Wiki 任务并在完成后写入 generated_contents（HTTP 语义）"""
    from packages.application.commands.generated import save_generated_content
    from packages.application.commands.graph import get_topic_wiki
    from packages.domain.task_tracker import global_tracker

    def _run(progress_callback=None):
        # task_tracker 传入的 progress_callback 签名为 (msg, cur, tot)；
        # graph topic_wiki 内部按 (pct 0-1, msg) 调用，此处适配
        def _adapted(pct: float, msg: str):
            if progress_callback:
                progress_callback(msg, int(pct * 100), 100)

        result = get_topic_wiki(keyword=keyword, limit=limit, progress_callback=_adapted)
        from packages.storage.db import session_scope

        with session_scope() as session:
            result["content_id"] = save_generated_content(
                session,
                content_type="topic_wiki",
                title=f"Topic Wiki: {keyword}",
                markdown=result.get("markdown", ""),
                keyword=keyword,
                metadata_json={k: v for k, v in result.items() if k != "markdown"},
            )
        return result

    task_id = global_tracker.submit(
        task_type="topic_wiki",
        title=f"Wiki: {keyword}",
        fn=_run,
        keyword=keyword,
        limit=limit,
        category="generation",
    )
    return {"task_id": task_id, "status": "pending"}
