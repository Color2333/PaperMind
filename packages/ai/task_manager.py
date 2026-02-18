"""
后台任务管理器 - 管理 wiki/brief 等耗时生成任务
@author Bamzc
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskInfo:
    task_id: str
    task_type: str
    title: str
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    message: str = ""
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "title": self.title,
            "status": self.status.value,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "has_result": self.result is not None,
        }


class TaskManager:
    """线程安全的后台任务管理器（单例）"""

    _instance: TaskManager | None = None
    _lock = threading.Lock()

    def __new__(cls) -> TaskManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._tasks: dict[str, TaskInfo] = {}
                cls._instance._tasks_lock = threading.Lock()
        return cls._instance

    def submit(
        self,
        task_type: str,
        title: str,
        fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """提交后台任务，返回 task_id"""
        task_id = uuid.uuid4().hex[:12]
        info = TaskInfo(
            task_id=task_id,
            task_type=task_type,
            title=title,
        )
        with self._tasks_lock:
            self._tasks[task_id] = info

        def _run():
            info.status = TaskStatus.RUNNING
            info.updated_at = time.time()
            try:
                info.result = fn(
                    *args,
                    progress_callback=lambda p, m: self._update_progress(
                        task_id, p, m
                    ),
                    **kwargs,
                )
                info.status = TaskStatus.COMPLETED
                info.progress = 1.0
                info.message = "完成"
                logger.info("Task %s completed: %s", task_id, title)
            except Exception as exc:
                info.status = TaskStatus.FAILED
                info.error = str(exc)
                logger.error("Task %s failed: %s - %s", task_id, title, exc)
            info.updated_at = time.time()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return task_id

    def _update_progress(
        self, task_id: str, progress: float, message: str
    ):
        with self._tasks_lock:
            info = self._tasks.get(task_id)
            if info:
                info.progress = progress
                info.message = message
                info.updated_at = time.time()

    def get_status(self, task_id: str) -> dict | None:
        with self._tasks_lock:
            info = self._tasks.get(task_id)
            return info.to_dict() if info else None

    def get_result(self, task_id: str) -> Any | None:
        with self._tasks_lock:
            info = self._tasks.get(task_id)
            return info.result if info else None

    def list_tasks(
        self, task_type: str | None = None, limit: int = 20,
    ) -> list[dict]:
        with self._tasks_lock:
            tasks = list(self._tasks.values())
        if task_type:
            tasks = [t for t in tasks if t.task_type == task_type]
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return [t.to_dict() for t in tasks[:limit]]

    def cleanup(self, max_age_seconds: int = 3600):
        """清理过期任务"""
        cutoff = time.time() - max_age_seconds
        with self._tasks_lock:
            expired = [
                tid for tid, t in self._tasks.items()
                if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
                and t.updated_at < cutoff
            ]
            for tid in expired:
                del self._tasks[tid]
