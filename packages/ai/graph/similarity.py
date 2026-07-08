"""论文 embedding 相似度降维服务。"""

from __future__ import annotations

import logging

from packages.storage.db import session_scope
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
