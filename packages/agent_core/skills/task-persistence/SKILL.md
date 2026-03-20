---
name: task-persistence
description: |
  基于文件的 TaskManager，任务持久化 + 依赖图。
  使用此 skill 当你需要：
  - 创建跨会话持久化的任务
  - 管理任务间的 blockedBy/blocks 依赖关系
  - 理解 s07 TaskSystem 的文件格式
---

# Task Persistence — 任务持久化 + 依赖图

## 核心设计（s07 Motto）

> **"Break big goals into small tasks, order them, persist to disk."**

任务落盘 → 对话结束后任务不丢失 → 下次开新会话仍然可以继续。

## 文件格式

```
.tasks/
  task_1.json   ← 任务文件
  task_2.json
  task_3.json
```

每个任务文件内容：

```json
{
  "id": 1,
  "subject": "实现用户认证",
  "description": "添加 JWT 登录功能",
  "status": "pending",
  "owner": "alice",
  "worktree": "",
  "blockedBy": [2],
  "blocks": [3],
  "created_at": 1710000000.0,
  "updated_at": 1710000000.0
}
```

## 依赖图机制

```
task_1 (pending) ──blockedBy[2]──→ task_2 (in_progress)
task_3 (pending) ──blockedBy[1]──→ task_1 (pending)
```

- `blockedBy`: 当前任务依赖哪些任务（必须等它们完成）
- `blocks`: 当前任务阻断了哪些任务（完成后自动解除它们的阻塞）

**自动解除**：`task_2.status = "completed"` → task_1.blockedBy 自动移除 `[2]`

## 使用方式

```python
from pathlib import Path
from agent_core import TaskManager

tm = TaskManager(Path(".tasks"))

# 创建任务
tm.create("实现登录 API", "添加 POST /auth/login")
# → 返回 {"id": 1, "subject": "实现登录 API", ...}

# 列出所有
print(tm.list_all())
# [ ] #1: 实现登录 API
# [ ] #2: 实现注册 API

# 更新状态
tm.update(task_id=1, status="completed")
# 完成 task #1 后，依赖它的任务自动解除阻塞

# 设置依赖
tm.add_blocked_by(task_id=3, blocked_by=[1, 2])
# task #3 被 task #1 和 task #2 阻塞
```

## list_all() 输出格式

```
[ ] #1: 实现登录 API
[>] #2: 实现注册 API (owner @alice)
[x] #3: 添加单元测试 (completed 2024-01-01)
    #4: 部署上线 (blocked by [1, 3])
```

标记含义：`[ ]` pending / `[>]` in_progress / `[x]` completed

## 关键方法

| 方法 | 返回 | 说明 |
|------|------|------|
| `create(subject, desc?)` | JSON str | 创建新任务 |
| `get(task_id)` | JSON str | 获取任务详情 |
| `update(task_id, status?, owner?)` | JSON str | 更新状态/负责人 |
| `delete(task_id)` | str | 删除任务 |
| `list_all()` | str | 列出所有任务 |
| `list_pending()` | str | 只列 pending |
| `add_blocked_by(task_id, [dep_id, ...])` | JSON str | 设置阻塞依赖 |
| `is_blocked(task_id)` | bool | 是否被阻塞 |
| `get_ready_tasks()` | list[Task] | 所有就绪任务 |

## 依赖管理细节

```python
# 设置 task #3 依赖 task #1 和 task #2
tm.add_blocked_by(task_id=3, blocked_by=[1, 2])

# 双向记录：task #1.blocks = [3], task #2.blocks = [3]

# 完成 task #1
tm.update(task_id=1, status="completed")
# → task #3.blockedBy 自动变为 [2]（task #1 已完成）

# 再完成 task #2
tm.update(task_id=2, status="completed")
# → task #3.blockedBy 变为 []（完全解除阻塞）
# → task #3 现在可以开始了
```

## 与 AgentLoop 集成

```python
dispatcher = ToolDispatcher()
tm = TaskManager(Path(".tasks"))

dispatcher.register("task_create", lambda subject, description="": tm.create(subject, description))
dispatcher.register("task_list", lambda: tm.list_all())
dispatcher.register("task_update", lambda task_id, status=None: tm.update(task_id, status=status))
```

## 何时用 TaskManager

**用：**
- 多步骤任务需要跨会话持久化
- 任务间有明确的先后依赖
- 需要给任务分配 owner
- 多 agent 协作需要共享任务状态

**不用：**
- 一次性简单任务
- 不需要跨会话记住的临时 todo
- 已有其他任务系统（如 Linear、Jira）
