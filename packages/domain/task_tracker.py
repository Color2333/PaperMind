"""
统一任务追踪与执行框架 — 替代原来分散的 4 套任务系统
@author Color2333

功能：
- 全局任务进度追踪（前端轮询可见）
- 后台任务提交与执行（线程池管理）
- 统一 start / update / finish 生命周期
- 线程安全 + 自动清理过期任务
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

# 完成后保留 2 分钟供前端展示
_FINISHED_TTL = 120


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
    error: str | None = None
    result: Any = None

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
            "has_result": self.result is not None,
        }


class TaskTracker:
    """
    统一的全局任务追踪器（线程安全，纯内存）

    两种使用方式：
    1. 纯追踪：手动调用 start/update/finish 管理生命周期
    2. 提交执行：调用 submit() 自动在后台线程执行 + 追踪
    """

    def __init__(self):
        self._tasks: dict[str, TaskInfo] = {}
        self._lock = threading.Lock()

    # ---------- 生命周期管理（纯追踪） ----------

    def start(self, task_id: str, task_type: str, title: str, total: int = 0) -> TaskInfo:
        """注册一个任务，开始追踪"""
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
        """更新任务进度"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.current = current
                task.message = message
                if total is not None:
                    task.total = total

    def finish(self, task_id: str, success: bool = True, error: str | None = None):
        """标记任务完成"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.finished = True
                task.success = success
                task.error = error
                task.current = task.total

    # ---------- 提交执行（追踪 + 后台线程） ----------

    def submit(
        self,
        task_type: str,
        title: str,
        fn: Callable[..., Any],
        *args: Any,
        total: int = 100,
        **kwargs: Any,
    ) -> str:
        """
        提交后台任务，自动追踪进度

        fn 可接收 progress_callback(message, current, total) 参数
        返回 task_id
        """
        task_id = f"{task_type}_{uuid.uuid4().hex[:8]}"
        self.start(task_id, task_type, title, total=total)

        def _run():
            try:
                result = fn(
                    *args,
                    progress_callback=lambda msg, cur, tot: self.update(task_id, cur, msg, total=tot or total),
                    **kwargs,
                )
                with self._lock:
                    task = self._tasks.get(task_id)
                    if task:
                        task.result = result
                self.finish(task_id, success=True)
                logger.info("Task %s completed: %s", task_id, title)
            except Exception as exc:
                self.finish(task_id, success=False, error=str(exc)[:200])
                logger.error("Task %s failed: %s - %s", task_id, title, exc)

        thread = threading.Thread(target=_run, daemon=True, name=f"task-{task_id}")
        thread.start()
        return task_id

    # ---------- 查询 ----------

    def get_active(self) -> list[dict]:
        """获取所有活跃任务（含刚完成的）"""
        with self._lock:
            self._cleanup()
            return [t.to_dict() for t in self._tasks.values()]

    def get_task(self, task_id: str) -> dict | None:
        """查询单个任务状态"""
        with self._lock:
            task = self._tasks.get(task_id)
            return task.to_dict() if task else None

    def get_result(self, task_id: str) -> Any | None:
        """获取已完成任务的结果"""
        with self._lock:
            task = self._tasks.get(task_id)
            return task.result if task else None

    # ---------- 内部清理 ----------

    def _cleanup(self):
        """清除完成超过 TTL 的任务"""
        now = time.time()
        expired = [
            tid for tid, t in self._tasks.items()
            if t.finished and (now - t.started_at) > _FINISHED_TTL
        ]
        for tid in expired:
            del self._tasks[tid]


# 全局单例 — 整个应用共享一个 tracker
global_tracker = TaskTracker()
