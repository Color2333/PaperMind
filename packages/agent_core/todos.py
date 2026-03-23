"""
统一 TodoWrite 接口 — 支持跨 subagent 会话持久化

整合散落在各 skill 的任务计划功能，提供：
- TodoItem: 原子任务单元
- TodoManager: 统一任务管理（文件持久化）
- PlannerMixin: 计划生成混入类

@author Color2333
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Iterator


@dataclass
class TodoItem:
    """原子任务单元"""

    id: str
    content: str  # "[WHERE] [HOW] to [WHY] — expect [RESULT]"
    status: Literal["pending", "in_progress", "completed", "cancelled"] = "pending"
    priority: Literal["high", "medium", "low"] = "medium"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    parent_id: str | None = None  # 父任务 ID，用于子任务分解

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "status": self.status,
            "priority": self.priority,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "parent_id": self.parent_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TodoItem:
        return cls(
            id=d["id"],
            content=d["content"],
            status=d.get("status", "pending"),
            priority=d.get("priority", "medium"),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            parent_id=d.get("parent_id"),
        )


class TodoManager:
    """
    统一任务管理器，支持跨 subagent 会话持久化。

    存储格式：
        {storage_path}/
            todos.json  # 所有 todo 的 JSON 数组

    使用方式：
        manager = TodoManager()
        todo_id = manager.create("实现登录功能", priority="high")
        manager.set_in_progress(todo_id)
        manager.complete(todo_id)
    """

    DEFAULT_STORAGE_PATH = ".todos"

    def __init__(self, storage_path: str | None = None):
        self.storage_path = Path(storage_path or self.DEFAULT_STORAGE_PATH)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._todos_file = self.storage_path / "todos.json"
        self._todos: dict[str, TodoItem] = {}
        self._load()

    def _load(self) -> None:
        """从文件加载所有 todos"""
        if self._todos_file.exists():
            try:
                data = json.loads(self._todos_file.read_text())
                self._todos = {item["id"]: TodoItem.from_dict(item) for item in data}
            except (json.JSONDecodeError, KeyError):
                self._todos = {}

    def _save(self) -> None:
        """持久化到文件"""
        data = [todo.to_dict() for todo in self._todos.values()]
        self._todos_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def _touch_updated(self, todo: TodoItem) -> None:
        """更新 updated_at 时间戳"""
        todo.updated_at = time.time()

    # ========== CRUD ==========

    def create(
        self,
        content: str,
        priority: str = "medium",
        parent_id: str | None = None,
    ) -> str:
        """
        创建新 todo，返回 todo_id。

        content 格式建议："[WHERE] [HOW] to [WHY] — expect [RESULT]"
        """
        todo_id = f"todo_{uuid.uuid4().hex[:8]}"
        todo = TodoItem(
            id=todo_id,
            content=content,
            priority=priority,  # type: ignore
            parent_id=parent_id,
        )
        self._todos[todo_id] = todo
        self._save()
        return todo_id

    def get(self, todo_id: str) -> dict | None:
        """获取 todo 详情"""
        todo = self._todos.get(todo_id)
        return todo.to_dict() if todo else None

    def update(
        self,
        todo_id: str,
        status: str | None = None,
        content: str | None = None,
    ) -> dict:
        """
        更新 todo 状态或内容。
        返回更新后的 todo 字典。
        """
        todo = self._todos.get(todo_id)
        if not todo:
            raise ValueError(f"Todo {todo_id} not found")

        if status:
            if status not in ("pending", "in_progress", "completed", "cancelled"):
                raise ValueError(f"Invalid status: {status}")
            todo.status = status  # type: ignore

        if content:
            todo.content = content

        self._touch_updated(todo)
        self._save()
        return todo.to_dict()

    def list_all(self, status: str | None = None) -> list[dict]:
        """
        列出所有 todos。
        可选按 status 过滤。
        """
        todos = list(self._todos.values())
        if status:
            todos = [t for t in todos if t.status == status]
        return sorted([t.to_dict() for t in todos], key=lambda x: x["created_at"])

    def list_in_progress(self) -> list[dict]:
        """列出所有 in_progress 的 todos"""
        return self.list_all(status="in_progress")

    # ========== 状态变更快捷方法 ==========

    def set_in_progress(self, todo_id: str) -> None:
        """标记为进行中"""
        self.update(todo_id, status="in_progress")

    def complete(self, todo_id: str) -> None:
        """标记为已完成"""
        self.update(todo_id, status="completed")

    def cancel(self, todo_id: str) -> None:
        """标记为已取消"""
        self.update(todo_id, status="cancelled")

    def delete(self, todo_id: str) -> None:
        """删除 todo"""
        if todo_id in self._todos:
            del self._todos[todo_id]
            self._save()

    # ========== 层级结构 ==========

    def get_children(self, parent_id: str) -> list[dict]:
        """获取子任务列表"""
        children = [t for t in self._todos.values() if t.parent_id == parent_id]
        return sorted([t.to_dict() for t in children], key=lambda x: x["created_at"])

    def get_tree(self) -> dict:
        """
        获取树形结构。
        返回格式：
            {
                "roots": [todo_dict, ...],
                "children": {parent_id: [todo_dict, ...], ...}
            }
        """
        roots = [t for t in self._todos.values() if not t.parent_id]
        children_map: dict[str, list[dict]] = {}

        for todo in self._todos.values():
            if todo.parent_id:
                if todo.parent_id not in children_map:
                    children_map[todo.parent_id] = []
                children_map[todo.parent_id].append(todo.to_dict())

        return {
            "roots": sorted([t.to_dict() for t in roots], key=lambda x: x["created_at"]),
            "children": {
                k: sorted(v, key=lambda x: x["created_at"]) for k, v in children_map.items()
            },
        }

    # ========== 批量操作 ==========

    def batch_create(self, items: list[str], priority: str = "medium") -> list[str]:
        """
        批量创建 todos。
        返回 todo_id 列表。
        """
        return [self.create(content=item, priority=priority) for item in items]

    def clear_completed(self) -> int:
        """清理所有已完成的 todos，返回清理数量"""
        completed_ids = [tid for tid, t in self._todos.items() if t.status == "completed"]
        for tid in completed_ids:
            del self._todos[tid]
        if completed_ids:
            self._save()
        return len(completed_ids)


class PlannerMixin:
    """
    计划生成混入类。

    混入 AgentLoop，在必要时生成任务计划。
    子类需要实现 _call_llm_for_plan 方法。
    """

    def needs_plan(self, task: str) -> bool:
        """
        判断任务是否需要计划。

        简单启发式：
        - 包含"实现"、"开发"、"构建"等关键词
        - 任务描述超过 50 字符
        """
        plan_keywords = ("实现", "开发", "构建", "创建", "设计", "重构", "修复", "优化")
        return any(kw in task for kw in plan_keywords) or len(task) > 50

    def plan(self, task: str) -> list[str]:
        """
        生成任务计划。

        子类应重写此方法，调用 LLM 生成计划。
        返回 TodoItem content 列表。
        """
        raise NotImplementedError("Subclass must implement plan() method")

    def _call_llm_for_plan(self, task: str) -> list[str]:
        """
        调用 LLM 生成计划的内部方法。

        子类实现此方法，返回分解后的子任务列表。
        格式要求：每个子任务遵循 "[WHERE] [HOW] to [WHY] — expect [RESULT]"
        """
        raise NotImplementedError("Subclass must implement _call_llm_for_plan()")

    def execute_with_plan(
        self,
        task: str,
        manager: TodoManager,
        executor: Any,
    ) -> Iterator[dict]:
        """
        带计划的执行流程。

        1. 判断是否需要计划
        2. 如需要，生成计划并创建 todos
        3. 逐个执行 todos，更新状态
        4. yield 进度事件

        Args:
            task: 任务描述
            manager: TodoManager 实例
            executor: 执行器（需要有 execute(todo_content) 方法）

        Yields:
            进度事件字典 {"type": "todo_start"|"todo_progress"|"todo_done", ...}
        """
        if not self.needs_plan(task):
            # 简单任务直接执行
            todo_id = manager.create(content=task)
            manager.set_in_progress(todo_id)
            yield {"type": "todo_start", "todo_id": todo_id, "content": task}

            try:
                result = executor.execute(task)
                manager.complete(todo_id)
                yield {"type": "todo_done", "todo_id": todo_id, "success": True, "result": result}
            except Exception as exc:
                manager.cancel(todo_id)
                yield {"type": "todo_done", "todo_id": todo_id, "success": False, "error": str(exc)}
            return

        # 复杂任务：生成计划
        subtasks = self.plan(task)
        parent_id = manager.create(content=task, priority="high")
        manager.set_in_progress(parent_id)
        yield {"type": "plan_start", "parent_id": parent_id, "subtasks": subtasks}

        # 创建子任务
        child_ids = []
        for subtask in subtasks:
            child_id = manager.create(content=subtask, parent_id=parent_id)
            child_ids.append(child_id)

        # 逐个执行子任务
        for child_id in child_ids:
            todo = manager.get(child_id)
            if not todo:
                continue

            manager.set_in_progress(child_id)
            yield {"type": "todo_start", "todo_id": child_id, "content": todo["content"]}

            try:
                result = executor.execute(todo["content"])
                manager.complete(child_id)
                yield {"type": "todo_done", "todo_id": child_id, "success": True, "result": result}
            except Exception as exc:
                manager.cancel(child_id)
                yield {
                    "type": "todo_done",
                    "todo_id": child_id,
                    "success": False,
                    "error": str(exc),
                }
                # 子任务失败，父任务也取消
                manager.cancel(parent_id)
                return

        # 所有子任务完成，父任务也完成
        manager.complete(parent_id)
        yield {"type": "plan_done", "parent_id": parent_id, "success": True}


# ========== 工具函数 ==========


def format_todo_content(where: str, how: str, why: str, expected: str) -> str:
    """
    格式化 todo content。

    格式："[WHERE] [HOW] to [WHY] — expect [RESULT]"

    Example:
        format_todo_content(
            where="src/auth/login.ts",
            how="Add validateToken()",
            why="ensure token not expired",
            expected="returns boolean"
        )
        # => "src/auth/login.ts: Add validateToken() to ensure token not expired — returns boolean"
    """
    return f"{where}: {how} to {why} — expect {expected}"


# ========== 全局单例（可选使用） ==========

_global_manager: TodoManager | None = None


def get_todo_manager(storage_path: str | None = None) -> TodoManager:
    """获取全局 TodoManager 单例"""
    global _global_manager
    if _global_manager is None:
        _global_manager = TodoManager(storage_path)
    return _global_manager


def reset_todo_manager() -> None:
    """重置全局 TodoManager（用于测试）"""
    global _global_manager
    _global_manager = None
