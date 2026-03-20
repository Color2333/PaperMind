---
name: context-compaction
description: |
  3层 Context 压缩策略，支持无限长度会话。
  使用此 skill 当你需要：
  - 理解 Context 压缩的原理
  - 实现消息历史摘要
  - 处理超长对话导致 context overflow
---

# Context Compaction — 3层压缩策略

## 问题

每轮对话 messages[] 都在增长。几轮之后 context 就满了。
解决思路：不是截断，是**压缩**。

## 3层压缩策略（s06）

### Layer 1：消息摘要（Message Summarization）

定期把多轮对话压缩成一条摘要消息：

```
# 原始（10轮对话，~8000 tokens）
messages = [
  {"role": "user", "content": "添加用户认证"},
  {"role": "assistant", "content": "我帮你..."},
  {"role": "user", "content": "再加个注册"},
  {"role": "assistant", "content": "好的..."},
  ... 10轮
]

# Layer 1 压缩后
messages = [
  {"role": "user", "content": "添加用户认证 + 注册功能"},  ← 摘要
  {"role": "assistant", "content": "完成了，代码已提交"},
]
```

**触发条件**：messages 总长度 > 50% max_tokens

### Layer 2：关键决策提取（Key Decisions）

只保留重要的架构决策、操作结果、文件路径，丢弃探索过程：

```python
COMPRESSED = """
=== 项目状态 ===
- 完成了用户认证（JWT）
- 添加了 /auth/login 和 /auth/register 端点
- 使用了 PyJWT 库
- 数据库迁移：users 表

=== 关键文件 ===
- apps/api/routers/auth.py
- apps/api/models/user.py

=== 当前进行中 ===
实现论文搜索 API
"""
```

### Layer 3：元信息压缩（Metadata）

把完整消息压缩成结构化元信息：

```python
{
  "type": "compressed_history",
  "summary": "完成用户认证，添加登录注册API，使用PyJWT",
  "decisions": ["使用JWT而非session", "密码用bcrypt哈希"],
  "files_touched": ["auth.py", "user.py", "models.py"],
  "active_task": "实现论文搜索API",
  "next_step": "添加 arxiv_id 字段到 papers 表",
}
```

## 何时压缩

| 信号 | 动作 |
|------|------|
| messages 长度 > 50% max_tokens | Layer 1 |
| 单轮工具调用 > 20 次 | Layer 2 |
| 会话超过 2 小时 | Layer 2 |
| 历史消息全部是工具调用 | Layer 3 |

## 压缩实现伪代码

```python
def should_compact(messages, max_tokens):
    total = sum_tokens(messages)
    return total > max_tokens * 0.5

def compact(messages, strategy="auto"):
    if strategy == "auto":
        if len(messages) > 20:
            return layer3_compress(messages)
        elif total_tools > 20:
            return layer2_compress(messages)
        else:
            return layer1_summarize(messages)
```

## 与 AgentLoop 集成

```python
class CompactingAgentLoop(AgentLoop):
    def __init__(self, config, dispatcher, compact_threshold=0.5):
        super().__init__(config, dispatcher)
        self.compact_threshold = compact_threshold

    def run(self, messages):
        result = super().run(messages)
        if self._should_compact(messages):
            messages[:] = self._compact(messages)
        return result
```

## 实际经验

- **不要过度压缩**：保留关键上下文（当前任务、目标文件、已确定方案）
- **优先 Layer 1**：摘要比元信息更可靠
- **记录压缩历史**：方便回溯
- **LLM 辅助压缩**：让 LLM 自己写摘要（用工具调用一次）
