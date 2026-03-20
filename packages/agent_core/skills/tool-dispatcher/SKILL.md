---
name: tool-dispatcher
description: |
  工具注册与分发机制。使用此 skill 当你需要：
  - 注册新的 tool handler
  - 理解工具定义（tools list）和工具执行（handlers dict）的分离
  - 使用 make_default_dispatcher 快速创建默认工具集
---

# Tool Dispatcher — 工具注册与分发

## 核心原则（s02 Motto）

> **"Adding a tool means adding one handler"**

Loop 本身不变。加工具 = 加一个 handler 到 dispatch map。

## 核心架构

```
Anthropic tools list（给 LLM 看）
    ↓
LLM 决定调用 "bash"
    ↓
ToolDispatcher.handlers["bash"] → run_bash()
    ↓
执行并返回结果
```

**工具定义**（tools list）和**工具处理**（handlers dict）是两回事：
- `tools list` → 告诉 LLM 有哪些工具可用（Anthropic API 格式）
- `handlers dict` → 实际执行逻辑

## 注册一个工具

```python
from agent_core import ToolDispatcher

dispatcher = ToolDispatcher()

def my_tool(arg1: str, arg2: int = 10) -> str:
    return f"{arg1}: {arg2}"

dispatcher.register(
    name="my_tool",          # LLM 调用时用的名称
    handler=my_tool,         # 实际执行的函数
)
```

`register()` 会自动：
1. 从 handler docstring 提取描述
2. 从 handler 签名推断 input_schema
3. 注册到 handlers dict
4. 追加到 tools list

## 手动指定 schema

如果自动推断不满足需求，可以手动传：

```python
dispatcher.register(
    name="search",
    handler=search_handler,
    description="Search the web for information",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "num_results": {"type": "integer", "default": 5},
        },
        "required": ["query"],
    },
)
```

## 批量注册

```python
from agent_core.tools.bash import run_bash
from agent_core.tools.filesystem import run_read, run_write, run_edit

dispatcher.register_many({
    "bash": run_bash,
    "read_file": run_read,
    "write_file": run_write,
    "edit_file": run_edit,
})
```

## 默认工具集

一行创建常用工具：

```python
from agent_core import make_default_dispatcher

# 只包含基础工具
dispatcher = make_default_dispatcher(workdir="/path/to/project")

# 包含基础工具 + tasks
dispatcher = make_default_dispatcher(
    workdir="/path/to/project",
    tasks_dir="/path/to/.tasks",
)
```

默认包含：`bash`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`

## 常用工具 handler

| 工具名 | handler | 作用 |
|--------|---------|------|
| `bash` | `run_bash(command)` | 执行 shell 命令 |
| `read_file` | `run_read(path, limit?)` | 读文件 |
| `write_file` | `run_write(path, content)` | 写文件（覆盖） |
| `edit_file` | `run_edit(path, old, new)` | 替换文件内容 |
| `glob` | `run_glob(pattern)` | glob 搜索 |
| `grep` | `run_grep(pattern, include?)` | 内容搜索 |
| `task_create` | `task_manager.create(subject, description)` | 创建任务 |
| `task_list` | `task_manager.list_all()` | 列出任务 |

## dispatch() 行为

```python
output = dispatcher.dispatch("bash", command="ls -la")
# 成功 → 返回命令输出字符串
# 未知工具 → "Error: Unknown tool 'bash'. Available: [...]"
# 参数错误 → "Error: Tool 'bash' received wrong arguments..."
# 执行异常 → "Error: Tool 'bash' failed: TimeoutError: ..."
```

## 何时注册工具

注册越早越好（freeze 后不能注册）：

```python
dispatcher = ToolDispatcher()
dispatcher.register("bash", run_bash)
dispatcher.register("read_file", run_read)
# ... 更多工具 ...

# 第一次调用 get_tool_definitions() 后 frozen
tools = dispatcher.get_tool_definitions()  # ← freeze

dispatcher.register("new_tool", handler)  # RuntimeError!
```

正确做法：在 `get_tool_definitions()` 之前注册所有工具。
