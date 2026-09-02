"""图谱只读查询（B6，设计② GetGraph* 查询族的第一批）"""

from __future__ import annotations


def get_citation_tree(*, paper_id: str, depth: int = 2) -> dict:
    from packages.ai.graph_service import GraphService

    return GraphService().citation_tree(root_paper_id=paper_id, depth=depth)


def get_timeline(*, keyword: str, limit: int = 100) -> dict:
    from packages.ai.graph_service import GraphService

    return GraphService().timeline(keyword=keyword, limit=limit)
