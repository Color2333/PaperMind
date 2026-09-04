"""Pi 引擎桥（packages/agent_pi）：Web 聊天的 Pi agent 接入层。

Pi（PaperMind-Terminal 的 pm）是 agent 循环与 LLM 网关的唯一实现；
本包只做子进程编排与事件翻译，不持有任何 LLM 协议细节。

@author Color2333
"""

from packages.agent_pi.host import (
    PiEngineUnavailable,
    materialize_model_config,
    pi_chat_stream,
    pi_engine_available,
    session_file_for,
    web_agent_dir,
)

__all__ = [
    "PiEngineUnavailable",
    "materialize_model_config",
    "pi_chat_stream",
    "pi_engine_available",
    "session_file_for",
    "web_agent_dir",
]
