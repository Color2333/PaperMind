"""
BackgroundTaskRunner — 后台任务执行，参考 learn-claude-code s08

核心设计：
- daemon 线程池执行耗时操作（编译、测试、部署）
- 主 agent loop 不阻塞，继续推理
- 任务完成后，通过通知队列注入回调

    BackgroundRunner.submit("build frontend", build_command):
        → 启动 daemon 线程执行命令
        → 主线程立即返回 "Task submitted"
        → daemon 完成 → notify(result)
        → 下次 agent loop 读取通知

    用途：
    - npm build / docker build（分钟级）
    - 长时间运行的测试
    - CI/CD 部署
    - 任何不应该卡住 agent 的操作
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from enum import Enum


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class BackgroundTask:
    id: str
    name: str
    command: str
    status: TaskStatus = TaskStatus.PENDING
    started_at: float | None = None
    finished_at: float | None = None
    result: str | None = None
    error: str | None = None

    @property
    def duration_ms(self) -> float | None:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at) * 1000
        return None


class BackgroundTaskRunner:
    """
    后台任务执行器。
    submit() 立即返回，任务在 daemon 线程运行。
    poll() / drain_notifications() 获取完成结果。
    """

    def __init__(self, max_workers: int = 4):
        self._task_queue: queue.Queue[BackgroundTask] = queue.Queue()
        self._notification_queue: queue.Queue[BackgroundTask] = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._max_workers = max_workers
        self._shutdown = False
        self._started = False
        self._task_counter = 0

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        for i in range(self._max_workers):
            t = threading.Thread(target=self._worker, daemon=True, name=f"bg-worker-{i}")
            t.start()
            self._threads.append(t)

    def _worker(self) -> None:
        while not self._shutdown:
            try:
                task = self._task_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            task.status = TaskStatus.RUNNING
            task.started_at = time.time()

            import subprocess

            try:
                result = subprocess.run(
                    task.command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=600,  # 10min max
                )
                task.result = (result.stdout + result.stderr).strip()
                task.status = TaskStatus.COMPLETED
            except subprocess.TimeoutExpired:
                task.error = "Timeout (600s exceeded)"
                task.status = TaskStatus.FAILED
            except Exception as exc:  # noqa: BLE001
                task.error = f"{type(exc).__name__}: {exc}"
                task.status = TaskStatus.FAILED
            finally:
                task.finished_at = time.time()
                self._notification_queue.put(task)

    def submit(self, name: str, command: str) -> str:
        if not self._started:
            self.start()

        self._task_counter += 1
        task_id = f"bg_{self._task_counter}_{int(time.time())}"
        task = BackgroundTask(id=task_id, name=name, command=command)
        self._task_queue.put(task)
        return task_id

    def status(self, task_id: str) -> str:
        # Peek at notification queue without removing
        with self._notification_queue.mutex:
            for task in self._notification_queue.queue:
                if task.id == task_id:
                    return self._format_status(task)
        return f"Task '{task_id}' not found or still pending."

    def poll(self) -> list[BackgroundTask]:
        """获取所有已完成的任务（从通知队列取出）"""
        completed = []
        while True:
            try:
                task = self._notification_queue.get_nowait()
                completed.append(task)
            except queue.Empty:
                break
        return completed

    def drain_notifications(self) -> str:
        """以文本形式返回所有已完成任务（适合注入 LLM context）"""
        completed = self.poll()
        if not completed:
            return ""
        lines = ["[Background tasks completed]"]
        for t in completed:
            lines.append(self._format_status(t))
        return "\n".join(lines)

    def shutdown(self, timeout: float = 5.0) -> None:
        self._shutdown = True
        for t in self._threads:
            t.join(timeout=timeout)

    @staticmethod
    def _format_status(task: BackgroundTask) -> str:
        duration = f"{task.duration_ms:.0f}ms" if task.duration_ms else "?"
        if task.status == TaskStatus.COMPLETED:
            result_preview = (task.result or "")[:200]
            return f"[{task.id}] {task.name}: completed in {duration}\n{result_preview}"
        elif task.status == TaskStatus.FAILED:
            return f"[{task.id}] {task.name}: FAILED in {duration}\n{task.error}"
        else:
            return f"[{task.id}] {task.name}: {task.status.value}"
