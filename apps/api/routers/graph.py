"""引用图谱 & 引用同步路由
@author Color2333
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from apps.api.deps import cache, get_paper_title, graph_service
from packages.domain.task_tracker import global_tracker
from packages.storage.db import session_scope
from packages.storage.repositories import TopicRepository

router = APIRouter()


# ---------- 引用同步 ----------
# 注意：固定路径必须在 {paper_id} 动态路径之前，否则会被错误匹配


@router.post("/citations/sync/incremental")
def sync_citations_incremental(
    paper_limit: int = Query(default=40, ge=1, le=200),
    edge_limit_per_paper: int = Query(default=6, ge=1, le=50),
) -> dict:
    """增量同步引用（后台执行）"""

    def _fn(progress_callback=None):
        if progress_callback:
            progress_callback("正在同步增量引用...", 20, 100)
        result = graph_service.sync_incremental(
            paper_limit=paper_limit,
            edge_limit_per_paper=edge_limit_per_paper,
        )
        if progress_callback:
            progress_callback("增量引用同步完成", 90, 100)
        return result

    task_id = global_tracker.submit("citation_sync", "📊 增量引用同步", _fn, category="sync")
    return {"task_id": task_id, "message": "增量引用同步已启动", "status": "running"}


@router.post("/citations/sync/topic/{topic_id}")
def sync_citations_for_topic(
    topic_id: str,
    paper_limit: int = Query(default=30, ge=1, le=200),
    edge_limit_per_paper: int = Query(default=6, ge=1, le=50),
) -> dict:
    """主题引用同步（后台执行）"""
    topic_name = topic_id
    try:
        with session_scope() as session:
            topic = TopicRepository(session).get_by_id(topic_id)
            if topic:
                topic_name = topic.name
    except Exception:
        pass

    def _fn(progress_callback=None):
        if progress_callback:
            progress_callback("正在同步主题引用...", 20, 100)
        result = graph_service.sync_citations_for_topic(
            topic_id=topic_id,
            paper_limit=paper_limit,
            edge_limit_per_paper=edge_limit_per_paper,
        )
        if progress_callback:
            progress_callback("主题引用同步完成", 90, 100)
        return result

    task_id = global_tracker.submit(
        "citation_sync", f"📊 主题引用同步：{topic_name}", _fn, category="sync"
    )
    return {"task_id": task_id, "message": f"主题引用同步已启动: {topic_name}", "status": "running"}


@router.post("/citations/sync/{paper_id}")
def sync_citations(
    paper_id: str,
    limit: int = Query(default=8, ge=1, le=50),
) -> dict:
    """单篇论文引用同步（后台执行）"""
    paper_title = get_paper_title(UUID(paper_id)) or paper_id[:8]

    def _fn(progress_callback=None):
        if progress_callback:
            progress_callback("正在同步论文引用...", 20, 100)
        result = graph_service.sync_citations_for_paper(paper_id=paper_id, limit=limit)
        if progress_callback:
            progress_callback("论文引用同步完成", 90, 100)
        return result

    task_id = global_tracker.submit(
        "citation_sync", f"📄 引用同步：{paper_title[:30]}", _fn, category="sync"
    )
    return {"task_id": task_id, "message": "论文引用同步已启动", "status": "running"}


# ---------- 图谱 ----------


@router.get("/graph/similarity-map")
async def similarity_map(
    topic_id: str | None = None,
    limit: int = Query(default=200, ge=5, le=500),
) -> dict:
    """论文相似度 2D 散点图（UMAP 降维，60s 缓存，线程池执行避免阻塞事件循环）"""
    cache_key = f"graph_similarity_map_{topic_id}_{limit}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    result = await run_in_threadpool(graph_service.similarity_map, topic_id=topic_id, limit=limit)
    cache.set(cache_key, result, ttl=60)
    return result


@router.get("/graph/cluster-map")
async def cluster_map(
    n_clusters: int = Query(default=12, ge=2, le=30),
    limit: int = Query(default=5000, ge=10, le=20000),
) -> dict:
    """全库论文 embedding k-means 聚类（研究领域地图，60s 缓存，线程池执行）"""
    cache_key = f"graph_cluster_map_{n_clusters}_{limit}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    result = await run_in_threadpool(graph_service.cluster_map, n_clusters=n_clusters, limit=limit)
    cache.set(cache_key, result, ttl=60)
    return result


@router.get("/graph/similar-via-citation/{paper_id}")
async def similar_via_citation(
    paper_id: UUID,
    top_k: int = Query(default=5, ge=1, le=20),
) -> dict:
    """引用同一篇论文且语义相近的论文（co-citation + 向量补强）"""
    try:
        return await run_in_threadpool(
            graph_service.similar_via_citation, paper_id=str(paper_id), top_k=top_k
        )
    except ValueError as exc:
        # get_by_id 在论文不存在时抛 ValueError，统一转 404（此前返回 500）
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/graph/citation-tree/{paper_id}")
async def citation_tree(
    paper_id: str,
    depth: int = Query(default=2, ge=1, le=5),
) -> dict:
    """引用树 BFS（60s 缓存，线程池执行避免阻塞事件循环）"""
    cache_key = f"graph_citation_tree_{paper_id}_{depth}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    result = await run_in_threadpool(
        graph_service.citation_tree, root_paper_id=paper_id, depth=depth
    )
    cache.set(cache_key, result, ttl=60)
    return result


@router.get("/graph/citation-detail/{paper_id}")
def citation_detail(paper_id: str) -> dict:
    """获取单篇论文的丰富引用详情（含参考文献和被引列表，含外部 API 副作用，不缓存）"""
    return graph_service.citation_detail(paper_id=paper_id)


@router.get("/graph/citation-network/topic/{topic_id}")
async def topic_citation_network(topic_id: str) -> dict:
    """获取主题内论文的互引网络（60s 缓存，线程池执行）"""
    cache_key = f"graph_topic_citation_network_{topic_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    result = await run_in_threadpool(graph_service.topic_citation_network, topic_id=topic_id)
    cache.set(cache_key, result, ttl=60)
    return result


@router.post("/graph/citation-network/topic/{topic_id}/deep-trace")
def topic_deep_trace(topic_id: str) -> dict:
    """对主题内论文执行深度溯源，拉取外部引用并进行共引分析（含外部 API 副作用，不缓存）"""
    return graph_service.topic_deep_trace(topic_id=topic_id)


@router.get("/graph/overview")
async def graph_overview() -> dict:
    """全库引用概览 — 节点 + 边 + PageRank + 统计（60s 缓存，线程池执行）"""
    cached = cache.get("graph_overview")
    if cached is not None:
        return cached
    result = await run_in_threadpool(graph_service.library_overview)
    cache.set("graph_overview", result, ttl=60)
    return result


@router.get("/graph/bridges")
async def graph_bridges() -> dict:
    """跨主题桥接论文（60s 缓存，线程池执行）"""
    cached = cache.get("graph_bridges")
    if cached is not None:
        return cached
    result = await run_in_threadpool(graph_service.cross_topic_bridges)
    cache.set("graph_bridges", result, ttl=60)
    return result


@router.get("/graph/frontier")
async def graph_frontier(
    days: int = Query(default=90, ge=7, le=365),
) -> dict:
    """研究前沿检测（60s 缓存，线程池执行）"""
    cache_key = f"graph_frontier_{days}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    result = await run_in_threadpool(graph_service.research_frontier, days=days)
    cache.set(cache_key, result, ttl=60)
    return result


@router.get("/graph/cocitation-clusters")
async def graph_cocitation_clusters(
    min_cocite: int = Query(default=2, ge=1, le=10),
) -> dict:
    """共引聚类分析 O(N²) 配对（300s 缓存，线程池执行）"""
    cache_key = f"graph_cocitation_clusters_{min_cocite}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    result = await run_in_threadpool(graph_service.cocitation_clusters, min_cocite=min_cocite)
    cache.set(cache_key, result, ttl=300)
    return result


@router.post("/graph/auto-link")
def graph_auto_link(paper_ids: list[str]) -> dict:
    """手动触发引用自动关联（含外部 API 副作用，不缓存）"""
    return graph_service.auto_link_citations(paper_ids)


@router.get("/graph/timeline")
async def graph_timeline(
    keyword: str,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    """领域时间线 PageRank（120s 缓存，线程池执行）"""
    cache_key = f"graph_timeline_{keyword}_{limit}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    result = await run_in_threadpool(graph_service.timeline, keyword=keyword, limit=limit)
    cache.set(cache_key, result, ttl=120)
    return result


@router.get("/graph/quality")
async def graph_quality(
    keyword: str,
    limit: int = Query(default=120, ge=1, le=500),
) -> dict:
    """图谱质量指标（120s 缓存，线程池执行）"""
    cache_key = f"graph_quality_{keyword}_{limit}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    result = await run_in_threadpool(graph_service.quality_metrics, keyword=keyword, limit=limit)
    cache.set(cache_key, result, ttl=120)
    return result


@router.get("/graph/evolution/weekly")
async def graph_weekly_evolution(
    keyword: str,
    limit: int = Query(default=160, ge=1, le=500),
) -> dict:
    """周演化（含 LLM，300s 缓存，线程池执行）"""
    cache_key = f"graph_weekly_evolution_{keyword}_{limit}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    result = await run_in_threadpool(graph_service.weekly_evolution, keyword=keyword, limit=limit)
    cache.set(cache_key, result, ttl=300)
    return result


@router.get("/graph/survey")
async def graph_survey(
    keyword: str,
    limit: int = Query(default=120, ge=1, le=500),
) -> dict:
    """领域综述（含 LLM，300s 缓存，线程池执行）"""
    cache_key = f"graph_survey_{keyword}_{limit}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    result = await run_in_threadpool(graph_service.survey, keyword=keyword, limit=limit)
    cache.set(cache_key, result, ttl=300)
    return result


@router.get("/graph/research-gaps")
async def graph_research_gaps(
    keyword: str,
    limit: int = Query(default=120, ge=1, le=500),
) -> dict:
    """研究空白检测（含 2×timeline + 2×LLM，最重图谱端点，600s 缓存，线程池执行）"""
    cache_key = f"graph_research_gaps_{keyword}_{limit}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    result = await run_in_threadpool(
        graph_service.detect_research_gaps, keyword=keyword, limit=limit
    )
    cache.set(cache_key, result, ttl=600)
    return result
