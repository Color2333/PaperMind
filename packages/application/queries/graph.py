"""图谱只读查询（B6，设计② GetGraph* 查询族的第一批）"""

from __future__ import annotations


def get_citation_tree(*, paper_id: str, depth: int = 2) -> dict:
    from packages.ai.graph_service import GraphService

    return GraphService().citation_tree(root_paper_id=paper_id, depth=depth)


def get_timeline(*, keyword: str, limit: int = 100) -> dict:
    from packages.ai.graph_service import GraphService

    return GraphService().timeline(keyword=keyword, limit=limit)


def get_paper_wiki(*, paper_id: str) -> dict:
    from packages.ai.graph_service import GraphService

    return GraphService().paper_wiki(paper_id=paper_id)


def get_topic_wiki(*, keyword: str, limit: int = 120, progress_callback=None) -> dict:
    from packages.ai.graph_service import GraphService

    return GraphService().topic_wiki(
        keyword=keyword, limit=limit, progress_callback=progress_callback
    )


def detect_research_gaps(*, keyword: str, limit: int = 100) -> dict:
    from packages.ai.graph_service import GraphService

    return GraphService().detect_research_gaps(keyword=keyword, limit=limit)
