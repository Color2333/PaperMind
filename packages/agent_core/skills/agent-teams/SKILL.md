---
name: agent-teams
description: |
  多 Agent 协作机制，持久 agent + 异步通信 + 团队管理。
  使用此 skill 当你需要：
  - 理解 Agent Teams 的工作方式
  - 使用 MessageBus 进行 agent 间通信
  - 使用 TeammateManager 管理持久 agent 线程
---

# Agent Teams — 多 Agent 协作

## Subagent vs Teammate（s09 核心区别）

```
Subagent (一次性):
  spawn → execute → return summary → destroyed

Teammate (持久):
  spawn → work → idle → work → ... → shutdown
```

**Subagent** 适合独立子任务。
**Teammate** 适合需要持续工作、等待指令的助手。

## MessageBus — 异步邮箱机制

每个 teammate 有一个 JSONL 文件作为收件箱：

```
.team/inbox/
  alice.jsonl    ← alice 的消息
  bob.jsonl      ← bob 的消息
  lead.jsonl    ← lead（主 agent）的消息
```

发消息 = 追加到文件（append-only，不丢消息）
读消息 = 读取并清空文件

```python
from pathlib import Path
from agent_core import MessageBus

bus = MessageBus(Path(".team/inbox"))

# 发消息
bus.send("lead", "alice", "please fix the login bug")
bus.send("lead", "bob", "review alice's PR")

# 读自己的收件箱（lead）
messages = bus.read_inbox("lead")
# [{'type': 'message', 'from': 'alice', 'content': 'login bug fixed', ...}, ...]

# 广播
bus.broadcast("lead", "all devs: meeting in 5 min", teammates=["alice", "bob", "carol"])
```

## TeammateManager — 持久 agent 线程管理

```python
from pathlib import Path
from agent_core import TeammateManager, make_default_dispatcher

tm = TeammateManager(
    team_dir=Path(".team"),
    inbox_dir=Path(".team/inbox"),
    model="claude-sonnet-4-20250514",
    system_base="你是一个代码审查 agent。",
)

dispatcher = make_default_dispatcher(workdir=Path.cwd())
tm.spawn(
    name="reviewer",
    role="code_reviewer",
    prompt="审查 apps/api/auth.py 的安全性，给出改进建议。",
    tools=dispatcher.get_tool_definitions(),
)
# → Spawned 'reviewer' (role: code_reviewer)
```

reviewer agent 在独立线程运行，有自己的 inbox，可以接收 lead 的消息。

## 消息类型（5种）

| 类型 | 用途 | 方向 |
|------|------|------|
| `message` | 普通文本消息 | any → any |
| `broadcast` | 广播 | lead → all |
| `shutdown_request` | 请求关闭 | lead → teammate |
| `shutdown_response` | 同意/拒绝关闭 | teammate → lead |
| `plan_approval_request` | 请求批准计划 | teammate → lead |
| `plan_approval_response` | 同意/拒绝计划 | lead → teammate |

## shutdown 流程

```
lead ──shutdown_request──→ alice
                          alice: 停止接单，完成当前任务
alice ──shutdown_response(approved)──→ lead
```

```python
# lead 请求关闭
tm.shutdown("alice")

# alice 的线程收到 shutdown_request
# → 完成当前任务 → 状态改为 idle

# 检查 team 状态
print(tm.list_all())
# Team: default
#   reviewer (code_reviewer): idle
#   tester (qa): idle
```

## 使用场景

**适合 Team 模式：**
- 代码审查 + 实际修改（两个 agent 并行）
- 前端 + 后端同时开发
- 一个 agent 执行，另一个 agent 监控质量

**不适合：**
- 简单一次性任务 → 用 Subagent
- 强耦合任务 → 一个 agent 做到底

## 5种消息详解

### message（普通消息）

```python
bus.send("lead", "alice", "PR #42 已创建，请审查")
bus.send("alice", "lead", "审查完成，发现3个安全问题")
```

### broadcast（广播）

```python
bus.broadcast("lead", "meeting cancelled", teammates=["alice", "bob"])
# → 发送到 alice.jsonl 和 bob.jsonl
```

### shutdown_request / shutdown_response

```python
# lead 发送关闭请求
tm.shutdown("alice")

# alice 线程内部处理：
# if msg["type"] == "shutdown_request":
#     bus.send("alice", "lead", "approved", "shutdown_response")
#     return  # 退出 loop
```

### plan_approval_request / response

```python
# alice 发计划给 lead 审批
bus.send("alice", "lead",
         "我计划重构 auth.py，拆分成 auth/jwt.py 和 auth/oauth.py",
         "plan_approval_request")

# lead 审批
bus.send("lead", "alice", "approved: 可以开始", "plan_approval_response")
```
