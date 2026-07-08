"""图谱分析服务包 — 拆分自 graph_service.py。

对外仍导出 GraphService 门面，保持 `from packages.ai.graph import GraphService` 可用。
"""

from packages.ai.graph.facade import GraphService

__all__ = ["GraphService"]
