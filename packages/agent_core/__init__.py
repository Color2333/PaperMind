"""
agent_core — Agent Harness 工程核心库

参考 learn-claude-code (https://github.com/shareAI-lab/learn-claude-code)
s01-s12 渐进式 harness 机制 Python 实现。

主要模块：
- loop.py       : StreamingAgentLoop，流式 agent 循环 + 确认机制
- dispatcher.py : ToolDispatcher，工具注册与分发
- tasks.py      : TaskManager，任务持久化 + 依赖图
"""

from .dispatcher import ToolDispatcher, make_default_dispatcher
from .tasks import Task, TaskManager

__all__ = [
    "ToolDispatcher",
    "make_default_dispatcher",
    "TaskManager",
    "Task",
]
