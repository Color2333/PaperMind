"""
推荐引擎 + 热点趋势检测
@author Color2333
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from packages.domain.math_utils import cosine_similarity as _cosine_sim
from packages.storage.db import session_scope
from packages.storage.models import PaperTopic, TopicSubscription
from packages.storage.repositories import PaperRepository

logger = logging.getLogger(__name__)

# 简单的 TTL 内存缓存
_ttl_cache: dict[str, tuple[float, object]] = {}
_ttl_lock = threading.Lock()
_DEFAULT_TTL = 300  # 5 分钟


def _cached(key: str, ttl: float = _DEFAULT_TTL):
    """读取缓存，命中返回值，未命中返回 None"""
    with _ttl_lock:
        entry = _ttl_cache.get(key)
        if entry and time.monotonic() - entry[0] < ttl:
            return entry[1]
    return None


def _set_cache(key: str, value: object):
    with _ttl_lock:
        _ttl_cache[key] = (time.monotonic(), value)


def _mean_vector(vectors: list[list[float]]) -> list[float]:
    """计算向量集合的质心（自动过滤维度不一致的向量）"""
    if not vectors:
        return []
    dim = len(vectors[0])
    valid = [v for v in vectors if len(v) == dim]
    if not valid:
        return []
    result = [0.0] * dim
    for v in valid:
        for i in range(dim):
            result[i] += v[i]
    n = len(valid)
    return [x / n for x in result]


def _weighted_mean_vector(
    weighted_vectors: list[tuple[list[float], float]],
) -> list[float]:
    """加权质心：每条向量乘权重后求平均。用于时间衰减。"""
    if not weighted_vectors:
        return []
    dim = len(weighted_vectors[0][0])
    total_w = 0.0
    result = [0.0] * dim
    for vec, w in weighted_vectors:
        if len(vec) != dim:
            continue
        total_w += w
        for i in range(dim):
            result[i] += vec[i] * w
    if total_w == 0:
        return []
    return [x / total_w for x in result]


def _kmeans(
    weighted_vectors: list[tuple[list[float], float]],
    k: int,
    max_iter: int = 10,
) -> list[list[float]]:
    """纯 Python 加权 k-means，返回 k 个质心。

    用于多兴趣聚类：已读论文 embedding 聚成 N 簇（每个兴趣方向一簇），
    每簇质心代表一个兴趣方向。时间衰减权重体现在质心计算里。

    简单实现（避免引入 sklearn 依赖）：
    - 初始质心：随机选 k 个向量（带权重概率）
    - 迭代：每点分到最近质心 → 重新算加权质心 → 收敛或 max_iter 停止
    """
    if not weighted_vectors or k < 1:
        return []
    if k == 1:
        return [_weighted_mean_vector(weighted_vectors)]
    vectors = [v for v, _ in weighted_vectors]
    n = len(vectors)
    k = min(k, n)
    dim = len(vectors[0])

    # 初始质心：随机选 k 个不重复点
    rng = random.Random(42)  # 固定种子保证可复现
    indices = rng.sample(range(n), k)
    centroids = [list(vectors[i]) for i in indices]

    for _ in range(max_iter):
        # 分配：每点分到最近质心（余弦距离，复用 cosine_similarity）
        clusters: list[list[tuple[list[float], float]]] = [[] for _ in range(k)]
        for vec, w in weighted_vectors:
            if len(vec) != dim:
                continue
            best_c = 0
            best_sim = -2.0
            for ci, centroid in enumerate(centroids):
                sim = _cosine_sim(vec, centroid)
                if sim > best_sim:
                    best_sim = sim
                    best_c = ci
            clusters[best_c].append((vec, w))

        # 更新质心：加权平均
        new_centroids = []
        for ci, cluster in enumerate(clusters):
            if cluster:
                new_centroids.append(_weighted_mean_vector(cluster))
            else:
                # 空簇保留旧质心
                new_centroids.append(centroids[ci])

        # 收敛检查（质心几乎不变）
        moved = sum(
            sum((a - b) ** 2 for a, b in zip(new_centroids[i], centroids[i])) for i in range(k)
        )
        centroids = new_centroids
        if moved < 1e-6:
            break

    return centroids


# 时间衰减半衰期（天）：最近 90 天权重高，半年前衰减到 ~0.16
_DECAY_HALFLIFE_DAYS = 90.0
# 主题加权倍数：候选若属于已订阅 topic，相似度乘 1.2
_TOPIC_BOOST = 1.2


class RecommendationService:
    """基于阅读历史 embedding 的个性化推荐（多兴趣 + 时间衰减 + 主题加权）"""

    def get_user_profile(self) -> list[list[float]]:
        """从已读论文（skimmed/deep_read）的 embedding 计算多兴趣质心向量集合。

        返回 list[list[float]] —— 每个质心代表一个兴趣方向（k-means 簇心）。
        向后兼容：调用方按 list[centroid] 处理；单簇时退化为旧的单质心。
        """
        with session_scope() as session:
            repo = PaperRepository(session)
            read_papers = repo.list_by_read_status_with_embedding(
                statuses=["skimmed", "deep_read"], limit=500
            )
            now = datetime.now(UTC)
            weighted_vectors = []
            for p in read_papers:
                if not p.embedding or not p.created_at:
                    continue
                # PG timestamp without time zone 返回 naive datetime，统一转 UTC
                created = p.created_at
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
                age_days = (now - created).total_seconds() / 86400
                # 指数衰减：weight = 0.5 ^ (age / halflife)
                weight = 0.5 ** (age_days / _DECAY_HALFLIFE_DAYS)
                weighted_vectors.append((list(p.embedding), weight))

        if not weighted_vectors:
            return []

        # k 自适应：已读论文多则多兴趣，少则单质心
        n = len(weighted_vectors)
        k = max(1, min(3, n // 5))
        centroids = _kmeans(weighted_vectors, k)
        return [c for c in centroids if c]

    def recommend(self, top_k: int = 10) -> list[dict]:
        """推荐与用户兴趣最匹配的未读论文。

        策略升级（替代旧的单质心）：
        1. 多兴趣：已读论文 k-means 聚成 N 簇，每簇一个兴趣质心
        2. 时间衰减：最近读的论文权重高（90 天半衰期），远的衰减
        3. 主题加权：候选若属于已订阅 topic，相似度乘 1.2
        4. 负反馈：候选查询已排除 rejected 论文（见 list_unread_with_embedding）
        5. 多兴趣命中：候选对每个质心算相似度取 max（命中任一兴趣即可）
        """
        cache_key = f"recommend:{top_k}"
        hit = _cached(cache_key)
        if hit is not None:
            return hit

        profiles = self.get_user_profile()
        if not profiles:
            return []

        # 在 session 内提取候选 + 订阅主题
        with session_scope() as session:
            repo = PaperRepository(session)
            unread = repo.list_unread_with_embedding(limit=500)
            candidates = []
            for p in unread:
                if not p.embedding:
                    continue
                meta = p.metadata_json or {}
                candidates.append(
                    {
                        "embedding": list(p.embedding),
                        "id": str(p.id),
                        "title": p.title,
                        "arxiv_id": p.arxiv_id,
                        "abstract": (p.abstract or "")[:300],
                        "publication_date": (
                            str(p.publication_date) if p.publication_date else None
                        ),
                        "keywords": meta.get("keywords", []),
                        "categories": meta.get("categories", []),
                        "title_zh": meta.get("title_zh", ""),
                    }
                )

            # 取用户已订阅的 topic_id 集合，用于主题加权
            subscribed_topic_ids = {
                str(row[0])
                for row in session.execute(
                    select(TopicSubscription.id).where(TopicSubscription.enabled.is_(True))
                ).all()
            }
            # 候选论文属于哪些已订阅 topic（PaperTopic 关联）
            if candidates and subscribed_topic_ids:
                cand_ids = [c["id"] for c in candidates]
                rows = session.execute(
                    select(PaperTopic.paper_id, PaperTopic.topic_id).where(
                        PaperTopic.paper_id.in_(cand_ids),
                        PaperTopic.topic_id.in_(list(subscribed_topic_ids)),
                    )
                ).all()
                topic_boost_ids = {str(r[0]) for r in rows}
            else:
                topic_boost_ids = set()

        scored: list[tuple[float, dict]] = []
        for c in candidates:
            emb = c.pop("embedding")
            if not emb:
                continue
            # 多兴趣命中：取所有质心相似度的最大值
            sims = [_cosine_sim(profile, emb) for profile in profiles if len(emb) == len(profile)]
            if not sims:
                continue
            sim = max(sims)
            # 主题加权：候选属于已订阅 topic 则乘 1.2
            if c["id"] in topic_boost_ids:
                sim *= _TOPIC_BOOST
            c["similarity"] = round(sim, 4)
            scored.append((sim, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        result = [item for _, item in scored[:top_k]]
        _set_cache(cache_key, result)
        return result


class TrendService:
    """热点趋势检测"""

    @staticmethod
    def _extract_metadata(papers: list) -> list[dict]:
        """在 session 内提取论文的 metadata_json"""
        return [p.metadata_json or {} for p in papers]

    def detect_hot_keywords(self, days: int = 7, top_k: int = 15) -> list[dict]:
        """分析近 N 天论文的关键词频率（5 分钟缓存）"""
        cache_key = f"hot_keywords:{days}:{top_k}"
        hit = _cached(cache_key)
        if hit is not None:
            return hit
        cutoff = datetime.now(UTC) - timedelta(days=days)
        with session_scope() as session:
            repo = PaperRepository(session)
            recent = repo.list_recent_since(cutoff, limit=500)
            metas = self._extract_metadata(recent)

        keyword_counter: Counter[str] = Counter()
        for meta in metas:
            for kw in meta.get("keywords", []):
                keyword_counter[kw.lower()] += 1
            for cat in meta.get("categories", []):
                keyword_counter[cat] += 1

        result = [
            {"keyword": kw, "count": count} for kw, count in keyword_counter.most_common(top_k)
        ]
        _set_cache(cache_key, result)
        return result

    def detect_trends(self, days: int = 14) -> dict:
        """对比近期 vs 更早期的关键词变化"""
        now = datetime.now(UTC)
        recent_cutoff = now - timedelta(days=days // 2)
        old_cutoff = now - timedelta(days=days)

        with session_scope() as session:
            repo = PaperRepository(session)
            recent_papers = repo.list_recent_since(recent_cutoff, limit=500)
            older_papers = repo.list_recent_between(old_cutoff, recent_cutoff, limit=500)
            recent_metas = self._extract_metadata(recent_papers)
            older_metas = self._extract_metadata(older_papers)
            recent_count = len(recent_papers)
            older_count = len(older_papers)

        def count_keywords(metas: list[dict]) -> Counter:
            c: Counter[str] = Counter()
            for meta in metas:
                for kw in meta.get("keywords", []):
                    c[kw.lower()] += 1
            return c

        recent_kw = count_keywords(recent_metas)
        older_kw = count_keywords(older_metas)

        emerging = []
        for kw, count in recent_kw.most_common(30):
            old_count = older_kw.get(kw, 0)
            if count >= 2 and (old_count == 0 or count / max(old_count, 1) >= 1.5):
                emerging.append(
                    {
                        "keyword": kw,
                        "recent_count": count,
                        "previous_count": old_count,
                        "growth": (
                            "新出现"
                            if old_count == 0
                            else f"+{round((count / old_count - 1) * 100)}%"
                        ),
                    }
                )

        return {
            "period_days": days,
            "recent_paper_count": recent_count,
            "older_paper_count": older_count,
            "hot_keywords": [{"keyword": kw, "count": c} for kw, c in recent_kw.most_common(10)],
            "emerging_trends": emerging[:10],
        }

    def get_today_summary(self) -> dict:
        """今日研究速览（5 分钟缓存）"""
        hit = _cached("today_summary")
        if hit is not None:
            return hit
        # 用用户时区的"今天 0:00"作为起始点，转为 UTC 与数据库比较
        from packages.timezone import user_today_start_utc

        today_start = user_today_start_utc()
        week_start = today_start - timedelta(days=7)

        with session_scope() as session:
            repo = PaperRepository(session)
            today_count = len(repo.list_recent_since(today_start, limit=100))
            week_count = len(repo.list_recent_since(week_start, limit=500))
            total_count = repo.count_all()

        recommendations = RecommendationService().recommend(top_k=5)
        hot_keywords = self.detect_hot_keywords(days=7, top_k=8)

        result = {
            "today_new": today_count,
            "week_new": week_count,
            "total_papers": total_count,
            "recommendations": recommendations,
            "hot_keywords": hot_keywords,
        }
        _set_cache("today_summary", result)
        return result
