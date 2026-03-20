---
name: agent-loop
description: |
  AgentLoop 是整个 Agent Harness 的心脏。使用此 skill 当你需要：
  - 构建新的 Agent 系统
  - 理解 Model + Harness 的关系
  - 使用 chat() 快捷函数进行单轮对话
---

# Agent Loop — 理解 Model + Harness 的关系

## 核心真理

> **"The model IS the agent. The code is the harness."**

- Model（Claude/GPT）：决定何时调用工具，何时停止
- Harness（我们的代码）：执行工具、收集结果、注入回 context

两者各司其职，不能互相替代。

## 循环模式（s01 核心）

```
while stop_reason == "tool_use":
    response = LLM(messages, tools)
    execute each tool call
    append results to messages
```

这就是 agent loop 的全部。Model 决定何时调用工具，我们执行工具。

## AgentLoop 使用方式

```python
from agent_core import AgentConfig, ToolDispatcher, AgentLoop
from agent_core.tools.bash import run_bash
from agent_core.tools.filesystem import run_read, run_write, run_edit

config = AgentConfig(
    model="claude-sonnet-4-20250514",
    system_prompt="You are a coding agent at /path/to/project.",
)

dispatcher = ToolDispatcher()
dispatcher.register("bash", run_bash)
dispatcher.register("read_file", run_read)
dispatcher.register("write_file", run_write)
dispatcher.register("edit_file", run_edit)

loop = AgentLoop(config, dispatcher)
messages = [{"role": "user", "content": "帮我添加用户认证功能"}]
response = loop.run(messages)

print(response.text)           # 最终文本回复
print(response.stop_reason)    # 为什么停止
print(response.tool_results)   # 所有工具执行结果
```

## 快捷函数：chat()

单轮对话不需要手动创建 loop：

```python
from agent_core import chat

result = chat(
    system_prompt="You are a helpful coding assistant.",
    user_message="What files were modified today?",
    model="claude-sonnet-4-20250514",
    tools={
        "bash": run_bash,
        "read_file": run_read,
    }
)
print(result.text)
```

## 何时使用 AgentLoop

**使用：**
- 构建新的 Agent 系统
- 需要细粒度控制 tool dispatch 逻辑
- 需要在 tool 执行前后插入 hook
- 需要访问 `tool_results` 做日志/分析

**不需要：**
- 简单的一次性 LLM 调用 → 直接用 `client.messages.create()`
- 已有框架内置了 loop → 参考这个 skill 理解原理即可

## AgentLoop 类方法

| 方法 | 作用 |
|------|------|
| `loop.run(messages)` | 执行完整循环，返回 AgentResponse |
| `AgentResponse.text` | LLM 最终文本回复 |
| `AgentResponse.stop_reason` | 停止原因（tool_use/end_turn/max_tokens） |
| `AgentResponse.tool_results` | 所有工具执行结果列表 |
| `AgentResponse.raw` | 原始 LLM 响应对象 |

## stop_reason 三种值

| 值 | 含义 | 我们做什么 |
|----|------|-----------|
| `tool_use` | LLM 调用了工具 | 继续循环 |
| `end_turn` | LLM 直接回复用户 | 返回 text |
| `max_tokens` | 达到 token 上限 | 返回已收集结果 |
