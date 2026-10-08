"""图谱只读查询（B6/B7，设计② GetGraph* 查询族；纯读快照）

facade 单例经 lru_cache 持有（构造轻量但非零，摊平请求成本）；
缓存与线程池调度属于传输层，留在 router。
"""

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def _graph_service():
    from packages.ai.graph_service import GraphService

    return GraphService()


def get_citation_tree(*, paper_id: str, depth: int = 2) -> dict:
    return _graph_service().citation_tree(root_paper_id=paper_id, depth=depth)


def get_timeline(*, keyword: str, limit: int = 100) -> dict:
    return _graph_service().timeline(keyword=keyword, limit=limit)


# ---------- B7：HTTP 图谱 GET 查询族 ----------


def similarity_map(*, topic_id: str | None = None, limit: int = 200) -> dict:
    return _graph_service().similarity_map(topic_id=topic_id, limit=limit)


def cluster_map(*, n_clusters: int = 12, limit: int = 5000, papers_per_cluster: int = 5) -> dict:
    return _graph_service().cluster_map(
        n_clusters=n_clusters, limit=limit, papers_per_cluster=papers_per_cluster
    )


def similar_via_citation(*, paper_id: str, top_k: int = 5) -> dict:
    return _graph_service().similar_via_citation(paper_id=paper_id, top_k=top_k)


def citation_detail(*, paper_id: str) -> dict:
    return _graph_service().citation_detail(paper_id=paper_id)


def topic_citation_network(*, topic_id: str) -> dict:
    return _graph_service().topic_citation_network(topic_id=topic_id)


def library_overview() -> dict:
    return _graph_service().library_overview()


def cross_topic_bridges() -> dict:
    return _graph_service().cross_topic_bridges()


def research_frontier(*, days: int = 90) -> dict:
    return _graph_service().research_frontier(days=days)


def cocitation_clusters(*, min_cocite: int = 2) -> dict:
    return _graph_service().cocitation_clusters(min_cocite=min_cocite)


def quality_metrics(*, keyword: str, limit: int = 120) -> dict:
    return _graph_service().quality_metrics(keyword=keyword, limit=limit)


def weekly_evolution(*, keyword: str, limit: int = 160) -> dict:
    return _graph_service().weekly_evolution(keyword=keyword, limit=limit)


def survey(*, keyword: str, limit: int = 120) -> dict:
    return _graph_service().survey(keyword=keyword, limit=limit)
