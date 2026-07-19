"""LangGraph agent harness PoC.

与现有自研 StreamingAgentLoop（packages/agent_core/loop.py）并行，
经 /agent/v2/* 路由暴露。PoC 不合入 main，拍板替换后再删老 loop。

核心组件：
- chat_model.py: PaperMindChatModel 包装现有 LLMClient.chat_stream
- tools_adapter.py: 现有 ToolDef → langchain StructuredTool
- state.py + graph.py: StateGraph ReAct + interrupt 复刻 confirm
- checkpointer.py: PostgresSaver 单例（thread_id = conversation_id）
- sse_adapter.py: LangGraph stream → 现有 9 种 SSE 事件
- entry.py: stream_chat_v2 / confirm_v2 / reject_v2

@author Color2333
"""
