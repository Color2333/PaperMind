"""Reconciler（C8，设计③ §运行组件边界）

应用层循环：回收过期 lease → 按 C4 注册表判定 manual_recovery（不可自动重试的
能力直接标 manual_recovery，不回队列）→ 其余按 backoff/dead_letter 由仓储处理。

单次运行 `run_reconcile` 幂等；周期触发在部署层（worker 循环 / cron）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from packages.domain.enums import TaskStatus

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def run_reconcile(session: Session, *, now: Any = None, backoff_s: int = 60) -> dict[str, Any]:
    """回收过期 lease 并按能力边界处置；返回统计。"""
    from packages.application.commands.task_registry import TASK_CAPABILITIES
    from packages.storage.models import DurableTask
    from packages.storage.repositories import TaskRepository

    outcomes = TaskRepository(session).reclaim_expired_leases(now=now, backoff_s=backoff_s)

    # manual_recovery 能力：不回队列——直接标 manual_recovery
    manual_moved: list[str] = []
    for task_id, outcome in outcomes.items():
        if outcome != "requeued":
            continue
        task = session.get(DurableTask, task_id)
        if task is None:
            continue
        spec = TASK_CAPABILITIES.get(task.capability)
        if spec is not None and spec.manual_recovery:
            task.status = TaskStatus.manual_recovery
            manual_moved.append(task_id)
            session.flush()

    requeued = sum(1 for v in outcomes.values() if v == "requeued") - len(manual_moved)
    dead = sum(1 for v in outcomes.values() if v == "dead_letter")
    logger.info(
        "Reconcile 完成：回收 %d，requeue %d，dead_letter %d，manual_recovery %d",
        len(outcomes),
        requeued,
        dead,
        len(manual_moved),
    )
    return {
        "reclaimed": len(outcomes),
        "outcomes": outcomes,
        "manual_recovery": manual_moved,
    }
