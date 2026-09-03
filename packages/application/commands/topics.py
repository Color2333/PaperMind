"""主题订阅命令（B8，设计② ManageTopics / StartTopicResearch / ImportReferences）"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from packages.domain.exceptions import NotFoundError

_FREQ_LABELS = {
    "daily": "每天",
    "twice_daily": "每天两次",
    "weekdays": "工作日",
    "weekly": "每周",
}
if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def upsert_topic(session: Session, **fields: Any) -> dict[str, Any]:
    """创建/更新主题订阅"""
    from packages.storage.repositories import TopicRepository

    topic = TopicRepository(session).upsert_topic(
        name=fields["name"],
        query=fields["query"],
        enabled=fields["enabled"],
        max_results_per_run=fields["max_results_per_run"],
        retry_limit=fields["retry_limit"],
        schedule_frequency=fields["schedule_frequency"],
        schedule_time_utc=fields["schedule_time_utc"],
        enable_date_filter=fields["enable_date_filter"],
        date_filter_days=fields["date_filter_days"],
    )
    from packages.application.queries.topics import _topic_dict

    return _topic_dict(topic, session)


def update_topic(session: Session, topic_id: str, **fields: Any) -> dict[str, Any]:
    from packages.storage.repositories import TopicRepository

    try:
        topic = TopicRepository(session).update_topic(topic_id, **fields)
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc
    from packages.application.queries.topics import _topic_dict

    return _topic_dict(topic, session)


def delete_topic(session: Session, topic_id: str) -> dict[str, Any]:
    from packages.storage.repositories import TopicRepository

    TopicRepository(session).delete_topic(topic_id)
    return {"deleted": topic_id}


def start_topic_fetch(topic_id: str) -> dict[str, Any]:
    """手动触发单个订阅抓取（durable Job，Executor 执行）"""
    from packages.application.commands.jobs import submit_job
    from packages.application.commands.task_registry import get_spec
    from packages.storage.db import session_scope
    from packages.storage.models import TopicSubscription

    with session_scope() as session:
        topic = session.get(TopicSubscription, topic_id)
        if not topic:
            raise NotFoundError("订阅不存在")
        topic_name = topic.name

    spec = get_spec("fetch_topic_papers")
    submitted = submit_job(
        kind="StartTopicResearch",
        capability="fetch_topic_papers",
        title=f"抓取：{topic_name[:30]}",
        input_ref={"topic_id": topic_id},
        resource_class=spec.resource_class,
        timeout_s=spec.timeout_s,
        max_attempts=spec.max_attempts,
    )
    task_id = submitted["task_id"]
    return {
        "status": "started",
        "task_id": task_id,
        "topic_id": topic_id,
        "topic_name": topic_name,
        "message": f"「{topic_name}」抓取已在后台启动",
    }


def start_reference_import(
    *,
    source_paper_id: str,
    source_paper_title: str,
    entries: list[dict],
    topic_ids: list[str] | None = None,
) -> dict[str, Any]:
    """一键导入参考文献（durable Job，Executor 执行；返回 task_id + total）"""
    from packages.application.commands.jobs import submit_job
    from packages.application.commands.task_registry import get_spec

    spec = get_spec("import_references")
    submitted = submit_job(
        kind="StartReferenceImport",
        capability="import_references",
        title=f"参考文献导入：{source_paper_title[:60]}",
        input_ref={
            "source_paper_id": source_paper_id,
            "source_paper_title": source_paper_title,
            "entries": entries,
            "topic_ids": topic_ids or [],
        },
        resource_class=spec.resource_class,
        timeout_s=spec.timeout_s,
        max_attempts=spec.max_attempts,
    )
    return {"task_id": submitted["task_id"], "total": len(entries)}


def update_subscription(
    session: Session,
    *,
    topic_name: str,
    enabled: bool,
    schedule_frequency: str | None = None,
    schedule_time_beijing: int | None = None,
) -> dict[str, Any]:
    """启用/禁用订阅并调整调度；主题不存在抛 NotFoundError"""
    from packages.storage.repositories import TopicRepository

    topic = TopicRepository(session).get_by_name(topic_name.strip())
    if not topic:
        raise NotFoundError(f"主题「{topic_name}」不存在")
    topic.enabled = enabled
    if schedule_frequency and schedule_frequency in _FREQ_LABELS:
        topic.schedule_frequency = schedule_frequency
    if schedule_time_beijing is not None:
        utc_hour = (schedule_time_beijing - 8) % 24
        topic.schedule_time_utc = max(0, min(23, utc_hour))
    return {
        "topic": topic_name,
        "enabled": enabled,
        "schedule_frequency": schedule_frequency or "daily",
        "schedule_time_beijing": (
            schedule_time_beijing if schedule_time_beijing is not None else 5
        ),
        "schedule_frequency_effective": topic.schedule_frequency,
        "bj_hour_effective": (topic.schedule_time_utc + 8) % 24,
    }
