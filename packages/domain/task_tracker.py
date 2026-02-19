"""
全局任务追踪器 — 跨页面可见的实时任务进度
@author Bamzc
"""
import threading
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TaskInfo:
    task_id: str
    task_type: str
    title: str
    current: int = 0
    total: int = 0
    message: str = ""
    started_at: float = field(default_factory=time.time)
    finished: bool = False
    success: bool = True
    error: Optional[str] = None

    def to_dict(self) -> dict:
        elapsed = time.time() - self.started_at
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "title": self.title,
            "current": self.current,
            "total": self.total,
            "message": self.message,
            "elapsed_seconds": round(elapsed, 1),
            "progress_pct": round(self.current / self.total * 100) if self.total > 0 else 0,
            "finished": self.finished,
            "success": self.success,
            "error": self.error,
        }


class TaskTracker:
    """线程安全的全局任务追踪器（纯内存，不持久化）"""

    def __init__(self):
        self._tasks: dict[str, TaskInfo] = {}
        self._lock = threading.Lock()
        self._ttl = 120  # 完成后保留 2 分钟供前端展示

    def start(self, task_id: str, task_type: str, title: str, total: int = 0) -> TaskInfo:
        task = TaskInfo(
            task_id=task_id,
            task_type=task_type,
            title=title,
            total=total,
        )
        with self._lock:
            self._cleanup()
            self._tasks[task_id] = task
        return task

    def update(self, task_id: str, current: int, message: str = "", total: int | None = None):
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.current = current
                task.message = message
                if total is not None:
                    task.total = total

    def finish(self, task_id: str, success: bool = True, error: str | None = None):
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.finished = True
                task.success = success
                task.error = error
                task.current = task.total

    def get_active(self) -> list[dict]:
        with self._lock:
            self._cleanup()
            return [t.to_dict() for t in self._tasks.values()]

    def _cleanup(self):
        """清除完成超过 TTL 的任务"""
        now = time.time()
        expired = [
            tid for tid, t in self._tasks.items()
            if t.finished and (now - t.started_at) > self._ttl
        ]
        for tid in expired:
            del self._tasks[tid]


# 全局单例
global_tracker = TaskTracker()
