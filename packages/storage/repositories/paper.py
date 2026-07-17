"""
论文数据仓储
@author Color2333
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import defer

from packages.domain.enums import ReadStatus
from packages.domain.math_utils import cosine_distance as _cosine_distance
from packages.storage.models import (
    AnalysisReport,
    Paper,
    PaperTag,
    PaperTopic,
    Tag,
    TopicSubscription,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy import Select
    from sqlalchemy.orm import Session

    from packages.domain.schemas import PaperCreate


class PaperRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_paper(self, data: PaperCreate) -> Paper:
        # 非 arXiv 源用合成值填充 arxiv_id（NOT NULL UNIQUE 列），维持多源去重
        arxiv_id = data.arxiv_id or data.normalized_arxiv_id or f"{data.source}:{data.source_id}"
        q = select(Paper).where(Paper.arxiv_id == arxiv_id)
        existing = self.session.execute(q).scalar_one_or_none()
        if existing:
            existing.title = data.title
            existing.abstract = data.abstract
            existing.publication_date = data.publication_date
            existing.metadata_json = data.metadata
            existing.updated_at = datetime.now(UTC)
            self.session.flush()
            return existing

        paper = Paper(
            arxiv_id=arxiv_id,
            title=data.title,
            abstract=data.abstract,
            publication_date=data.publication_date,
            metadata_json=data.metadata,
            source=data.source,
            source_id=data.source_id,
            doi=data.doi,
        )
        self.session.add(paper)
        self.session.flush()
        return paper

    def list_latest(self, limit: int = 20) -> list[Paper]:
        q: Select[tuple[Paper]] = select(Paper).order_by(Paper.created_at.desc()).limit(limit)
        return list(self.session.execute(q).scalars())

    def list_all(self, limit: int = 10000) -> list[Paper]:
        return self.list_latest(limit=limit)

    def list_lightweight(self, limit: int = 50000) -> list[Paper]:
        """只加载论文的轻量字段，避免加载 embedding 和大文本

        适用于需要批量加载论文但只需 id, title, arxiv_id, publication_date 等字段的场景
        """
        q = (
            select(Paper)
            .options(defer(Paper.embedding), defer(Paper.abstract))
            .order_by(Paper.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(q).scalars())

    def list_by_ids(self, paper_ids: list[str]) -> list[Paper]:
        if not paper_ids:
            return []
        q = select(Paper).where(Paper.id.in_(paper_ids))
        return list(self.session.execute(q).scalars())

    def list_existing_arxiv_ids(self, arxiv_ids: list[str]) -> set[str]:
        """批量检查哪些 arxiv_id 已存在，返回已存在的 ID 集合"""
        if not arxiv_ids:
            return set()
        q = select(Paper.arxiv_id).where(Paper.arxiv_id.in_(arxiv_ids))
        return set(self.session.execute(q).scalars())

    def list_existing_dois(self, dois: list[str]) -> set[str]:
        """批量检查哪些 DOI 已存在，返回已存在的 DOI 集合（IEEE 去重用）"""
        if not dois:
            return set()
        # 过滤 None 值
        clean_dois = [d for d in dois if d]
        if not clean_dois:
            return set()
        q = select(Paper.doi).where(Paper.doi.in_(clean_dois))
        return set(self.session.execute(q).scalars())

    def list_by_read_status(self, status: ReadStatus, limit: int = 200) -> list[Paper]:
        q = (
            select(Paper)
            .where(Paper.read_status == status)
            .order_by(Paper.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(q).scalars())

    def list_by_read_status_with_embedding(
        self, statuses: list[str], limit: int = 200
    ) -> list[Paper]:
        """查询指定阅读状态且有 embedding 的论文"""
        status_enums = [ReadStatus(s) for s in statuses]
        q = (
            select(Paper)
            .where(
                Paper.read_status.in_(status_enums),
                Paper.embedding.is_not(None),
            )
            .order_by(Paper.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(q).scalars())

    def list_unread_with_embedding(self, limit: int = 200) -> list[Paper]:
        """查询未读但有 embedding 的论文"""
        q = (
            select(Paper)
            .where(
                Paper.read_status == ReadStatus.unread,
                Paper.embedding.is_not(None),
            )
            .order_by(Paper.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(q).scalars())

    def list_with_embedding(
        self,
        topic_id: str | None = None,
        limit: int = 200,
    ) -> list[Paper]:
        """查询有 embedding 的论文，可选按 topic 过滤"""
        if topic_id:
            q = (
                select(Paper)
                .join(PaperTopic, Paper.id == PaperTopic.paper_id)
                .where(
                    PaperTopic.topic_id == topic_id,
                    Paper.embedding.is_not(None),
                )
                .order_by(Paper.created_at.desc())
                .limit(limit)
            )
        else:
            q = (
                select(Paper)
                .where(Paper.embedding.is_not(None))
                .order_by(Paper.created_at.desc())
                .limit(limit)
            )
        return list(self.session.execute(q).scalars())

    def list_recent_since(self, since: datetime, limit: int = 500) -> list[Paper]:
        """查询指定时间之后入库的论文"""
        q = (
            select(Paper)
            .where(Paper.created_at >= since)
            .order_by(Paper.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(q).scalars())

    def list_recent_between(self, start: datetime, end: datetime, limit: int = 500) -> list[Paper]:
        """查询指定时间区间内入库的论文"""
        q = (
            select(Paper)
            .where(Paper.created_at >= start, Paper.created_at < end)
            .order_by(Paper.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(q).scalars())

    def list_for_brief(self, since: datetime, min_score: float, limit: int = 30) -> list[Paper]:
        """简报专用：取 since 之后入库、skim_score >= min_score 的论文，按分数降序。

        排除未 skim 的论文（无 AnalysisReport 或 skim_score 为空）。
        分数相同再按 created_at 降序，保证新论文优先。
        """
        q = (
            select(Paper)
            .join(AnalysisReport, AnalysisReport.paper_id == Paper.id)
            .where(Paper.created_at >= since)
            .where(AnalysisReport.skim_score >= min_score)
            .order_by(AnalysisReport.skim_score.desc(), Paper.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(q).scalars())

    def list_recent_skimmed(self, since: datetime, limit: int = 30) -> list[Paper]:
        """简报回退用：取 since 之后已 skim 的全部论文（不限分数），按 created_at 降序。

        用于高分论文不足时补齐简报，保证邮件不空。
        """
        q = (
            select(Paper)
            .join(AnalysisReport, AnalysisReport.paper_id == Paper.id)
            .where(Paper.created_at >= since)
            .order_by(Paper.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(q).scalars())

    def count_all(self) -> int:
        q = select(func.count()).select_from(Paper)
        return self.session.execute(q).scalar() or 0

    def list_paginated(
        self,
        page: int = 1,
        page_size: int = 20,
        folder: str | None = None,
        topic_id: str | None = None,
        status: str | None = None,
        date_str: str | None = None,
        search: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        category: str | None = None,
        tag_ids: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        date_field: str = "created_at",
    ) -> tuple[list[Paper], int]:
        """分页查询论文，返回 (papers, total_count)"""
        filters = []
        need_join_topic = False
        need_join_tag = False

        if search:
            like_pat = f"%{search}%"
            filters.append(
                Paper.title.ilike(like_pat)
                | Paper.abstract.ilike(like_pat)
                | Paper.arxiv_id.ilike(like_pat)
            )

        if folder == "favorites":
            filters.append(Paper.favorited == True)  # noqa: E712
        elif folder == "recent":
            since = datetime.now(UTC) - timedelta(days=7)
            filters.append(Paper.created_at >= since)
        elif folder == "unclassified":
            subq = select(PaperTopic.paper_id).distinct()
            filters.append(Paper.id.notin_(subq))
        elif topic_id:
            need_join_topic = True
            filters.append(PaperTopic.topic_id == topic_id)

        if tag_ids and len(tag_ids) > 0:
            need_join_tag = True
            filters.append(PaperTag.tag_id.in_(tag_ids))

        if status and status in ("unread", "skimmed", "deep_read"):
            filters.append(Paper.read_status == ReadStatus(status))

        # 日期范围筛选（start_date/end_date 优先于 date_str）
        if start_date or end_date:
            col = Paper.created_at if date_field == "created_at" else Paper.publication_date
            try:
                if start_date:
                    d = date.fromisoformat(start_date)
                    if date_field == "publication_date":
                        filters.append(col >= d)
                    else:
                        filters.append(col >= datetime(d.year, d.month, d.day, tzinfo=UTC))
                if end_date:
                    d = date.fromisoformat(end_date)
                    if date_field == "publication_date":
                        # publication_date 是 Date 类型，取 < 次日即可包含当天
                        from datetime import timedelta as _td

                        filters.append(col < d + _td(days=1))
                    else:
                        filters.append(
                            col < datetime(d.year, d.month, d.day, tzinfo=UTC) + timedelta(days=1)
                        )
            except ValueError:
                pass
        elif date_str:
            try:
                d = date.fromisoformat(date_str)
                day_start = datetime(d.year, d.month, d.day, tzinfo=UTC)
                day_end = day_start + timedelta(days=1)
                filters.append(Paper.created_at >= day_start)
                filters.append(Paper.created_at < day_end)
            except ValueError:
                pass

        if category:
            filters.append(Paper.metadata_json.contains({"categories": [category]}))

        base_q = select(Paper)
        count_q = select(func.count()).select_from(Paper)
        if need_join_topic:
            base_q = base_q.join(PaperTopic, Paper.id == PaperTopic.paper_id)
            count_q = count_q.join(PaperTopic, Paper.id == PaperTopic.paper_id)
        if need_join_tag:
            base_q = base_q.join(PaperTag, Paper.id == PaperTag.paper_id)
            count_q = count_q.join(PaperTag, Paper.id == PaperTag.paper_id)
        for f in filters:
            base_q = base_q.where(f)
            count_q = count_q.where(f)

        total = self.session.execute(count_q).scalar() or 0
        offset = (max(1, page) - 1) * page_size
        _SORT_COLS = {
            "created_at": Paper.created_at,
            "publication_date": Paper.publication_date,
            "title": Paper.title,
        }
        sort_col = _SORT_COLS.get(sort_by, Paper.created_at)
        order_expr = sort_col.desc() if sort_order == "desc" else sort_col.asc()
        papers = list(
            self.session.execute(
                base_q.order_by(order_expr).offset(offset).limit(page_size)
            ).scalars()
        )
        return papers, total

    def list_by_topic(self, topic_id: str, limit: int = 200) -> list[Paper]:
        q = (
            select(Paper)
            .join(PaperTopic, Paper.id == PaperTopic.paper_id)
            .where(PaperTopic.topic_id == topic_id)
            .order_by(Paper.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(q).scalars())

    def get_by_id(self, paper_id: UUID) -> Paper:
        paper = self.session.get(Paper, str(paper_id))
        if paper is None:
            raise ValueError(f"paper {paper_id} not found")
        return paper

    def set_pdf_path(self, paper_id: UUID, pdf_path: str) -> None:
        paper = self.get_by_id(paper_id)
        paper.pdf_path = pdf_path
        paper.updated_at = datetime.now(UTC)

    def update_embedding(self, paper_id: UUID, embedding: list[float]) -> None:
        paper = self.get_by_id(paper_id)
        paper.embedding = embedding
        paper.updated_at = datetime.now(UTC)

    def update_read_status(self, paper_id: UUID, status: ReadStatus) -> None:
        paper = self.get_by_id(paper_id)
        upgrade = (
            paper.read_status == ReadStatus.unread
            and status in (ReadStatus.skimmed, ReadStatus.deep_read)
        ) or (paper.read_status == ReadStatus.skimmed and status == ReadStatus.deep_read)
        if upgrade:
            paper.read_status = status

    def similar_by_embedding(
        self,
        vector: list[float],
        exclude: UUID,
        limit: int = 5,
        max_candidates: int = 500,
    ) -> list[Paper]:
        if not vector:
            return []
        q = (
            select(Paper)
            .where(Paper.id != str(exclude))
            .where(Paper.embedding.is_not(None))
            .order_by(Paper.created_at.desc())
            .limit(max_candidates)
        )
        candidates = list(self.session.execute(q).scalars())
        ranked = sorted(
            candidates,
            key=lambda p: _cosine_distance(vector, p.embedding or []),
        )
        return ranked[:limit]

    def full_text_candidates(self, query: str, limit: int = 8) -> list[Paper]:
        """按关键词搜索论文（每个词独立匹配 title/abstract）"""
        tokens = [t for t in query.lower().split() if len(t) >= 2]
        if not tokens:
            return []
        # 每个关键词必须出现在 title 或 abstract 中
        conditions = []
        for token in tokens:
            conditions.append(
                func.lower(Paper.title).contains(token) | func.lower(Paper.abstract).contains(token)
            )
        q = select(Paper).where(*conditions).limit(limit)
        return list(self.session.execute(q).scalars())

    def semantic_candidates(
        self,
        query_vector: list[float],
        limit: int = 8,
        max_candidates: int = 500,
    ) -> list[Paper]:
        if not query_vector:
            return []
        q = (
            select(Paper)
            .where(Paper.embedding.is_not(None))
            .order_by(Paper.created_at.desc())
            .limit(max_candidates)
        )
        candidates = list(self.session.execute(q).scalars())
        ranked = sorted(
            candidates,
            key=lambda p: _cosine_distance(query_vector, p.embedding or []),
        )
        return ranked[:limit]

    def link_to_topic(self, paper_id: str, topic_id: str) -> None:
        q = select(PaperTopic).where(
            PaperTopic.paper_id == paper_id,
            PaperTopic.topic_id == topic_id,
        )
        found = self.session.execute(q).scalar_one_or_none()
        if found:
            return
        self.session.add(PaperTopic(paper_id=paper_id, topic_id=topic_id))

    def get_topic_names_for_papers(self, paper_ids: list[str]) -> dict[str, list[str]]:
        """批量查 paper → topic name 映射"""
        if not paper_ids:
            return {}
        q = (
            select(PaperTopic.paper_id, TopicSubscription.name)
            .join(
                TopicSubscription,
                PaperTopic.topic_id == TopicSubscription.id,
            )
            .where(PaperTopic.paper_id.in_(paper_ids))
        )
        rows = self.session.execute(q).all()
        result: dict[str, list[str]] = {}
        for pid, tname in rows:
            result.setdefault(pid, []).append(tname)
        return result

    def get_tags_for_papers(self, paper_ids: list[str]) -> dict[str, list[dict]]:
        """批量查 paper → tags 映射"""
        if not paper_ids:
            return {}
        q = (
            select(PaperTag.paper_id, Tag.id, Tag.name, Tag.color)
            .join(Tag, PaperTag.tag_id == Tag.id)
            .where(PaperTag.paper_id.in_(paper_ids))
        )
        rows = self.session.execute(q).all()
        result: dict[str, list[dict]] = {}
        for pid, tid, tname, tcolor in rows:
            result.setdefault(pid, []).append({"id": tid, "name": tname, "color": tcolor})
        return result

    def link_to_tag(self, paper_id: str, tag_id: str) -> None:
        """为论文添加标签"""
        q = select(PaperTag).where(
            PaperTag.paper_id == paper_id,
            PaperTag.tag_id == tag_id,
        )
        found = self.session.execute(q).scalar_one_or_none()
        if found:
            return
        self.session.add(PaperTag(paper_id=paper_id, tag_id=tag_id))

    def unlink_from_tag(self, paper_id: str, tag_id: str) -> None:
        """移除论文的标签"""
        q = select(PaperTag).where(
            PaperTag.paper_id == paper_id,
            PaperTag.tag_id == tag_id,
        )
        found = self.session.execute(q).scalar_one_or_none()
        if found:
            self.session.delete(found)
