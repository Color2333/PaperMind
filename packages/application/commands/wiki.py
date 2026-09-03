"""Wiki 生成命令（B6；C3 退出门起走 durable Job + Executor）"""

from __future__ import annotations

from packages.application.commands.task_registry import get_spec


def start_topic_wiki(*, keyword: str, limit: int = 120) -> str:
    """提交主题 Wiki 后台生成任务，返回 task_id（MCP 语义：不落库）"""
    from packages.application.commands.graph import get_topic_wiki  # noqa: F401 — 保留语义引用
    from packages.application.commands.jobs import submit_job

    spec = get_spec("generate_topic_wiki")
    submitted = submit_job(
        kind="StartWikiGeneration",
        capability="generate_topic_wiki",
        title=f"Wiki: {keyword}",
        input_ref={"keyword": keyword, "limit": limit},
        resource_class=spec.resource_class,
        timeout_s=spec.timeout_s,
        max_attempts=spec.max_attempts,
    )
    return submitted["task_id"]


def start_topic_wiki_with_save(*, keyword: str, limit: int = 120) -> dict:
    """提交主题 Wiki 任务并在完成后写入 generated_contents（HTTP 语义）"""
    from packages.application.commands.jobs import submit_job

    spec = get_spec("topic_wiki_save")
    submitted = submit_job(
        kind="StartWikiGeneration",
        capability="topic_wiki_save",
        title=f"Wiki: {keyword}",
        input_ref={"keyword": keyword, "limit": limit},
        resource_class=spec.resource_class,
        timeout_s=spec.timeout_s,
        max_attempts=spec.max_attempts,
    )
    return {"task_id": submitted["task_id"], "job_id": submitted["job_id"], "status": "pending"}
