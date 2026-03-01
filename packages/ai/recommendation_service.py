"""
推荐引擎 + 热点趋势检测
@author Bamzc
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import Counter
from datetime import UTC, datetime, timedelta

from packages.storage.db import session_scope
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


from packages.domain.math_utils import cosine_similarity as _cosine_sim


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


class RecommendationService:
    """基于阅读历史 embedding 的个性化推荐"""

    def get_user_profile(self) -> list[float]:
        """从已读论文（skimmed/deep_read）的 embedding 计算兴趣向量"""
        with session_scope() as session:
            repo = PaperRepository(session)
            read_papers = repo.list_by_read_status_with_embedding(
                statuses=["skimmed", "deep_read"], limit=200
            )
            vectors = [
                list(p.embedding) for p in read_papers
                if p.embedding
            ]
        if not vectors:
            return []
        return _mean_vector(vectors)

    def recommend(self, top_k: int = 10) -> list[dict]:
        """推荐与用户兴趣最匹配的未读论文"""
        profile = self.get_user_profile()
        if not profile:
            return []

        # 在 session 内提取所有需要的数据
        with session_scope() as session:
            repo = PaperRepository(session)
            unread = repo.list_unread_with_embedding(limit=200)
            candidates = []
            for p in unread:
                if not p.embedding:
                    continue
                meta = p.metadata_json or {}
                candidates.append({
                    "embedding": list(p.embedding),
                    "id": str(p.id),
                    "title": p.title,
                    "arxiv_id": p.arxiv_id,
                    "abstract": (p.abstract or "")[:300],
                    "publication_date": (
                        str(p.publication_date)
                        if p.publication_date else None
                    ),
                    "keywords": meta.get("keywords", []),
                    "categories": meta.get("categories", []),
                    "title_zh": meta.get("title_zh", ""),
                })

        profile_dim = len(profile)
        scored: list[tuple[float, dict]] = []
        for c in candidates:
            emb = c.pop("embedding")
            if len(emb) != profile_dim:
                continue
            sim = _cosine_sim(profile, emb)
            c["similarity"] = round(sim, 4)
            scored.append((sim, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:top_k]]


class TrendService:
    """热点趋势检测"""

    @staticmethod
    def _extract_metadata(papers: list) -> list[dict]:
        """在 session 内提取论文的 metadata_json"""
        return [p.metadata_json or {} for p in papers]

    def detect_hot_keywords(
        self, days: int = 7, top_k: int = 15
    ) -> list[dict]:
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
            {"keyword": kw, "count": count}
            for kw, count in keyword_counter.most_common(top_k)
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
            recent_papers = repo.list_recent_since(
                recent_cutoff, limit=500
            )
            older_papers = repo.list_recent_between(
                old_cutoff, recent_cutoff, limit=500
            )
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
            if count >= 2 and (
                old_count == 0
                or count / max(old_count, 1) >= 1.5
            ):
                emerging.append({
                    "keyword": kw,
                    "recent_count": count,
                    "previous_count": old_count,
                    "growth": (
                        "新出现" if old_count == 0
                        else f"+{round((count / old_count - 1) * 100)}%"
                    ),
                })

        return {
            "period_days": days,
            "recent_paper_count": recent_count,
            "older_paper_count": older_count,
            "hot_keywords": [
                {"keyword": kw, "count": c}
                for kw, c in recent_kw.most_common(10)
            ],
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
            today_count = len(
                repo.list_recent_since(today_start, limit=100)
            )
            week_count = len(
                repo.list_recent_since(week_start, limit=500)
            )
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
