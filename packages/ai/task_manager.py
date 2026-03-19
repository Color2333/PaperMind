"""
后台任务管理器 - 委托给 global_tracker 统一管理
@author Color2333
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from packages.domain.task_tracker import global_tracker

logger = logging.getLogger(__name__)


class TaskManager:
    """向后兼容的任务管理器 - 所有操作委托给 global_tracker"""

    _instance: TaskManager | None = None

    def __new__(cls) -> TaskManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def submit(
        self,
        task_type: str,
        title: str,
        fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """提交后台任务 - 委托给 global_tracker"""

        def _wrapped_fn(*a: Any, progress_callback=None, **kw: Any):
            def _adapted_cb(progress: float, message: str):
                if progress_callback:
                    progress_callback(message, int(progress * 100), 100)

            return fn(*a, *args, progress_callback=_adapted_cb, **kw, **kwargs)

        return global_tracker.submit(
            task_type=task_type,
            title=title,
            fn=_wrapped_fn,
            category="generation",
        )

    def get_status(self, task_id: str) -> dict | None:
        return global_tracker.get_task(task_id)

    def get_result(self, task_id: str) -> Any | None:
        return global_tracker.get_result(task_id)

    def list_tasks(self, task_type: str | None = None, limit: int = 20) -> list[dict]:
        all_tasks = global_tracker.get_active()
        if task_type:
            all_tasks = [t for t in all_tasks if t.get("task_type") == task_type]
        return all_tasks[:limit]

    def cleanup(self, max_age_seconds: int = 3600):
        pass  # global_tracker 自己管理清理
