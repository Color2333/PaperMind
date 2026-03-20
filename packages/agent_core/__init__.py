"""
agent_core — Agent Harness 工程核心库

参考 learn-claude-code (https://github.com/shareAI-lab/learn-claude-code)
s01-s12 渐进式 harness 机制 Python 实现。

主要模块：
- loop.py       : AgentLoop，显式 agent 循环
- dispatcher.py : ToolDispatcher，工具注册与分发
- tasks.py      : TaskManager，任务持久化 + 依赖图
- message_bus.py : MessageBus，team 异步通信
- teammates.py   : TeammateManager，持久 agent 线程管理
- protocols.py   : TeamProtocols，shutdown/plan_approval FSM
- background.py  : BackgroundTaskRunner，daemon 线程池
"""

from .background import BackgroundTask, BackgroundTaskRunner
from .dispatcher import ToolDispatcher, make_default_dispatcher
from .loop import AgentConfig, AgentLoop, AgentResponse, StopReason
from .message_bus import MessageBus
from .protocols import ProtocolState, TeamProtocols
from .tasks import Task, TaskManager
from .teammates import TeammateManager

__all__ = [
    "AgentLoop",
    "AgentConfig",
    "AgentResponse",
    "StopReason",
    "ToolDispatcher",
    "make_default_dispatcher",
    "TaskManager",
    "Task",
    "MessageBus",
    "TeammateManager",
    "TeamProtocols",
    "ProtocolState",
    "BackgroundTaskRunner",
    "BackgroundTask",
]
