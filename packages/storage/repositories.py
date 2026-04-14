"""
数据仓储层
@author Color2333
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import Integer, Select, delete, func, select
from sqlalchemy.orm import Session, defer

from packages.domain.enums import ActionType, PipelineStatus, ReadStatus
from packages.domain.math_utils import cosine_distance as _cosine_distance
from packages.domain.schemas import DeepDiveReport, PaperCreate, SkimReport
from packages.storage.models import (
    ActionPaper,
    AgentConversation,
    AgentMessage,
    AgentPendingAction,
    AnalysisReport,
    Citation,
    CollectionAction,
    CSCategory,
    CSFeedSubscription,
    DailyReportConfig,
    EmailConfig,
    GeneratedContent,
    IeeeApiQuota,
    LLMProviderConfig,
    Paper,
    PaperTag,
    PaperTopic,
    PipelineRun,
    PromptTrace,
    SourceCheckpoint,
    Tag,
    TopicSubscription,
)


class BaseQuery:
    """
    基础查询类 - 提供通用的查询方法减少重复代码
    """

    def __init__(self, session: Session):
        self.session = session

    def _paginate(self, query: Select, page: int, page_size: int) -> Select:
        """
        添加分页到查询

        Args:
            query: SQLAlchemy 查询对象
            page: 页码（从 1 开始）
            page_size: 每页大小

        Returns:
            添加了分页的查询对象
        """
        offset = (max(1, page) - 1) * page_size
        return query.offset(offset).limit(page_size)

    def _execute_paginated(
        self, query: Select, page: int = 1, page_size: int = 20
    ) -> tuple[list, int]:
        """
        执行分页查询，返回 (结果列表, 总数)

        Args:
            query: SQLAlchemy 查询对象
            page: 页码（从 1 开始）
            page_size: 每页大小

        Returns:
            (结果列表, 总数)
        """
        count_query = select(func.count()).select_from(query.alias())
        total = self.session.execute(count_query).scalar() or 0

        paginated_query = self._paginate(query, page, page_size)
        results = list(self.session.execute(paginated_query).scalars())

        return results, total


class PaperRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_paper(self, data: PaperCreate) -> Paper:
        q = select(Paper).where(Paper.arxiv_id == data.arxiv_id)
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
            arxiv_id=data.arxiv_id,
            title=data.title,
            abstract=data.abstract,
            publication_date=data.publication_date,
            metadata_json=data.metadata,
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

    def count_all(self) -> int:
        q = select(func.count()).select_from(Paper)
        return self.session.execute(q).scalar() or 0

    def folder_stats(self) -> dict:
        """返回文件夹统计：按主题、收藏、最近、未分类"""
        from packages.timezone import user_today_start_utc, utc_offset_hours

        total = self.count_all()
        fav_q = select(func.count()).select_from(Paper).where(Paper.favorited == True)  # noqa: E712
        favorites = self.session.execute(fav_q).scalar() or 0

        # "最近 7 天" 用用户时区的今天 0 点往前推 7 天
        user_today_utc = user_today_start_utc()
        week_start_utc = user_today_utc - timedelta(days=7)
        recent_q = select(func.count()).select_from(Paper).where(Paper.created_at >= week_start_utc)
        recent_7d = self.session.execute(recent_q).scalar() or 0

        # 有主题的论文 ID 集合
        has_topic_q = select(func.count(func.distinct(PaperTopic.paper_id)))
        has_topic = self.session.execute(has_topic_q).scalar() or 0
        unclassified = total - has_topic

        # 按主题统计
        topic_counts_q = (
            select(
                TopicSubscription.id,
                TopicSubscription.name,
                func.count(PaperTopic.paper_id),
            )
            .join(PaperTopic, TopicSubscription.id == PaperTopic.topic_id)
            .group_by(TopicSubscription.id, TopicSubscription.name)
            .order_by(func.count(PaperTopic.paper_id).desc())
        )
        topic_rows = self.session.execute(topic_counts_q).all()
        by_topic = [{"topic_id": r[0], "topic_name": r[1], "count": r[2]} for r in topic_rows]

        # 按阅读状态统计
        status_q = select(Paper.read_status, func.count()).group_by(Paper.read_status)
        status_rows = self.session.execute(status_q).all()
        by_status = {r[0].value: r[1] for r in status_rows}

        # 按日期分组（最近 30 天），用用户时区偏移
        # SQLite: datetime(created_at, '+N hours') 将 UTC 转为用户本地时间再取 date
        offset_h = utc_offset_hours()
        offset_str = f"{offset_h:+.0f} hours"
        date_expr = func.date(func.datetime(Paper.created_at, offset_str))
        since_30d = user_today_utc - timedelta(days=30)
        date_q = (
            select(date_expr.label("d"), func.count().label("c"))
            .where(Paper.created_at >= since_30d)
            .group_by(date_expr)
            .order_by(date_expr.desc())
        )
        date_rows = self.session.execute(date_q).all()
        by_date = [{"date": str(r[0]), "count": r[1]} for r in date_rows]

        return {
            "total": total,
            "favorites": favorites,
            "recent_7d": recent_7d,
            "unclassified": unclassified,
            "by_topic": by_topic,
            "by_status": by_status,
            "by_date": by_date,
        }

    def topic_stats(self) -> dict:
        """
        返回主题维度统计：
        - 每个主题的论文数、总引用数、活跃度（近 30 天新增）
        - 每个主题的阅读状态分布

        优化：将 N+1 查询合并为 4 次批量聚合查询
        """
        from packages.timezone import user_today_start_utc

        user_today_utc = user_today_start_utc()
        since_30d = user_today_utc - timedelta(days=30)

        # 1. 获取所有主题基本信息和论文数
        topic_stats_q = (
            select(
                TopicSubscription.id,
                TopicSubscription.name,
                func.count(PaperTopic.paper_id).label("paper_count"),
            )
            .join(PaperTopic, TopicSubscription.id == PaperTopic.topic_id, isouter=True)
            .group_by(TopicSubscription.id, TopicSubscription.name)
        )
        topic_rows = self.session.execute(topic_stats_q).all()

        # 提取所有 topic_id 用于批量查询
        topic_ids = [row.id for row in topic_rows]
        if not topic_ids:
            return {"topics": []}

        # 2. 批量查询所有主题的总引用数（一次查询，GROUP BY topic_id）
        citation_subq = (
            select(
                PaperTopic.topic_id,
                func.coalesce(
                    func.sum(
                        func.cast(
                            func.json_extract(Paper.metadata_json, "$.citation_count"), Integer
                        )
                    ),
                    0,
                ).label("total_citations"),
            )
            .join(Paper, Paper.id == PaperTopic.paper_id)
            .group_by(PaperTopic.topic_id)
            .subquery()
        )
        citation_rows = {
            row[0]: row[1] for row in self.session.execute(select(citation_subq)).all()
        }

        # 3. 批量查询所有主题的近 30 天新增论文数（一次查询，GROUP BY topic_id）
        recent_subq = (
            select(
                PaperTopic.topic_id,
                func.count().label("recent_30d"),
            )
            .join(Paper, Paper.id == PaperTopic.paper_id)
            .where(Paper.created_at >= since_30d)
            .group_by(PaperTopic.topic_id)
            .subquery()
        )
        recent_rows = {row[0]: row[1] for row in self.session.execute(select(recent_subq)).all()}

        # 4. 批量查询所有主题的阅读状态分布（一次查询，GROUP BY topic_id, read_status）
        status_subq = (
            select(
                PaperTopic.topic_id,
                Paper.read_status,
                func.count().label("count"),
            )
            .join(Paper, Paper.id == PaperTopic.paper_id)
            .group_by(PaperTopic.topic_id, Paper.read_status)
            .subquery()
        )
        status_rows = self.session.execute(select(status_subq)).all()
        # 组装成 {topic_id: {status: count}}
        status_map: dict[str, dict[str, int]] = {}
        for row in status_rows:
            tid = row[0]
            status = row[1].value
            count = row[2]
            if tid not in status_map:
                status_map[tid] = {}
            status_map[tid][status] = count

        # 在 Python 中组装结果
        result = []
        for row in topic_rows:
            topic_id = row.id
            topic_name = row.name
            paper_count = row.paper_count or 0
            total_citations = citation_rows.get(topic_id, 0)
            recent_30d = recent_rows.get(topic_id, 0)

            topic_status = status_map.get(topic_id, {})
            result.append(
                {
                    "topic_id": topic_id,
                    "topic_name": topic_name,
                    "paper_count": paper_count,
                    "total_citations": total_citations,
                    "recent_30d": recent_30d,
                    "status_dist": {
                        "unread": topic_status.get("unread", 0),
                        "skimmed": topic_status.get("skimmed", 0),
                        "deep_read": topic_status.get("deep_read", 0),
                    },
                }
            )

        # 按论文数降序排列
        result.sort(key=lambda x: x["paper_count"], reverse=True)
        return {"topics": result}

    def paper_distribution_stats(self) -> dict:
        """论文分布统计：按发表年份分布 + 按来源分布"""
        from packages.timezone import user_today_start_utc

        by_year_q = (
            select(
                func.coalesce(func.strftime("%Y", Paper.publication_date), "未知").label("year"),
                func.count().label("count"),
            )
            .group_by(func.strftime("%Y", Paper.publication_date))
            .order_by(func.strftime("%Y", Paper.publication_date).desc())
        )
        year_rows = self.session.execute(by_year_q).all()
        by_year = [{"year": r[0], "count": r[1]} for r in year_rows]

        by_source_q = (
            select(
                func.coalesce(func.json_extract(Paper.metadata_json, "$.source"), "unknown").label(
                    "source"
                ),
                func.count().label("count"),
            )
            .group_by(func.json_extract(Paper.metadata_json, "$.source"))
            .order_by(func.count().desc())
        )
        source_rows = self.session.execute(by_source_q).all()
        source_label: dict[str, str] = {
            "arxiv": "arXiv",
            "semantic_scholar": "Semantic Scholar",
            "reference_import": "参考文献导入",
            "unknown": "未知来源",
        }
        by_source = [
            {"source": source_label.get(r[0], r[0]), "raw_source": r[0], "count": r[1]}
            for r in source_rows
        ]

        by_status_q = select(Paper.read_status, func.count()).group_by(Paper.read_status)
        status_rows = self.session.execute(by_status_q).all()
        status_label: dict[str, str] = {
            "unread": "未读",
            "skimmed": "已粗读",
            "deep_read": "已精读",
        }
        by_status = [
            {
                "status": status_label.get(r[0].value, r[0].value),
                "raw_status": r[0].value,
                "count": r[1],
            }
            for r in status_rows
        ]

        user_today_utc = user_today_start_utc()
        by_month_rows: list[dict] = []
        for i in range(11, -1, -1):
            month_start = user_today_utc - timedelta(days=30 * i)
            month_label = month_start.strftime("%Y-%m")
            month_start_day = month_start.replace(day=1)
            if month_start.month == 12:
                month_end = month_start.replace(year=month_start.year + 1, month=1, day=1)
            else:
                month_end = month_start.replace(month=month_start.month + 1, day=1)
            count_q = (
                select(func.count())
                .select_from(Paper)
                .where(
                    Paper.created_at >= month_start_day,
                    Paper.created_at < month_end,
                )
            )
            count = self.session.execute(count_q).scalar() or 0
            by_month_rows.append({"month": month_label, "count": count})

        by_venue_q = (
            select(
                func.coalesce(func.json_extract(Paper.metadata_json, "$.venue"), "未知").label(
                    "venue"
                ),
                func.count().label("count"),
            )
            .where(func.json_extract(Paper.metadata_json, "$.venue") != None)
            .group_by(func.json_extract(Paper.metadata_json, "$.venue"))
            .order_by(func.count().desc())
            .limit(15)
        )
        venue_rows = self.session.execute(by_venue_q).all()
        by_venue = [{"venue": r[0], "count": r[1]} for r in venue_rows if r[0]]

        action_source_q = (
            select(
                CollectionAction.action_type,
                func.sum(CollectionAction.paper_count).label("total"),
            )
            .group_by(CollectionAction.action_type)
            .order_by(func.sum(CollectionAction.paper_count).desc())
        )
        action_rows = self.session.execute(action_source_q).all()
        action_label: dict[str, str] = {
            "initial_import": "初始导入",
            "manual_collect": "手动收集",
            "auto_collect": "自动收集",
            "agent_collect": "Agent收集",
            "subscription_ingest": "订阅抓取",
            "reference_import": "参考文献",
        }
        by_action_source = [
            {
                "source": action_label.get(r[0].value, r[0].value),
                "raw_source": r[0].value,
                "count": r[1] or 0,
            }
            for r in action_rows
        ]

        return {
            "by_year": by_year,
            "by_source": by_source,
            "by_status": by_status,
            "by_month": by_month_rows,
            "by_venue": by_venue,
            "by_action_source": by_action_source,
        }

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

        if date_str:
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


class TagRepository:
    """标签数据仓储"""

    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[Tag]:
        """获取所有标签，按使用次数排序"""
        q = (
            select(Tag, func.count(PaperTag.id).label("paper_count"))
            .join(PaperTag, Tag.id == PaperTag.tag_id, isouter=True)
            .group_by(Tag.id)
            .order_by(func.count(PaperTag.id).desc())
        )
        rows = self.session.execute(q).all()
        tags = []
        for row in rows:
            tag = row[0]
            tag.paper_count = row[1] or 0
            tags.append(tag)
        return tags

    def get_by_id(self, tag_id: str) -> Tag | None:
        """根据 ID 获取标签"""
        return self.session.get(Tag, tag_id)

    def get_by_name(self, name: str) -> Tag | None:
        """根据名称获取标签"""
        q = select(Tag).where(Tag.name == name)
        return self.session.execute(q).scalar_one_or_none()

    def create(self, name: str, color: str = "#3b82f6") -> Tag:
        """创建新标签"""
        existing = self.get_by_name(name)
        if existing:
            raise ValueError(f"标签 '{name}' 已存在")
        tag = Tag(name=name, color=color)
        self.session.add(tag)
        self.session.flush()
        return tag

    def update(self, tag_id: str, name: str | None = None, color: str | None = None) -> Tag:
        """更新标签"""
        tag = self.get_by_id(tag_id)
        if tag is None:
            raise ValueError(f"标签 {tag_id} 不存在")
        if name is not None:
            existing = self.get_by_name(name)
            if existing and existing.id != tag_id:
                raise ValueError(f"标签 '{name}' 已存在")
            tag.name = name
        if color is not None:
            tag.color = color
        self.session.flush()
        return tag

    def delete(self, tag_id: str) -> None:
        """删除标签"""
        tag = self.get_by_id(tag_id)
        if tag is not None:
            self.session.delete(tag)

    def get_paper_count(self, tag_id: str) -> int:
        """获取标签关联的论文数量"""
        q = select(func.count()).select_from(PaperTag).where(PaperTag.tag_id == tag_id)
        return self.session.execute(q).scalar() or 0


class AnalysisRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_skim(self, paper_id: UUID, skim: SkimReport) -> None:
        report = self._get_or_create(paper_id)
        innovations = "".join([f"  - {x}\n" for x in skim.innovations])
        report.summary_md = f"- 一句话: {skim.one_liner}\n- 创新点:\n{innovations}"
        report.skim_score = skim.relevance_score
        report.key_insights = {"skim_innovations": skim.innovations}

    def upsert_deep_dive(self, paper_id: UUID, deep: DeepDiveReport) -> None:
        report = self._get_or_create(paper_id)
        risks = "".join([f"- {x}\n" for x in deep.reviewer_risks])
        report.deep_dive_md = (
            f"## Method\n{deep.method_summary}\n\n"
            f"## Experiments\n{deep.experiments_summary}\n\n"
            f"## Ablation\n{deep.ablation_summary}\n\n"
            f"## Reviewer Risks\n{risks}"
        )
        report.key_insights = {
            **(report.key_insights or {}),
            "reviewer_risks": deep.reviewer_risks,
        }

    def _get_or_create(self, paper_id: UUID) -> AnalysisReport:
        pid = str(paper_id)
        q = select(AnalysisReport).where(AnalysisReport.paper_id == pid)
        found = self.session.execute(q).scalar_one_or_none()
        if found:
            return found
        report = AnalysisReport(paper_id=pid, key_insights={})
        self.session.add(report)
        self.session.flush()
        return report

    def summaries_for_papers(self, paper_ids: list[str]) -> dict[str, str]:
        if not paper_ids:
            return {}
        q = select(AnalysisReport).where(AnalysisReport.paper_id.in_(paper_ids))
        reports = list(self.session.execute(q).scalars())
        return {x.paper_id: x.summary_md or "" for x in reports}

    def contexts_for_papers(self, paper_ids: list[str]) -> dict[str, str]:
        if not paper_ids:
            return {}
        q = select(AnalysisReport).where(AnalysisReport.paper_id.in_(paper_ids))
        reports = list(self.session.execute(q).scalars())
        out: dict[str, str] = {}
        for x in reports:
            combined = []
            if x.summary_md:
                combined.append(x.summary_md)
            if x.deep_dive_md:
                combined.append(x.deep_dive_md[:2000])
            out[x.paper_id] = "\n\n".join(combined)
        return out


class PipelineRunRepository:
    def __init__(self, session: Session):
        self.session = session

    def start(
        self,
        pipeline_name: str,
        paper_id: UUID | None = None,
        decision_note: str | None = None,
    ) -> PipelineRun:
        run = PipelineRun(
            pipeline_name=pipeline_name,
            paper_id=str(paper_id) if paper_id else None,
            status=PipelineStatus.running,
            decision_note=decision_note,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def finish(self, run_id: UUID, elapsed_ms: int | None = None) -> None:
        run = self.session.get(PipelineRun, str(run_id))
        if not run:
            return
        run.status = PipelineStatus.succeeded
        run.elapsed_ms = elapsed_ms

    def fail(self, run_id: UUID, error_message: str) -> None:
        run = self.session.get(PipelineRun, str(run_id))
        if not run:
            return
        run.status = PipelineStatus.failed
        run.retry_count += 1
        run.error_message = error_message

    def list_latest(self, limit: int = 30) -> list[PipelineRun]:
        q = select(PipelineRun).order_by(PipelineRun.created_at.desc()).limit(limit)
        return list(self.session.execute(q).scalars())


class PromptTraceRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        stage: str,
        provider: str,
        model: str,
        prompt_digest: str,
        paper_id: UUID | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        input_cost_usd: float | None = None,
        output_cost_usd: float | None = None,
        total_cost_usd: float | None = None,
    ) -> None:
        self.session.add(
            PromptTrace(
                stage=stage,
                provider=provider,
                model=model,
                prompt_digest=prompt_digest,
                paper_id=str(paper_id) if paper_id else None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                input_cost_usd=input_cost_usd,
                output_cost_usd=output_cost_usd,
                total_cost_usd=total_cost_usd,
            )
        )

    def summarize_costs(self, days: int = 7) -> dict:
        since = None if days <= 0 else datetime.now(UTC) - timedelta(days=days)
        base_filter = [] if since is None else [PromptTrace.created_at >= since]

        total_q = select(
            func.count(PromptTrace.id),
            func.coalesce(func.sum(PromptTrace.input_tokens), 0),
            func.coalesce(func.sum(PromptTrace.output_tokens), 0),
            func.coalesce(func.sum(PromptTrace.total_cost_usd), 0.0),
        )
        if since:
            total_q = total_q.where(*base_filter)
        count, in_tokens, out_tokens, total_cost = self.session.execute(total_q).one()

        by_stage_q = select(
            PromptTrace.stage,
            func.count(PromptTrace.id),
            func.coalesce(func.sum(PromptTrace.total_cost_usd), 0.0),
            func.coalesce(func.sum(PromptTrace.input_tokens), 0),
            func.coalesce(func.sum(PromptTrace.output_tokens), 0),
        )
        if since:
            by_stage_q = by_stage_q.where(*base_filter)
        by_stage_q = by_stage_q.group_by(PromptTrace.stage)

        by_model_q = select(
            PromptTrace.provider,
            PromptTrace.model,
            func.count(PromptTrace.id),
            func.coalesce(func.sum(PromptTrace.total_cost_usd), 0.0),
            func.coalesce(func.sum(PromptTrace.input_tokens), 0),
            func.coalesce(func.sum(PromptTrace.output_tokens), 0),
        )
        if since:
            by_model_q = by_model_q.where(*base_filter)
        by_model_q = by_model_q.group_by(PromptTrace.provider, PromptTrace.model)

        by_stage = [
            {
                "stage": stage,
                "calls": calls,
                "total_cost_usd": float(cost),
                "input_tokens": int(in_t or 0),
                "output_tokens": int(out_t or 0),
            }
            for stage, calls, cost, in_t, out_t in self.session.execute(by_stage_q).all()
        ]
        by_model = [
            {
                "provider": prov,
                "model": mdl,
                "calls": calls,
                "total_cost_usd": float(cost),
                "input_tokens": int(in_t or 0),
                "output_tokens": int(out_t or 0),
            }
            for prov, mdl, calls, cost, in_t, out_t in self.session.execute(by_model_q).all()
        ]

        return {
            "window_days": days,
            "calls": int(count),
            "input_tokens": int(in_tokens or 0),
            "output_tokens": int(out_tokens or 0),
            "total_cost_usd": float(total_cost or 0.0),
            "by_stage": by_stage,
            "by_model": by_model,
        }


class SourceCheckpointRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, source: str) -> SourceCheckpoint | None:
        q = select(SourceCheckpoint).where(SourceCheckpoint.source == source)
        return self.session.execute(q).scalar_one_or_none()

    def upsert(self, source: str, last_published_date: date | None) -> None:
        found = self.get(source)
        now = datetime.now(UTC)
        if found:
            found.last_fetch_at = now
            if last_published_date and (
                found.last_published_date is None or last_published_date > found.last_published_date
            ):
                found.last_published_date = last_published_date
            return
        self.session.add(
            SourceCheckpoint(
                source=source,
                last_fetch_at=now,
                last_published_date=last_published_date,
            )
        )


class CitationRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_edge(
        self,
        source_paper_id: str,
        target_paper_id: str,
        context: str | None = None,
    ) -> None:
        q = select(Citation).where(
            Citation.source_paper_id == source_paper_id,
            Citation.target_paper_id == target_paper_id,
        )
        found = self.session.execute(q).scalar_one_or_none()
        if found:
            if context:
                found.context = context
            return
        self.session.add(
            Citation(
                source_paper_id=source_paper_id,
                target_paper_id=target_paper_id,
                context=context,
            )
        )

    def list_all(self, limit: int = 10000) -> list[Citation]:
        """
        查询所有引用关系（带分页限制）

        Args:
            limit: 最大返回数量，默认 10000

        Returns:
            引用关系列表
        """
        q = select(Citation).order_by(Citation.source_paper_id).limit(limit)
        return list(self.session.execute(q).scalars())

    def list_for_paper_ids(self, paper_ids: list[str]) -> list[Citation]:
        if not paper_ids:
            return []
        q = select(Citation).where(
            Citation.source_paper_id.in_(paper_ids) | Citation.target_paper_id.in_(paper_ids)
        )
        return list(self.session.execute(q).scalars())


class TopicRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_topics(self, enabled_only: bool = False) -> list[TopicSubscription]:
        q = select(TopicSubscription).order_by(TopicSubscription.created_at.desc())
        if enabled_only:
            q = q.where(TopicSubscription.enabled.is_(True))
        return list(self.session.execute(q).scalars())

    def get_by_name(self, name: str) -> TopicSubscription | None:
        q = select(TopicSubscription).where(TopicSubscription.name == name)
        return self.session.execute(q).scalar_one_or_none()

    def get_by_id(self, topic_id: str) -> TopicSubscription | None:
        return self.session.get(TopicSubscription, topic_id)

    def upsert_topic(
        self,
        *,
        name: str,
        query: str,
        enabled: bool = True,
        max_results_per_run: int = 20,
        retry_limit: int = 2,
        schedule_frequency: str = "daily",
        schedule_time_utc: int = 21,
        enable_date_filter: bool = False,
        date_filter_days: int = 7,
    ) -> TopicSubscription:
        found = self.get_by_name(name)
        if found:
            found.query = query
            found.enabled = enabled
            found.max_results_per_run = max(max_results_per_run, 1)
            found.retry_limit = max(retry_limit, 0)
            found.schedule_frequency = schedule_frequency
            found.schedule_time_utc = max(0, min(23, schedule_time_utc))
            found.enable_date_filter = enable_date_filter
            found.date_filter_days = max(1, date_filter_days)
            found.updated_at = datetime.now(UTC)
            self.session.flush()
            return found
        topic = TopicSubscription(
            name=name,
            query=query,
            enabled=enabled,
            max_results_per_run=max(max_results_per_run, 1),
            retry_limit=max(retry_limit, 0),
            schedule_frequency=schedule_frequency,
            schedule_time_utc=max(0, min(23, schedule_time_utc)),
            enable_date_filter=enable_date_filter,
            date_filter_days=max(1, date_filter_days),
        )
        self.session.add(topic)
        self.session.flush()
        return topic

    def update_topic(
        self,
        topic_id: str,
        *,
        query: str | None = None,
        enabled: bool | None = None,
        max_results_per_run: int | None = None,
        retry_limit: int | None = None,
        schedule_frequency: str | None = None,
        enable_date_filter: bool | None = None,
        date_filter_days: int | None = None,
        schedule_time_utc: int | None = None,
    ) -> TopicSubscription:
        topic = self.session.get(TopicSubscription, topic_id)
        if topic is None:
            raise ValueError(f"topic {topic_id} not found")
        if query is not None:
            topic.query = query
        if enabled is not None:
            topic.enabled = enabled
        if max_results_per_run is not None:
            topic.max_results_per_run = max(max_results_per_run, 1)
        if retry_limit is not None:
            topic.retry_limit = max(retry_limit, 0)
        if schedule_frequency is not None:
            topic.schedule_frequency = schedule_frequency
        if schedule_time_utc is not None:
            topic.schedule_time_utc = max(0, min(23, schedule_time_utc))
        if enable_date_filter is not None:
            topic.enable_date_filter = enable_date_filter
        if date_filter_days is not None:
            topic.date_filter_days = max(1, date_filter_days)
        topic.updated_at = datetime.now(UTC)
        self.session.flush()
        return topic

    def delete_topic(self, topic_id: str) -> None:
        topic = self.session.get(TopicSubscription, topic_id)
        if topic is not None:
            self.session.delete(topic)


class LLMConfigRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[LLMProviderConfig]:
        q = select(LLMProviderConfig).order_by(LLMProviderConfig.created_at.desc())
        return list(self.session.execute(q).scalars())

    def get_active(self) -> LLMProviderConfig | None:
        q = select(LLMProviderConfig).where(LLMProviderConfig.is_active.is_(True))
        return self.session.execute(q).scalar_one_or_none()

    def get_by_id(self, config_id: str) -> LLMProviderConfig:
        cfg = self.session.get(LLMProviderConfig, config_id)
        if cfg is None:
            raise ValueError(f"llm_config {config_id} not found")
        return cfg

    def create(
        self,
        *,
        name: str,
        provider: str,
        api_key: str,
        api_base_url: str | None,
        model_skim: str,
        model_deep: str,
        model_vision: str | None,
        model_embedding: str,
        model_fallback: str,
    ) -> LLMProviderConfig:
        cfg = LLMProviderConfig(
            name=name,
            provider=provider,
            api_key=api_key,
            api_base_url=api_base_url,
            model_skim=model_skim,
            model_deep=model_deep,
            model_vision=model_vision,
            model_embedding=model_embedding,
            model_fallback=model_fallback,
            is_active=False,
        )
        self.session.add(cfg)
        self.session.flush()
        return cfg

    def update(
        self,
        config_id: str,
        *,
        name: str | None = None,
        provider: str | None = None,
        api_key: str | None = None,
        api_base_url: str | None = None,
        model_skim: str | None = None,
        model_deep: str | None = None,
        model_vision: str | None = None,
        model_embedding: str | None = None,
        model_fallback: str | None = None,
    ) -> LLMProviderConfig:
        cfg = self.get_by_id(config_id)
        if name is not None:
            cfg.name = name
        if provider is not None:
            cfg.provider = provider
        if api_key is not None:
            cfg.api_key = api_key
        if api_base_url is not None:
            cfg.api_base_url = api_base_url
        if model_skim is not None:
            cfg.model_skim = model_skim
        if model_deep is not None:
            cfg.model_deep = model_deep
        if model_vision is not None:
            cfg.model_vision = model_vision
        if model_embedding is not None:
            cfg.model_embedding = model_embedding
        if model_fallback is not None:
            cfg.model_fallback = model_fallback
        cfg.updated_at = datetime.now(UTC)
        self.session.flush()
        return cfg

    def delete(self, config_id: str) -> None:
        cfg = self.session.get(LLMProviderConfig, config_id)
        if cfg is not None:
            self.session.delete(cfg)

    def activate(self, config_id: str) -> LLMProviderConfig:
        """激活指定配置，同时取消其他配置的激活状态"""
        all_cfgs = self.list_all()
        for c in all_cfgs:
            c.is_active = c.id == config_id
        self.session.flush()
        return self.get_by_id(config_id)

    def deactivate_all(self) -> None:
        """取消所有配置的激活状态（回退到 .env 默认配置）"""
        all_cfgs = self.list_all()
        for c in all_cfgs:
            c.is_active = False
        self.session.flush()


class GeneratedContentRepository:
    """持久化生成内容（Wiki / Brief）"""

    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        content_type: str,
        title: str,
        markdown: str,
        keyword: str | None = None,
        paper_id: str | None = None,
        metadata_json: dict | None = None,
    ) -> GeneratedContent:
        gc = GeneratedContent(
            content_type=content_type,
            title=title,
            markdown=markdown,
            keyword=keyword,
            paper_id=paper_id,
            metadata_json=metadata_json or {},
        )
        self.session.add(gc)
        self.session.flush()
        return gc

    def list_by_type(self, content_type: str, limit: int = 50) -> list[GeneratedContent]:
        q = (
            select(GeneratedContent)
            .where(GeneratedContent.content_type == content_type)
            .order_by(GeneratedContent.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(q).scalars())

    def get_by_id(self, content_id: str) -> GeneratedContent:
        gc = self.session.get(GeneratedContent, content_id)
        if gc is None:
            raise ValueError(f"generated_content {content_id} not found")
        return gc

    def delete(self, content_id: str) -> None:
        gc = self.session.get(GeneratedContent, content_id)
        if gc is not None:
            self.session.delete(gc)


class ActionRepository:
    """论文入库行动记录的数据仓储"""

    def __init__(self, session: Session):
        self.session = session

    def create_action(
        self,
        action_type: ActionType,
        title: str,
        paper_ids: list[str],
        query: str | None = None,
        topic_id: str | None = None,
    ) -> CollectionAction:
        """创建一条行动记录并关联论文"""
        action = CollectionAction(
            action_type=action_type,
            title=title,
            query=query,
            topic_id=topic_id,
            paper_count=len(paper_ids),
        )
        self.session.add(action)
        self.session.flush()

        # 批量插入关联论文
        action_papers = [ActionPaper(action_id=action.id, paper_id=pid) for pid in paper_ids]
        self.session.add_all(action_papers)
        self.session.flush()
        return action

    def list_actions(
        self,
        action_type: str | None = None,
        topic_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CollectionAction], int]:
        """分页列出行动记录"""
        base = select(CollectionAction)
        count_q = select(func.count()).select_from(CollectionAction)

        if action_type:
            base = base.where(CollectionAction.action_type == action_type)
            count_q = count_q.where(CollectionAction.action_type == action_type)
        if topic_id:
            base = base.where(CollectionAction.topic_id == topic_id)
            count_q = count_q.where(CollectionAction.topic_id == topic_id)

        total = self.session.execute(count_q).scalar() or 0
        rows = (
            self.session.execute(
                base.order_by(CollectionAction.created_at.desc()).limit(limit).offset(offset)
            )
            .scalars()
            .all()
        )
        return list(rows), total

    def get_action(self, action_id: str) -> CollectionAction | None:
        return self.session.get(CollectionAction, action_id)

    def get_paper_ids_by_action(self, action_id: str) -> list[str]:
        """获取某次行动关联的所有论文 ID"""
        rows = (
            self.session.execute(
                select(ActionPaper.paper_id).where(ActionPaper.action_id == action_id)
            )
            .scalars()
            .all()
        )
        return list(rows)

    def get_papers_by_action(
        self,
        action_id: str,
        limit: int = 200,
    ) -> list[Paper]:
        """获取某次行动关联的论文列表"""
        rows = (
            self.session.execute(
                select(Paper)
                .join(ActionPaper, Paper.id == ActionPaper.paper_id)
                .where(ActionPaper.action_id == action_id)
                .order_by(Paper.created_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return list(rows)


class EmailConfigRepository:
    """邮箱配置仓储"""

    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[EmailConfig]:
        """获取所有邮箱配置"""
        q = select(EmailConfig).order_by(EmailConfig.created_at.desc())
        return list(self.session.execute(q).scalars())

    def get_active(self) -> EmailConfig | None:
        """获取激活的邮箱配置"""
        q = select(EmailConfig).where(EmailConfig.is_active == True)
        return self.session.execute(q).scalar_one_or_none()

    def get_by_id(self, config_id: str) -> EmailConfig | None:
        """根据 ID 获取配置"""
        return self.session.get(EmailConfig, config_id)

    def create(
        self,
        name: str,
        smtp_server: str,
        smtp_port: int,
        smtp_use_tls: bool,
        sender_email: str,
        sender_name: str,
        username: str,
        password: str,
    ) -> EmailConfig:
        """创建邮箱配置"""
        config = EmailConfig(
            name=name,
            smtp_server=smtp_server,
            smtp_port=smtp_port,
            smtp_use_tls=smtp_use_tls,
            sender_email=sender_email,
            sender_name=sender_name,
            username=username,
            password=password,
        )
        self.session.add(config)
        self.session.flush()
        return config

    def update(self, config_id: str, **kwargs) -> EmailConfig | None:
        """更新邮箱配置"""
        config = self.get_by_id(config_id)
        if config:
            for key, value in kwargs.items():
                if hasattr(config, key):
                    setattr(config, key, value)
            self.session.flush()
        return config

    def delete(self, config_id: str) -> bool:
        """删除邮箱配置"""
        config = self.get_by_id(config_id)
        if config:
            self.session.delete(config)
            self.session.flush()
            return True
        return False

    def set_active(self, config_id: str) -> EmailConfig | None:
        """激活指定配置，取消其他配置的激活状态"""
        all_configs = self.list_all()
        for cfg in all_configs:
            cfg.is_active = False
        config = self.get_by_id(config_id)
        if config:
            config.is_active = True
            self.session.flush()
        return config


# ========== Agent 对话相关 ==========


class AgentConversationRepository:
    """Agent 对话会话 Repository"""

    def __init__(self, session: Session):
        self.session = session

    def create(self, user_id: str | None = None, title: str | None = None) -> AgentConversation:
        """创建新会话"""
        conv = AgentConversation(user_id=user_id, title=title)
        self.session.add(conv)
        self.session.flush()
        return conv

    def get_by_id(self, conv_id: str) -> AgentConversation | None:
        """根据 ID 获取会话"""
        return self.session.get(AgentConversation, conv_id)

    def list_all(self, user_id: str | None = None, limit: int = 50) -> list[AgentConversation]:
        """获取所有会话（按时间倒序）"""
        q = select(AgentConversation).order_by(AgentConversation.updated_at.desc()).limit(limit)
        return list(self.session.execute(q).scalars())

    def update_title(self, conv_id: str, title: str) -> AgentConversation | None:
        """更新会话标题"""
        conv = self.get_by_id(conv_id)
        if conv:
            conv.title = title
            self.session.flush()
        return conv

    def delete(self, conv_id: str) -> bool:
        """删除会话"""
        conv = self.get_by_id(conv_id)
        if conv:
            self.session.delete(conv)
            self.session.flush()
            return True
        return False


class AgentMessageRepository:
    """Agent 对话消息 Repository"""

    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        conversation_id: str,
        role: str,
        content: str,
        meta: dict | None = None,
    ) -> AgentMessage:
        """创建消息"""
        msg = AgentMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            meta=meta,
        )
        self.session.add(msg)
        self.session.flush()
        return msg

    def list_by_conversation(self, conversation_id: str, limit: int = 100) -> list[AgentMessage]:
        """获取会话的所有消息"""
        q = (
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation_id)
            .order_by(AgentMessage.created_at.asc())
            .limit(limit)
        )
        return list(self.session.execute(q).scalars())

    def delete_by_conversation(self, conversation_id: str) -> int:
        """删除会话的所有消息"""
        q = delete(AgentMessage).where(AgentMessage.conversation_id == conversation_id)
        result = self.session.execute(q)
        self.session.flush()
        return result.rowcount


class DailyReportConfigRepository:
    """每日报告配置仓储"""

    def __init__(self, session: Session):
        self.session = session

    def get_config(self) -> DailyReportConfig:
        """获取每日报告配置（单例）"""
        config = self.session.execute(select(DailyReportConfig)).scalar_one_or_none()

        if not config:
            # 创建默认配置
            config = DailyReportConfig()
            self.session.add(config)
            self.session.flush()

        return config

    def update_config(self, **kwargs) -> DailyReportConfig:
        """更新每日报告配置"""
        config = self.get_config()
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        return config


class IeeeQuotaRepository:
    """IEEE API 配额管理 Repository"""

    def __init__(self, session: Session):
        from packages.storage.models import IeeeApiQuota

        self.session = session
        self.IeeeApiQuota = IeeeApiQuota

    def get_or_create(self, topic_id: str, date: date, limit: int = 50) -> IeeeApiQuota:
        """获取或创建当日配额记录"""
        from sqlalchemy import select

        q = select(self.IeeeApiQuota).where(
            self.IeeeApiQuota.topic_id == topic_id,
            self.IeeeApiQuota.date == date,
        )
        quota = self.session.execute(q).scalar_one_or_none()

        if not quota:
            quota = self.IeeeApiQuota(
                topic_id=topic_id,
                date=date,
                api_calls_used=0,
                api_calls_limit=limit,
            )
            self.session.add(quota)
            self.session.flush()

        return quota

    def check_quota(self, topic_id: str, date: date, limit: int = 50) -> bool:
        """检查是否还有配额"""
        quota = self.get_or_create(topic_id, date, limit)
        return quota.api_calls_used < quota.api_calls_limit

    def consume_quota(self, topic_id: str, date: date, amount: int = 1) -> bool:
        """消耗配额"""
        quota = self.get_or_create(topic_id, date)

        if quota.api_calls_used + amount > quota.api_calls_limit:
            return False

        quota.api_calls_used += amount
        self.session.flush()
        return True

    def get_remaining(self, topic_id: str, date: date) -> int:
        """获取剩余配额"""
        quota = self.get_or_create(topic_id, date)
        return max(0, quota.api_calls_limit - quota.api_calls_used)

    def reset_quota(self, topic_id: str, date: date, new_limit: int = 50) -> None:
        """重置配额"""
        quota = self.get_or_create(topic_id, date, new_limit)
        quota.api_calls_used = 0
        quota.api_calls_limit = new_limit
        quota.last_reset_at = datetime.now(UTC)
        self.session.flush()


class AgentPendingActionRepository:
    """Agent 待确认操作持久化 Repository"""

    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        action_id: str,
        tool_name: str,
        tool_args: dict,
        tool_call_id: str | None = None,
        conversation_id: str | None = None,
        conversation_state: dict | None = None,
    ) -> AgentPendingAction:
        """创建待确认操作"""
        action = AgentPendingAction(
            id=action_id,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_call_id=tool_call_id,
            conversation_id=conversation_id,
            conversation_state=conversation_state,
        )
        self.session.add(action)
        self.session.flush()
        return action

    def get_by_id(self, action_id: str) -> AgentPendingAction | None:
        """根据 ID 获取待确认操作"""
        return self.session.get(AgentPendingAction, action_id)

    def delete(self, action_id: str) -> bool:
        """删除待确认操作"""
        action = self.get_by_id(action_id)
        if action:
            self.session.delete(action)
            self.session.flush()
            return True
        return False

    def cleanup_expired(self, ttl_seconds: int = 1800) -> int:
        """清理过期的待确认操作"""
        cutoff = datetime.now(UTC) - timedelta(seconds=ttl_seconds)
        q = delete(AgentPendingAction).where(AgentPendingAction.created_at < cutoff)
        result = self.session.execute(q)
        self.session.flush()
        return result.rowcount


class CSFeedRepository:
    """arXiv CS 分类订阅 Repository"""

    def __init__(self, session: Session):
        self.session = session

    def get_categories(self) -> list[CSCategory]:
        return list(self.session.execute(select(CSCategory)).scalars())

    def upsert_category(self, code: str, name: str, description: str = "") -> CSCategory:
        existing = self.session.execute(
            select(CSCategory).where(CSCategory.code == code)
        ).scalar_one_or_none()
        if existing:
            existing.name = name
            existing.description = description
            existing.cached_at = datetime.now(UTC)
            return existing
        cat = CSCategory(code=code, name=name, description=description)
        self.session.add(cat)
        self.session.commit()
        return cat

    def get_subscriptions(self) -> list[CSFeedSubscription]:
        return list(self.session.execute(select(CSFeedSubscription)).scalars())

    def get_subscription(self, category_code: str) -> CSFeedSubscription | None:
        return self.session.execute(
            select(CSFeedSubscription).where(CSFeedSubscription.category_code == category_code)
        ).scalar_one_or_none()

    def upsert_subscription(
        self, category_code: str, daily_limit: int, enabled: bool = True
    ) -> CSFeedSubscription:
        existing = self.get_subscription(category_code)
        if existing:
            existing.daily_limit = daily_limit
            existing.enabled = enabled
            self.session.commit()
            return existing
        sub = CSFeedSubscription(
            category_code=category_code, daily_limit=daily_limit, enabled=enabled
        )
        self.session.add(sub)
        self.session.commit()
        return sub

    def delete_subscription(self, category_code: str) -> bool:
        sub = self.get_subscription(category_code)
        if sub:
            self.session.delete(sub)
            self.session.commit()
            return True
        return False

    def update_run_status(self, category_code: str, count: int):
        sub = self.get_subscription(category_code)
        if sub:
            sub.last_run_at = datetime.now(UTC)
            sub.last_run_count = count
            sub.status = "active"
            self.session.commit()

    def set_cool_down(self, category_code: str, until: datetime):
        sub = self.get_subscription(category_code)
        if sub:
            sub.status = "cool_down"
            sub.cool_down_until = until
            self.session.commit()

    def get_active_subscriptions(self) -> list[CSFeedSubscription]:
        return list(
            self.session.execute(
                select(CSFeedSubscription).where(CSFeedSubscription.enabled == True)
            ).scalars()
        )
