"""
TaskManager — 任务持久化系统，参考 learn-claude-code s07

核心设计：
- 任务以 JSON 文件形式持久化到 .tasks/ 目录
- 每个任务文件：task_{id}.json
- 依赖图：blockedBy / blocks 字段
- 完成任务时，自动从所有依赖任务的 blockedBy 中移除

    .tasks/
      task_1.json  {"id":1,"subject":"...","status":"completed","blockedBy":[],"blocks":[2]}
      task_2.json  {"id":2,"subject":"...","status":"pending","blockedBy":[1],"blocks":[]}
"""

from __future__ import annotations

import json
import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class Task:
    id: int
    subject: str
    description: str = ""
    status: Literal["pending", "in_progress", "completed"] = "pending"
    owner: str = ""
    worktree: str = ""
    blockedBy: list[int] = field(default_factory=list)
    blocks: list[int] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "subject": self.subject,
            "description": self.description,
            "status": self.status,
            "owner": self.owner,
            "worktree": self.worktree,
            "blockedBy": self.blockedBy,
            "blocks": self.blocks,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Task:
        return cls(
            id=d["id"],
            subject=d["subject"],
            description=d.get("description", ""),
            status=d.get("status", "pending"),
            owner=d.get("owner", ""),
            worktree=d.get("worktree", ""),
            blockedBy=d.get("blockedBy", []),
            blocks=d.get("blocks", []),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
        )


class TaskManager:
    """
    基于文件的任务管理器。
    所有操作即时落盘，任务不依赖进程存活。
    """

    def __init__(self, tasks_dir: Path):
        self.dir = tasks_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self._next_id = self._max_id() + 1

    # -- 内部方法 --
    def _max_id(self) -> int:
        ids = []
        for f in self.dir.glob("task_*.json"):
            try:
                parts = f.stem.split("_")
                if len(parts) == 2:
                    ids.append(int(parts[1]))
            except (ValueError, IndexError):
                pass
        return max(ids) if ids else 0

    def _path(self, task_id: int) -> Path:
        return self.dir / f"task_{task_id}.json"

    def _load(self, task_id: int) -> Task:
        path = self._path(task_id)
        if not path.exists():
            raise ValueError(f"Task {task_id} not found")
        return Task.from_dict(json.loads(path.read_text()))

    def _save(self, task: Task) -> None:
        task.updated_at = time.time()
        self._path(task.id).write_text(json.dumps(task.to_dict(), indent=2))

    # -- CRUD --
    def create(self, subject: str, description: str = "") -> str:
        """创建新任务，返回 JSON 字符串"""
        task = Task(id=self._next_id, subject=subject, description=description)
        self._save(task)
        self._next_id += 1
        return json.dumps(task.to_dict(), indent=2)

    def get(self, task_id: int) -> str:
        """获取任务详情，返回 JSON 字符串"""
        return json.dumps(self._load(task_id).to_dict(), indent=2)

    def update(
        self,
        task_id: int,
        status: str | None = None,
        owner: str | None = None,
    ) -> str:
        """
        更新任务状态或负责人。
        当状态设为 completed 时，自动解除所有依赖任务的阻塞。
        """
        task = self._load(task_id)

        if status:
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(
                    f"Invalid status: {status}. Must be one of: pending, in_progress, completed"
                )
            task.status = status

        if owner is not None:
            task.owner = owner

        if task.status == "completed":
            self._clear_dependency(task_id)

        self._save(task)
        return json.dumps(task.to_dict(), indent=2)

    def delete(self, task_id: int) -> str:
        """删除任务（如果已完成，从依赖任务中移除）"""
        task = self._load(task_id)
        if task.status == "completed":
            self._clear_dependency(task_id)
        self._path(task_id).unlink(missing_ok=True)
        return f"Deleted task {task_id}"

    # -- 依赖管理 --
    def add_blocked_by(self, task_id: int, blocked_by: list[int]) -> str:
        """设置任务依赖于其他任务（blockedBy）"""
        task = self._load(task_id)
        for bid in blocked_by:
            if bid not in task.blockedBy:
                task.blockedBy.append(bid)
                # 双向更新：blocked 任务也要记录 blocks
                try:
                    blocked_task = self._load(bid)
                    if task_id not in blocked_task.blocks:
                        blocked_task.blocks.append(task_id)
                        self._save(blocked_task)
                except ValueError:
                    pass  # blocked_by task doesn't exist
        self._save(task)
        return json.dumps(task.to_dict(), indent=2)

    def remove_blocked_by(self, task_id: int, blocked_by: int) -> str:
        """移除一个阻塞依赖"""
        task = self._load(task_id)
        if blocked_by in task.blockedBy:
            task.blockedBy.remove(blocked_by)
        if task_id in self._load(blocked_by).blocks:
            blocked_task = self._load(blocked_by)
            blocked_task.blocks.remove(task_id)
            self._save(blocked_task)
        self._save(task)
        return json.dumps(task.to_dict(), indent=2)

    def _clear_dependency(self, completed_id: int) -> None:
        """当任务完成时，从所有任务的 blockedBy 中移除它"""
        for f in self.dir.glob("task_*.json"):
            try:
                task = Task.from_dict(json.loads(f.read_text()))
                if completed_id in task.blockedBy:
                    task.blockedBy.remove(completed_id)
                    self._save(task)
            except (ValueError, json.JSONDecodeError):
                pass

    # -- 查询 --
    def list_all(self) -> str:
        """列出所有任务，带状态图标"""
        tasks = []
        for f in sorted(self.dir.glob("task_*.json")):
            with suppress(ValueError, json.JSONDecodeError):
                tasks.append(Task.from_dict(json.loads(f.read_text())))

        if not tasks:
            return "No tasks."

        lines = []
        for t in sorted(tasks, key=lambda x: x.id):
            marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}.get(
                t.status, "[?]"
            )
            owner_str = f" @{t.owner}" if t.owner else ""
            wt_str = f" wt={t.worktree}" if t.worktree else ""
            blocked_str = f" (blocked by {t.blockedBy})" if t.blockedBy else ""
            lines.append(f"{marker} #{t.id}: {t.subject}{blocked_str}{owner_str}{wt_str}")

        return "\n".join(lines)

    def list_pending(self) -> str:
        """只列出 pending 任务"""
        tasks = []
        for f in sorted(self.dir.glob("task_*.json")):
            try:
                t = Task.from_dict(json.loads(f.read_text()))
                if t.status == "pending":
                    tasks.append(t)
            except (ValueError, json.JSONDecodeError):
                pass
        if not tasks:
            return "No pending tasks."
        return "\n".join(f"#{t.id}: {t.subject}" for t in sorted(tasks, key=lambda x: x.id))

    def is_blocked(self, task_id: int) -> bool:
        """检查任务是否被阻塞（blockedBy 非空）"""
        try:
            task = self._load(task_id)
            return len(task.blockedBy) > 0
        except ValueError:
            return False

    def get_ready_tasks(self) -> list[Task]:
        """获取所有就绪任务（pending 且未被阻塞）"""
        ready = []
        for f in self.dir.glob("task_*.json"):
            try:
                t = Task.from_dict(json.loads(f.read_text()))
                if t.status == "pending" and not t.blockedBy:
                    ready.append(t)
            except (ValueError, json.JSONDecodeError):
                pass
        return sorted(ready, key=lambda x: x.id)
