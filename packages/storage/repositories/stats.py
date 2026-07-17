"""
论文统计分析查询 —— 分析聚合，非 CRUD
@author Color2333
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from sqlalchemy import Integer, func, select, text

from packages.storage.db import _is_sqlite
from packages.storage.models import (
    CollectionAction,
    Paper,
    PaperTopic,
    TopicSubscription,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _json_field(column, key: str):
    """方言通用的 JSON 字段提取：SQLite 用 json_extract，PG 用 ->> 。"""
    if _is_sqlite:
        return func.json_extract(column, f"$.{key}")
    # PG: metadata_json->>'key'（jsonb/json 文本取值）
    return column[key].astext


def _date_trunc_day(column, offset_hours: float):
    """方言通用的"按用户时区取日期"：SQLite 用 datetime(date(+N));PG 用 date + interval。"""
    offset_str = f"{offset_hours:+.0f} hours"
    if _is_sqlite:
        return func.date(func.datetime(column, offset_str))
    # PG: (created_at + interval 'N hours')::date
    return func.cast(column + text(f"interval '{offset_str}'"), text("date"))


def _year_of(column):
    """方言通用的取年份：SQLite strftime('%Y',x)；PG to_char(x,'YYYY')。"""
    if _is_sqlite:
        return func.strftime("%Y", column)
    return func.to_char(column, "YYYY")


def get_folder_stats(session: Session) -> dict:
    """返回文件夹统计：按主题、收藏、最近、未分类"""
    from packages.timezone import user_today_start_utc, utc_offset_hours

    total_q = select(func.count()).select_from(Paper)
    total = session.execute(total_q).scalar() or 0

    fav_q = select(func.count()).select_from(Paper).where(Paper.favorited == True)  # noqa: E712
    favorites = session.execute(fav_q).scalar() or 0

    # "最近 7 天" 用用户时区的今天 0 点往前推 7 天
    user_today_utc = user_today_start_utc()
    week_start_utc = user_today_utc - timedelta(days=7)
    recent_q = select(func.count()).select_from(Paper).where(Paper.created_at >= week_start_utc)
    recent_7d = session.execute(recent_q).scalar() or 0

    # 有主题的论文 ID 集合
    has_topic_q = select(func.count(func.distinct(PaperTopic.paper_id)))
    has_topic = session.execute(has_topic_q).scalar() or 0
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
    topic_rows = session.execute(topic_counts_q).all()
    by_topic = [{"topic_id": r[0], "topic_name": r[1], "count": r[2]} for r in topic_rows]

    # 按阅读状态统计
    status_q = select(Paper.read_status, func.count()).group_by(Paper.read_status)
    status_rows = session.execute(status_q).all()
    by_status = {r[0].value: r[1] for r in status_rows}

    # 按日期分组（最近 30 天），用用户时区偏移
    # 方言通用：SQLite datetime(created_at,'+N hours');PG (created_at + interval 'N hours')::date
    offset_h = utc_offset_hours()
    date_expr = _date_trunc_day(Paper.created_at, offset_h)
    since_30d = user_today_utc - timedelta(days=30)
    date_q = (
        select(date_expr.label("d"), func.count().label("c"))
        .where(Paper.created_at >= since_30d)
        .group_by(date_expr)
        .order_by(date_expr.desc())
    )
    date_rows = session.execute(date_q).all()
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


def get_topic_stats(session: Session) -> dict:
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
    topic_rows = session.execute(topic_stats_q).all()

    # 提取所有 topic_id 用于批量查询
    topic_ids = [row.id for row in topic_rows]
    if not topic_ids:
        return {"topics": []}

    # 2. 批量查询所有主题的总引用数（一次查询，GROUP BY topic_id）
    citation_subq = (
        select(
            PaperTopic.topic_id,
            func.coalesce(
                func.sum(func.cast(_json_field(Paper.metadata_json, "citation_count"), Integer)),
                0,
            ).label("total_citations"),
        )
        .join(Paper, Paper.id == PaperTopic.paper_id)
        .group_by(PaperTopic.topic_id)
        .subquery()
    )
    citation_rows = {row[0]: row[1] for row in session.execute(select(citation_subq)).all()}

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
    recent_rows = {row[0]: row[1] for row in session.execute(select(recent_subq)).all()}

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
    status_rows = session.execute(select(status_subq)).all()
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


def get_paper_distribution_stats(session: Session) -> dict:
    """论文分布统计：按发表年份分布 + 按来源分布"""
    from packages.timezone import user_today_start_utc

    by_year_q = (
        select(
            func.coalesce(_year_of(Paper.publication_date), "未知").label("year"),
            func.count().label("count"),
        )
        .group_by(_year_of(Paper.publication_date))
        .order_by(_year_of(Paper.publication_date).desc())
    )
    year_rows = session.execute(by_year_q).all()
    by_year = [{"year": r[0], "count": r[1]} for r in year_rows]

    by_source_q = (
        select(
            func.coalesce(_json_field(Paper.metadata_json, "source"), "unknown").label("source"),
            func.count().label("count"),
        )
        .group_by(_json_field(Paper.metadata_json, "source"))
        .order_by(func.count().desc())
    )
    source_rows = session.execute(by_source_q).all()
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
    status_rows = session.execute(by_status_q).all()
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
        count = session.execute(count_q).scalar() or 0
        by_month_rows.append({"month": month_label, "count": count})

    by_venue_q = (
        select(
            func.coalesce(_json_field(Paper.metadata_json, "venue"), "未知").label("venue"),
            func.count().label("count"),
        )
        .where(_json_field(Paper.metadata_json, "venue").is_not(None))
        .group_by(_json_field(Paper.metadata_json, "venue"))
        .order_by(func.count().desc())
        .limit(15)
    )
    venue_rows = session.execute(by_venue_q).all()
    by_venue = [{"venue": r[0], "count": r[1]} for r in venue_rows if r[0]]

    action_source_q = (
        select(
            CollectionAction.action_type,
            func.sum(CollectionAction.paper_count).label("total"),
        )
        .group_by(CollectionAction.action_type)
        .order_by(func.sum(CollectionAction.paper_count).desc())
    )
    action_rows = session.execute(action_source_q).all()
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
