"""论文 embedding 相似度降维服务。"""

from __future__ import annotations

import logging
from collections import Counter

from sqlalchemy import select as _sa_select

from packages.ai.recommendation_service import _kmeans
from packages.storage.db import session_scope
from packages.storage.models import Citation, Paper
from packages.storage.repositories import PaperRepository

logger = logging.getLogger(__name__)


class SimilarityService:
    def __init__(self) -> None:
        pass

    def similarity_map(
        self,
        topic_id: str | None = None,
        limit: int = 200,
    ) -> dict:
        """用 UMAP 将论文 embedding 降维到 2D，返回散点图数据"""
        import numpy as np

        with session_scope() as session:
            repo = PaperRepository(session)
            papers = repo.list_with_embedding(topic_id=topic_id, limit=limit)
            if len(papers) < 5:
                return {"points": [], "message": "论文数量不足（至少需要 5 篇有向量的论文）"}

            topic_map = repo.get_topic_names_for_papers([str(p.id) for p in papers])

            # 提取 embedding 矩阵
            dim = len(papers[0].embedding)
            vectors = []
            valid_papers = []
            for p in papers:
                if p.embedding and len(p.embedding) == dim:
                    vectors.append(p.embedding)
                    valid_papers.append(p)

            if len(valid_papers) < 5:
                return {"points": [], "message": "有效向量不足"}

            mat = np.array(vectors, dtype=np.float64)

            # UMAP 降维
            try:
                from umap import UMAP

                n_neighbors = min(15, len(valid_papers) - 1)
                reducer = UMAP(
                    n_components=2, random_state=42, n_neighbors=n_neighbors, min_dist=0.1
                )
                coords = reducer.fit_transform(mat)
            except Exception as exc:
                logger.warning("UMAP failed: %s, falling back to PCA", exc)
                from sklearn.decomposition import PCA

                coords = PCA(n_components=2, random_state=42).fit_transform(mat)

            points = []
            for i, p in enumerate(valid_papers):
                meta = p.metadata_json or {}
                topics = topic_map.get(str(p.id), [])
                points.append(
                    {
                        "id": str(p.id),
                        "title": p.title,
                        "x": float(coords[i][0]),
                        "y": float(coords[i][1]),
                        "year": p.publication_date.year if p.publication_date else None,
                        "read_status": p.read_status.value if p.read_status else "unread",
                        "topics": topics,
                        "topic": topics[0] if topics else "未分类",
                        "arxiv_id": p.arxiv_id,
                        "title_zh": meta.get("title_zh", ""),
                    }
                )

        return {"points": points, "total": len(points)}

    def cluster_map(self, n_clusters: int = 12, limit: int = 5000) -> dict:
        """全库 embedding k-means 聚类，每簇用 skim keywords 自动命名。

        返回研究领域地图：每个簇一个名称（取簇内论文 keywords 频率 top 3）+
        论文 id 列表 + 簇大小。前端可可视化展示"研究领域地图"。

        复用 recommendation_service._kmeans（加权 k-means，这里权重全部为 1.0，
        即不加权，纯空间聚类）。
        """
        with session_scope() as session:
            repo = PaperRepository(session)
            papers = repo.list_with_embedding(limit=limit)
            if len(papers) < n_clusters:
                return {
                    "clusters": [],
                    "message": f"论文数量不足（{len(papers)} < {n_clusters} 簇）",
                }

            dim = len(papers[0].embedding)
            vectors = []
            valid_papers = []
            for p in papers:
                if p.embedding and len(p.embedding) == dim:
                    vectors.append(list(p.embedding))
                    valid_papers.append(p)

            if len(valid_papers) < n_clusters:
                return {"clusters": [], "message": "有效向量不足"}

            # k-means 聚类（权重 1.0，不加权）
            weighted = [(v, 1.0) for v in vectors]
            centroids = _kmeans(weighted, n_clusters)

            if not centroids:
                return {"clusters": [], "message": "聚类失败"}

            # 分配每篇论文到最近质心（cosine 相似度最大）
            from packages.domain.math_utils import cosine_similarity as _cosine_sim

            cluster_buckets: dict[int, list] = {i: [] for i in range(len(centroids))}
            cluster_keywords: dict[int, list[str]] = {i: [] for i in range(len(centroids))}
            for p, vec in zip(valid_papers, vectors):
                best_c = 0
                best_sim = -2.0
                for ci, centroid in enumerate(centroids):
                    sim = _cosine_sim(vec, centroid)
                    if sim > best_sim:
                        best_sim = sim
                        best_c = ci
                meta = p.metadata_json or {}
                cluster_buckets[best_c].append(
                    {
                        "id": str(p.id),
                        "title": p.title,
                        "arxiv_id": p.arxiv_id,
                        "title_zh": meta.get("title_zh", ""),
                    }
                )
                cluster_keywords[best_c].extend(meta.get("keywords", []))

            # 每簇用 keywords 频率 top 3 作簇名
            clusters = []
            for ci in range(len(centroids)):
                kws = cluster_keywords[ci]
                top_kws = [kw for kw, _ in Counter(kws).most_common(3)] if kws else []
                clusters.append(
                    {
                        "cluster_id": ci,
                        "name": " / ".join(top_kws) if top_kws else f"簇 {ci + 1}",
                        "keywords": top_kws,
                        "size": len(cluster_buckets[ci]),
                        "papers": cluster_buckets[ci][:50],  # 每簇最多返回 50 篇，避免过大
                    }
                )

            # 按簇大小降序
            clusters.sort(key=lambda c: c["size"], reverse=True)

        return {
            "clusters": clusters,
            "total_clusters": len(clusters),
            "total_papers": len(valid_papers),
        }

    def similar_via_citation(self, paper_id: str, top_k: int = 5) -> dict:
        """引用同一篇论文且语义相近的论文（co-citation + 向量补强）。

        逻辑：
        1. 取 paper 引用 / 被引的论文集合 cited（Citation 表双向）
        2. 找也引用了 cited 中任一篇的论文（co-citation 集合）
        3. 在 co-citation 集合里用 embedding cosine 排序 top_k

        纯引用图谱只看显式连边，结合 embedding 可在"结构相邻"里再按"语义相近"排序，
        比单一信号更准。
        """
        from packages.domain.math_utils import cosine_similarity as _cosine_sim

        with session_scope() as session:
            repo = PaperRepository(session)
            seed = repo.get_by_id(paper_id)
            if not seed:
                return {"paper_id": str(paper_id), "items": [], "note": "论文不存在"}
            if not seed.embedding:
                return {
                    "paper_id": str(paper_id),
                    "items": [],
                    "note": "种子论文无 embedding，请先 embed",
                }
            seed_vec = list(seed.embedding)

            # 1. 取种子论文引用 / 被引的论文（双向）
            cited_rows = (
                session.execute(
                    _sa_select(Citation).where(
                        (Citation.source_paper_id == str(paper_id))
                        | (Citation.target_paper_id == str(paper_id))
                    )
                )
                .scalars()
                .all()
            )
            cited_ids = set()
            for c in cited_rows:
                if c.source_paper_id != str(paper_id):
                    cited_ids.add(c.source_paper_id)
                if c.target_paper_id != str(paper_id):
                    cited_ids.add(c.target_paper_id)
            if not cited_ids:
                return {"paper_id": str(paper_id), "items": [], "note": "无引用关系"}

            # 2. 找也引用了 cited 中任一篇的论文（co-citation）
            co_cite_rows = (
                session.execute(
                    _sa_select(Citation).where(
                        Citation.source_paper_id.in_(list(cited_ids))
                        | Citation.target_paper_id.in_(list(cited_ids))
                    )
                )
                .scalars()
                .all()
            )
            co_cite_ids = set()
            for c in co_cite_rows:
                co_cite_ids.add(c.source_paper_id)
                co_cite_ids.add(c.target_paper_id)
            # 排除种子 + 已在 cited 里的
            co_cite_ids.discard(str(paper_id))
            co_cite_ids -= cited_ids
            if not co_cite_ids:
                return {"paper_id": str(paper_id), "items": [], "note": "无 co-citation 候选"}

            # 3. 在 co-citation 集合里按 embedding cosine 排序
            candidates = (
                session.execute(
                    _sa_select(Paper).where(
                        Paper.id.in_(list(co_cite_ids)),
                        Paper.embedding.is_not(None),
                    )
                )
                .scalars()
                .all()
            )
            scored = []
            for p in candidates:
                if not p.embedding or len(p.embedding) != len(seed_vec):
                    continue
                sim = _cosine_sim(seed_vec, list(p.embedding))
                scored.append(
                    {
                        "id": str(p.id),
                        "title": p.title,
                        "arxiv_id": p.arxiv_id,
                        "similarity": round(sim, 4),
                    }
                )
            scored.sort(key=lambda x: x["similarity"], reverse=True)

        return {"paper_id": str(paper_id), "items": scored[:top_k], "count": len(scored)}
