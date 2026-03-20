---
name: team-protocols
description: |
  Agent Team 通信协议 FSM：shutdown / plan_approval。
  使用此 skill 当你需要：
  - 实现优雅关闭协议
  - 实现计划审批协议
  - 理解 s10 Team Protocols 的状态机设计
---

# Team Protocols — 通信协议 FSM

## 核心设计（s10 Motto）

> **"Teammates need shared communication rules."**

没有协议 = agent 间通信混乱。
有协议 = 行为可预测、可控制。

## 5种消息类型

所有 agent 间通信都是这 5 种之一：

| type | 触发方 | 接收方 | 用途 |
|------|--------|--------|------|
| `message` | any | any | 普通对话 |
| `broadcast` | lead | all | 广播通知 |
| `shutdown_request` | lead | teammate | 请求关闭 |
| `shutdown_response` | teammate | lead | 同意/拒绝关闭 |
| `plan_approval_request` | teammate | lead | 请求批准计划 |
| `plan_approval_response` | lead | teammate | 同意/拒绝计划 |

## shutdown FSM

```
     lead                    teammate
       │                         │
       │──── shutdown_request ───→│
       │                         │
       │                    [处理中]
       │                         │
       │←── shutdown_response ────┤
       │    (approved/rejected)   │
       │                         │
```

### 实现

```python
from agent_core import TeamProtocols

protocol = TeamProtocols()

# lead 请求关闭 teammate
msg = protocol.request_shutdown("alice")
bus.send("lead", "alice", msg["content"], msg["type"])

# teammate 处理 shutdown_request
# ... 执行清理 ...

# teammate 同意关闭
result = protocol.handle_shutdown_response("alice", approved=True)
# "Alice approved shutdown."

# teammate 拒绝关闭
result = protocol.handle_shutdown_response("alice", approved=False, message="PR #42 还没审完")
# "Alice rejected shutdown: PR #42 还没审完"
```

## plan_approval FSM

当 teammate 需要 lead 确认才能继续时：

```
     teammate                 lead
       │                       │
       │─── plan_approval ────→│
       │      request          │
       │                       │ ← human review / auto approve
       │←── plan_approval ─────┤
       │     response          │
       │                       │
```

### 实现

```python
# teammate 发送计划审批请求
msg = protocol.request_plan_approval(
    agent_name="alice",
    plan_summary="重构 auth.py 为独立模块",
    plan_detail="拆成 auth/jwt.py, auth/oauth.py, auth/session.py",
)
bus.send("alice", "lead", msg["content"], msg["type"])

# lead 处理（可以是 human-in-the-loop 或 auto approve）
bus.send("lead", "alice", "approved: 可以开始重构", "plan_approval_response")
result = protocol.handle_plan_response(approval_id=msg["approval_id"], approved=True)
# "Plan approved for 'alice': 可以开始重构"
```

## 状态机

```python
class ProtocolState(Enum):
    IDLE                      = "idle"
    AWAITING_SHUTDOWN_RESPONSE = "awaiting_shutdown_response"
    AWAITING_PLAN_APPROVAL     = "awaiting_plan_approval"
    WORKING                    = "working"
```

每个 agent 在 TeamProtocols 中记录状态：
- `IDLE` → 可以接受新任务
- `AWAITING_SHUTDOWN_RESPONSE` → 等待关闭确认
- `AWAITING_PLAN_APPROVAL` → 等待计划批准
- `WORKING` → 正在执行任务

## 何时用 shutdown 协议

**必须用 shutdown：**
- 关闭持久 teammate 线程
- 清理资源（关闭文件、数据库连接）
- 强制终止失控的 agent

**避免滥用：**
- 不要用来中断正在执行的任务（用 `message` + 取消标志）
- 不要频繁 shutdown/restart（开销大）

## TeamProtocols 方法

| 方法 | 返回 | 说明 |
|------|------|------|
| `state(agent)` | ProtocolState | 查询 agent 状态 |
| `request_shutdown(agent)` | dict | 生成关闭请求消息 |
| `handle_shutdown_response(agent, approved, msg?)` | str | 处理响应 |
| `request_plan_approval(agent, summary, detail)` | dict | 生成计划审批请求 |
| `handle_plan_response(id, approved, feedback?)` | str | 处理审批 |
| `get_pending_approvals()` | list[dict] | 获取所有待审批计划 |
