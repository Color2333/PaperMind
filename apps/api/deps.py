"""PaperMind API — 共享依赖
@author Color2333
"""

import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from packages.ai.brief_service import DailyBriefService
from packages.ai.graph_service import GraphService
from packages.ai.pipelines import PaperPipelines
from packages.ai.rag_service import RAGService
from packages.config import get_settings
from packages.storage.db import session_scope
from packages.storage.repositories import PaperRepository

logger = logging.getLogger(__name__)

settings = get_settings()


# ---------- 轻量内存缓存（TTL，线程安全） ----------


class TTLCache:
    """简单的 TTL 内存缓存，避免引入 cachetools 依赖"""

    def __init__(self):
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        with self._lock:
            entry = self._store.get(key)
            if entry and time.time() < entry[0]:
                return entry[1]
            return None

    def set(self, key: str, value: Any, ttl: float):
        with self._lock:
            self._store[key] = (time.time() + ttl, value)

    def invalidate(self, key: str):
        with self._lock:
            self._store.pop(key, None)

    def invalidate_prefix(self, prefix: str):
        with self._lock:
            keys = [k for k in self._store if k.startswith(prefix)]
            for k in keys:
                del self._store[k]


cache = TTLCache()


# ---------- 辅助函数 ----------


def get_paper_title(paper_id: UUID) -> str | None:
    """快速获取论文标题"""
    try:
        with session_scope() as session:
            p = PaperRepository(session).get_by_id(paper_id)
            return (p.title or "")[:40]
    except Exception:
        return None


def iso_dt(dt: datetime | None) -> str | None:
    """确保返回带时区的 ISO 格式（SQLite 读出来的可能是 naive datetime）"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def brief_date() -> str:
    from packages.timezone import user_date_str
    return user_date_str()


def paper_list_response(papers: list, repo: PaperRepository) -> dict:
    """论文列表统一序列化"""
    paper_ids = [str(p.id) for p in papers]
    topic_map = repo.get_topic_names_for_papers(paper_ids)
    return {
        "items": [
            {
                "id": str(p.id),
                "title": p.title,
                "arxiv_id": p.arxiv_id,
                "abstract": p.abstract,
                "publication_date": str(p.publication_date) if p.publication_date else None,
                "read_status": p.read_status.value,
                "pdf_path": p.pdf_path,
                "has_embedding": p.embedding is not None,
                "favorited": getattr(p, "favorited", False),
                "categories": (p.metadata_json or {}).get("categories", []),
                "keywords": (p.metadata_json or {}).get("keywords", []),
                "title_zh": (p.metadata_json or {}).get("title_zh", ""),
                "abstract_zh": (p.metadata_json or {}).get("abstract_zh", ""),
                "topics": topic_map.get(str(p.id), []),
            }
            for p in papers
        ]
    }


# ---------- Service 单例 ----------

pipelines = PaperPipelines()
rag_service = RAGService()
brief_service = DailyBriefService()
graph_service = GraphService()
