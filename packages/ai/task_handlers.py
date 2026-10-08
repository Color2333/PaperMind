"""durable Task handler 集合（C3 退出门：全部长任务的唯一执行体）

约定：每个 handler 是模块级函数，签名 `fn(*, progress=None, **input_keys)`；
- `progress(msg, current, total)` 由 Executor 注入（经 Go Core 协议上报，
  同时续约 lease——executor 不直写任务状态）；
- `cancel_check`（如 handler 接受）在安全检查点探测协作取消，置位时抛
  `TaskCancelledError`；
- handler 不捕获任务级异常（失败交给 durable store 的重试/dead_letter 语义）；
- 重试退避由 Task 层负责，handler 内不再自做 retry。

C4 注册表（TASK_CAPABILITIES）的 handler dotted path 全部指向本模块或既有
服务类方法；调用点不得再绑定闭包。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from packages.domain.schemas import PaperCreate

from packages.executor_runtime.runner import TaskCancelledError

logger = logging.getLogger(__name__)

ProgressFn = Callable[[str, int, int], None] | None


def _checked(cancel_check: Callable[[], bool] | None) -> None:
    """安全检查点：协作取消置位则抛 TaskCancelledError"""
    if cancel_check is not None and cancel_check():
        raise TaskCancelledError("协作取消（handler 安全点）")


# ---------- 每日/维护 ----------


def daily_ingest_and_brief(*, progress: ProgressFn = None, **_: Any) -> dict:
    """每日抓取 + 简报（StartDailyIngest / RunDailyJob 共用）"""
    from packages.ai.daily_runner import run_daily_brief, run_daily_ingest

    if progress:
        progress("正在执行订阅收集...", 10, 100)
    ingest = run_daily_ingest()
    if progress:
        progress("正在生成每日简报...", 70, 100)
    brief = run_daily_brief()
    if progress:
        progress("每日任务完成", 100, 100)
    return {"ingest": ingest, "brief": brief}


def weekly_graph_maintenance(*, progress: ProgressFn = None, **_: Any) -> dict:
    """每周图维护（任务链编排器）：逐主题提交 sync_citations_topic + 增量
    sync_citations_incremental 任务（均为 A 档，引用边在权威面单事务 apply），
    本 handler 只提交 + 轮询观察面，不再内联调 GraphService 直写。"""
    from packages.ai.daily_runner import _wait_tasks
    from packages.storage.db import session_scope
    from packages.storage.repositories import TopicRepository

    if progress:
        progress("正在获取主题列表...", 10, 100)
    with session_scope() as session:
        topics = TopicRepository(session).list_topics(enabled_only=True)

    total_topics = len(topics)
    task_ids: list[str] = []
    for i, t in enumerate(topics):
        if progress:
            progress(
                f"提交主题引用同步 {i + 1}/{total_topics}: {t.name[:20]}...",
                10 + int((i + 1) / max(total_topics, 1) * 30),
                100,
            )
        try:
            from packages.application.commands.jobs import submit_job

            submitted = submit_job(
                kind="CoreTask",
                capability="sync_citations_topic",
                title=f"引用同步 {t.name[:30]}",
                input_ref={"topic_id": str(t.id), "paper_limit": 20, "edge_limit_per_paper": 6},
                idempotency_key=None,
                created_by="weekly_graph",
            )
            task_ids.append(submitted["task_id"])
        except Exception:
            logger.exception("Failed to submit citation sync for topic %s", t.id)
            continue

    try:
        from packages.application.commands.jobs import submit_job

        incremental_submitted = submit_job(
            kind="CoreTask",
            capability="sync_citations_incremental",
            title="增量引用同步",
            input_ref={"paper_limit": 50, "edge_limit_per_paper": 6},
            idempotency_key=None,
            created_by="weekly_graph",
        )
        task_ids.append(incremental_submitted["task_id"])
    except Exception:
        logger.exception("Failed to submit incremental citation sync")

    if progress:
        progress(f"等待 {len(task_ids)} 个同步任务完成...", 45, 100)
    unfinished = _wait_tasks(
        task_ids,
        timeout_s=3600.0,
        progress=progress,
        base=45,
        span=50,
    )
    if progress:
        progress("图维护完成", 95, 100)
    return {
        "submitted": len(task_ids),
        "unfinished": len(unfinished),
    }


def daily_report_workflow(*, progress: ProgressFn = None, **_: Any) -> dict:
    """每日报告完整工作流（精读 + 生成 + 发邮件）"""
    from packages.ai.auto_read_service import AutoReadService

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(AutoReadService().run_daily_workflow(progress))
    finally:
        loop.close()


def daily_report_send_only(
    *, recipient: str | None = None, progress: ProgressFn = None, **_: Any
) -> dict:
    """快速发送模式（跳过精读，直接生成简报并发邮件）"""
    from packages.ai.auto_read_service import AutoReadService

    recipients = [e.strip() for e in recipient.split(",") if e.strip()] if recipient else None
    return AutoReadService().send_only(recipients, progress)


def batch_process_unread(
    *,
    max_papers: int = 50,
    progress: ProgressFn = None,
    cancel_check: Callable[[], bool] | None = None,
    **_: Any,
) -> dict:
    """批量处理未读论文（去重第二刀：改提交任务链）。

    原内联线程池直调 embed/skim/deep_dive（直写领域 + 自建并发/配额）——与
    A 档任务链双轨。现改为：未读论文逐篇提交 embed_paper + skim_paper 任务；
    粗读分数达阈值的精读决策由 skim proposal apply 后的 score 判定承接
    （任务完成后经任务链提交 deep_read_paper，配额由队列优先级承载）。
    失败不抛（提交失败计数），不阻断批次。

    Returns:
        {submitted, skipped}——处理进度经 JobMonitor 任务图观测。
    """
    from packages.application.commands.jobs import submit_job
    from packages.domain.enums import ReadStatus
    from packages.storage.db import session_scope
    from packages.storage.repositories import PaperRepository

    submitted = 0
    skipped = 0
    with session_scope() as session:
        unread = PaperRepository(session).list_by_read_status(ReadStatus.unread, limit=max_papers)
        paper_ids = [str(p.id) for p in unread]

    for i_, pid in enumerate(paper_ids, 1):
        if cancel_check and cancel_check():
            break
        if progress:
            with suppress(Exception):
                progress(f"提交处理任务 {i_}/{len(paper_ids)}", i_, len(paper_ids))
        try:
            submit_job(
                kind="CoreTask",
                capability="embed_paper",
                title=f"批量嵌入 {pid[:8]}",
                input_ref={"paper_id": pid},
                created_by="batch_unread",
            )
            submit_job(
                kind="CoreTask",
                capability="skim_paper",
                title=f"批量粗读 {pid[:8]}",
                input_ref={"paper_id": pid},
                created_by="batch_unread",
            )
            submitted += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("batch submit %s failed: %s", pid[:8], exc)
            skipped += 1

    return {"submitted": submitted, "skipped": skipped}


def skim_papers_batch(
    *,
    paper_ids: list[str],
    progress: ProgressFn = None,
    cancel_check: Callable[[], bool] | None = None,
    **_: Any,
) -> dict:
    """批量粗读（去重第五刀：改提交 skim_paper 任务链，原内联直写退役）。

    逐篇提交 skim_paper 任务（manifest A 档，Go 权威调度 + 单事务 apply）；
    单篇提交失败不阻断批次。
    """
    from packages.application.commands.jobs import submit_job

    ok, failed = 0, 0
    for i_, pid in enumerate(paper_ids, 1):
        if cancel_check and cancel_check():
            break
        if progress:
            with suppress(Exception):
                progress(f"提交粗读 {i_}/{len(paper_ids)}", i_, len(paper_ids))
        try:
            submit_job(
                kind="CoreTask",
                capability="skim_paper",
                title=f"批量粗读 {str(pid)[:8]}",
                input_ref={"paper_id": str(pid)},
                created_by="skim_batch",
            )
            ok += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            logger.warning("batch skim submit %s failed: %s", str(pid)[:8], exc)
    return {"skimmed": ok, "failed": failed, "skipped": 0, "total": len(paper_ids)}


def topic_dispatch(*, progress: ProgressFn = None, **_: Any) -> dict:
    """主题调度触发（每小时）：按订阅计划逐主题抓取（自 apps/worker 迁入）"""
    from datetime import UTC, datetime

    from packages.ai.daily_runner import run_topic_ingest
    from packages.ai.idle_processor import set_dispatching
    from packages.storage.db import session_scope
    from packages.storage.repositories import TopicRepository

    def _should_run(freq: str, time_utc: int, hour: int, weekday: int) -> bool:
        if freq == "hourly":
            return True
        if freq == "twice_daily":
            return hour in (time_utc, (time_utc + 12) % 24)
        if freq == "weekdays":
            return weekday < 5 and hour == time_utc
        if freq == "weekly":
            return weekday == 0 and hour == time_utc
        return hour == time_utc  # daily

    now = datetime.now(UTC)
    hour, weekday = now.hour, now.weekday()
    with session_scope() as session:
        topics = TopicRepository(session).list_topics(enabled_only=True)
        candidates = [
            {"id": t.id, "name": t.name}
            for t in topics
            if _should_run(
                getattr(t, "schedule_frequency", "daily"),
                getattr(t, "schedule_time_utc", 21),
                hour,
                weekday,
            )
        ]
    if not candidates:
        return {"triggered": 0, "failed": []}

    if progress:
        progress(f"触发 {len(candidates)} 个主题抓取", 10, 100)
    set_dispatching(True)
    failures: list[str] = []
    try:
        for i, c in enumerate(candidates):
            if progress:
                progress(
                    f"主题 {c['name'][:20]} ({i + 1}/{len(candidates)})",
                    10 + int(i / len(candidates) * 80),
                    100,
                )
            try:
                run_topic_ingest(c["id"])
            except Exception as exc:
                logger.exception("topic_dispatch failed for %s", c["name"])
                failures.append(f"{c['name']}: {exc}")
    finally:
        set_dispatching(False)
    return {"triggered": len(candidates), "failed": failures}


def cs_feed_dispatch(
    *, progress: ProgressFn = None, cancel_check: Callable[[], bool] | None = None, **_: Any
) -> dict:
    """CS 分类订阅调度（每小时，任务链编排器）。

    分类表经 cs_categories_sync proposal 在权威面落库；到点订阅逐个提交
    cs_feed_fetch_category 任务（A 档，papers + 主题 + 运行状态单事务 apply）。
    冷却/每日配额检查保留在编排器（提交前过滤）；arXiv 限流由串行领取 +
    ArxivClient 内建退避承接（原 token bucket/REQUEST_INTERVAL 随内联抓取退役）。
    """
    from datetime import UTC, datetime

    from packages.integrations.arxiv_client import ArxivClient
    from packages.storage.db import session_scope
    from packages.storage.repositories import CSFeedRepository

    if progress:
        progress("拉取 CS 分类...", 5, 100)
    try:
        cats = ArxivClient().fetch_categories()
    except Exception as exc:
        logger.warning("CS 分类拉取失败（跳过同步，不影响订阅抓取）: %s", exc)
        cats = []

    if progress:
        progress("筛选到点订阅...", 30, 100)
    now = datetime.now(UTC)
    with session_scope() as session:
        subs = CSFeedRepository(session).get_active_subscriptions()
        specs = [
            (
                s.category_code,
                s.status,
                s.cool_down_until,
                s.last_run_at,
                s.last_run_count,
                s.daily_limit,
            )
            for s in subs
        ]

    from packages.application.commands.jobs import submit_job

    submitted, skipped = 0, 0
    for category_code, status, cool_down_until, last_run_at, last_run_count, daily_limit in specs:
        if cancel_check and cancel_check():
            break
        if status == "cool_down" and cool_down_until and now < cool_down_until:
            skipped += 1
            continue
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        remaining = (
            daily_limit - last_run_count
            if (last_run_at and last_run_at >= today_start)
            else daily_limit
        )
        if remaining <= 0:
            skipped += 1
            continue
        if progress:
            progress(
                f"提交抓取 {category_code}...", 40 + int(submitted / max(len(specs), 1) * 50), 100
            )
        try:
            submit_job(
                kind="CoreTask",
                capability="cs_feed_fetch_category",
                title=f"📥 抓取分类: {category_code}",
                input_ref={"category_code": category_code},
                idempotency_key=None,
                created_by="cs_feed_dispatch",
            )
            submitted += 1
        except Exception:
            logger.exception("cs_feed_fetch 提交失败: %s", category_code)
            skipped += 1

    if progress:
        progress(f"已提交 {submitted} 个分类抓取", 95, 100)
    return {
        "proposal": {
            "kind": "cs_categories_sync",
            "categories": [
                {
                    "code": c.get("code", ""),
                    "name": c.get("name", ""),
                    "description": c.get("description", ""),
                }
                for c in cats
            ],
        },
        "submitted": submitted,
        "skipped": skipped,
    }


def fetch_topic_papers(*, topic_id: str, progress: ProgressFn = None, **_: Any) -> dict:
    """手动触发单个订阅抓取（分阶段进度：抓取 0-50% → 处理 50-100%）"""
    from packages.ai.daily_runner import run_topic_ingest

    def _stage(msg, cur, tot):
        if progress:
            progress(f"抓取：{msg}", int(cur / tot * 50) if tot else 0, 100)

    result = run_topic_ingest(topic_id, progress_callback=_stage)
    if progress:
        progress("处理完成", 100, 100)
    return result


def _ingest_papers_proposal(
    *,
    query: str,
    papers: list,
    topic_id: str | None,
    topic_name: str | None,
    action_type: str,
    action_title: str,
) -> dict:
    """入库 proposal 公共封装（ingest_arxiv_query / import_selected 共用）。

    领域写（papers upsert / paper_topics / topic_subscriptions 自动创建 /
    collection_actions）在权威面单事务执行：Go applyIngestPapersResult（A 档）
    或 domain_apply.apply_ingest_papers_proposal（Python authority 回退）。
    """
    return {
        "proposal": {
            "kind": "ingest_papers",
            "query": query,
            "topic_id": topic_id,
            "topic_name": topic_name,
            "action_type": action_type,
            "action_title": action_title,
            "papers": [p.model_dump(mode="json") for p in papers],
        }
    }


def ingest_arxiv_query_proposal(
    *,
    query: str,
    max_results: int = 20,
    topic_id: str | None = None,
    sort_by: str = "submittedDate",
    days_back: int = 7,
    action_type: str = "manual_collect",
    progress: ProgressFn = None,
    **_: Any,
) -> dict:
    """按关键词抓取 arXiv 候选（纯计算 + 只读去重）——入库 proposal 模式。

    保留原"分批递归抓取直到凑够 max_results 篇新论文"语义；DB 访问仅
    list_existing_arxiv_ids（只读）。领域写全部移入权威面。
    """
    import time as _time

    from packages.integrations.arxiv_client import ArxivClient
    from packages.storage.db import session_scope
    from packages.storage.repositories import PaperRepository

    arxiv = ArxivClient()
    selected: list[PaperCreate] = []
    selected_ids: set[str] = set()
    batch_size = 20
    max_pages = 10
    arxiv_request_delay = 3.0

    with session_scope() as session:
        existing_all: set[str] = set()

        for page in range(max_pages):
            if len(selected) >= max_results:
                break
            start = page * batch_size
            needed = max_results - len(selected)
            this_batch = min(batch_size, needed + 20)
            if progress:
                with suppress(Exception):
                    progress(f"抓取第 {page + 1}/{max_pages} 批", page + 1, max_pages)

            papers = arxiv.fetch_latest(
                query=query,
                max_results=this_batch,
                sort_by=sort_by,
                start=start,
                days_back=days_back,
            )
            if not papers:
                break
            existing = PaperRepository(session).list_existing_arxiv_ids(
                [p.arxiv_id for p in papers]
            )
            existing_all |= existing
            for paper in papers:
                if paper.arxiv_id not in existing and paper.arxiv_id not in selected_ids:
                    selected.append(paper)
                    selected_ids.add(paper.arxiv_id)
                    if len(selected) >= max_results:
                        break
            if page < max_pages - 1 and papers:
                _time.sleep(arxiv_request_delay)

    del existing_all
    if progress:
        with suppress(Exception):
            progress(f"抓取完成：{len(selected)} 篇新论文", len(selected), max(max_results, 1))
    return _ingest_papers_proposal(
        query=query,
        papers=selected,
        topic_id=topic_id,
        topic_name=None,
        action_type=action_type,
        action_title=f"收集：{query[:80]}",
    )


def import_selected_proposal(
    *, arxiv_ids: list[str], query: str, progress: ProgressFn = None, **_: Any
) -> dict:
    """按选中 ID 抓取元数据（纯计算）——入库 proposal 模式。

    topic 自动创建 / 论文入库 / 收集记录在权威面单事务执行。此前的内联
    PDF 下载与自动 embed/skim 线程池随 proposal 模式移除（后续任务编排
    由 workflow 展开机制承载）。
    """
    from packages.integrations.arxiv_client import ArxivClient

    arxiv = ArxivClient()
    selected_set = set(arxiv_ids)
    selected = [
        p for p in arxiv.fetch_latest(query=query, max_results=50) if p.arxiv_id in selected_set
    ]
    found_ids = {p.arxiv_id for p in selected}
    missing_ids = selected_set - found_ids
    if missing_ids:
        with suppress(Exception):
            selected.extend(arxiv.fetch_by_ids(list(missing_ids)))
    if progress:
        with suppress(Exception):
            progress(
                f"已获取 {len(selected)}/{len(selected_set)} 篇元数据",
                len(selected),
                max(len(selected_set), 1),
            )
    return _ingest_papers_proposal(
        query=query,
        papers=selected,
        topic_id=None,
        topic_name=query.strip() or None,
        action_type="agent_collect",
        action_title=f"Agent 收集: {query[:80]}",
    )


def ingest_arxiv_query(
    *,
    query: str,
    max_results: int = 20,
    topic_id: str | None = None,
    sort_by: str = "submittedDate",
    days_back: int = 7,
    progress: ProgressFn = None,
    **_: Any,
) -> dict:
    """[已退役直写路径] 兼容保留：转调 proposal 模式"""
    return ingest_arxiv_query_proposal(
        query=query,
        max_results=max_results,
        topic_id=topic_id,
        sort_by=sort_by,
        days_back=days_back,
        progress=progress,
    )


def import_selected(
    *, arxiv_ids: list[str], query: str, progress: ProgressFn = None, **_: Any
) -> dict:
    """[已退役直写路径] 兼容保留：转调 proposal 模式"""
    return import_selected_proposal(arxiv_ids=arxiv_ids, query=query, progress=progress)


def ingest_ieee_proposal(
    *,
    query: str,
    max_results: int = 20,
    topic_id: str | None = None,
    action_type: str = "manual_collect",
    progress: ProgressFn = None,
    **_: Any,
) -> dict:
    """按关键词抓取 IEEE 候选（纯计算 + 只读去重）——入库 proposal 模式。

    IeeeClient.fetch_by_keywords 网络计算留在 handler；papers 复用 ingest_papers
    proposal → 权威面单事务 apply（Go applyIngestPapersResult / Python
    domain_apply）。非 arXiv 源沿用 PaperRepository.upsert_paper 的合成键约定
    （arxiv_id="ieee:<source_id>"）；DOI 或合成键已命中的论文在只读阶段过滤
    （与旧 IEEE 直写路径语义一致）。IEEE PDF 下载不在此处（权限限制，维持原状）。
    """
    from packages.integrations.ieee_client import IeeeClient
    from packages.storage.db import session_scope
    from packages.storage.repositories import PaperRepository

    ieee = IeeeClient()
    if not ieee.api_key:
        raise RuntimeError("IEEE API Key 未配置，请设置 IEEE_API_KEY 环境变量")

    if progress:
        with suppress(Exception):
            progress("IEEE 检索中...", 0, max(max_results, 1))
    fetched = ieee.fetch_by_keywords(query=query, max_results=max_results)

    with session_scope() as session:
        repo = PaperRepository(session)
        dois = [p.doi for p in fetched if p.doi]
        existing_dois = repo.list_existing_dois(dois) if dois else set()
        keys = [f"ieee:{p.source_id}" for p in fetched if p.source_id]
        existing_keys = repo.list_existing_arxiv_ids(keys) if keys else set()

    selected: list[PaperCreate] = []
    for paper in fetched:
        if paper.doi and paper.doi in existing_dois:
            continue
        key = f"ieee:{paper.source_id}" if paper.source_id else ""
        if key and key in existing_keys:
            continue
        if key:
            paper.arxiv_id = key  # 合成键：与 upsert_paper 多源去重约定一致
        selected.append(paper)

    if progress:
        with suppress(Exception):
            progress(f"IEEE 抓取完成：{len(selected)} 篇新论文", len(selected), max(max_results, 1))
    return _ingest_papers_proposal(
        query=query,
        papers=selected,
        topic_id=topic_id,
        topic_name=None,
        action_type=action_type,
        action_title=f"IEEE 收集：{query[:80]}",
    )


def import_references(
    *,
    source_paper_id: str,
    source_paper_title: str,
    entries: list[dict],
    topic_ids: list[str] | None = None,
    progress: ProgressFn = None,
    **_: Any,
) -> dict:
    """一键导入参考文献（proposal 模式）：元数据补全（arXiv/S2 网络 IO）留
    handler，papers upsert + 引用边 + topic 关联 + 收集记录在权威面单事务
    执行（Go applyReferenceImportResult）。此前的内联 PDF 下载与后台
    skim/embed 线程移除（后续以任务链承载）。"""
    from packages.integrations.arxiv_client import ArxivClient
    from packages.integrations.semantic_scholar_client import SemanticScholarClient

    topics = topic_ids or []
    arxiv_entries = [e for e in entries if e.get("arxiv_id")]
    ss_entries = [e for e in entries if not e.get("arxiv_id")]

    papers: list[dict] = []
    skipped = 0

    if arxiv_entries:
        ids = [e["arxiv_id"] for e in arxiv_entries]
        fetched: dict[str, PaperCreate] = {}
        with suppress(Exception):
            for paper in ArxivClient().fetch_by_ids(ids):
                fetched[paper.arxiv_id] = paper
        for e in arxiv_entries:
            paper = fetched.get(e["arxiv_id"])
            if paper is None:
                skipped += 1
                continue
            papers.append(
                {
                    "paper": paper.model_dump(mode="json"),
                    "topics": topics,
                    "direction": e.get("direction", "reference"),
                }
            )

    scholar = None
    for e in ss_entries:
        paper_dict: dict | None = None
        if e.get("scholar_id"):
            if scholar is None:
                scholar = SemanticScholarClient()
            with suppress(Exception):
                detail = scholar.fetch_paper_by_scholar_id(e["scholar_id"])
                if detail:
                    time.sleep(0.5)
                    paper_dict = {
                        "arxiv_id": detail.get("arxiv_id") or "",
                        "title": detail.get("title") or e.get("title", "Unknown"),
                        "abstract": detail.get("abstract") or "",
                        "metadata": {"source": "semantic_scholar"},
                    }
        if paper_dict is None:
            paper_dict = {
                "arxiv_id": "",
                "title": e.get("title", "Unknown"),
                "abstract": "",
                "metadata": {"source": "semantic_scholar"},
            }
        papers.append(
            {"paper": paper_dict, "topics": topics, "direction": e.get("direction", "reference")}
        )

    if progress:
        progress(f"元数据就绪 {len(papers)}/{len(entries)}（跳过 {skipped}）", 80, 100)

    return {
        "proposal": {
            "kind": "reference_import",
            "source_paper_id": source_paper_id,
            "source_paper_title": source_paper_title,
            "papers": papers,
        }
    }


def cs_feed_fetch_category(*, category_code: str, progress: ProgressFn = None, **_: Any) -> dict:
    """抓取单个 CS 分类（proposal 模式）：arXiv 网络抓取留 handler（纯计算），
    papers 入库 + csfeed:{code} 主题关联 + 订阅运行状态在权威面单事务执行
    （Go applyCsFeedFetchResult / Python domain_apply.apply_cs_feed_fetch_proposal）。

    此前的内联 upsert 直写、auto_link 线程池与抓取即 embed/skim 随 proposal
    模式移除——抓取后处理由 cs_feed_dispatch 编排器经任务链承接。
    """
    from packages.domain.exceptions import NotFoundError
    from packages.integrations.arxiv_client import ArxivClient
    from packages.storage.db import session_scope
    from packages.storage.repositories import CSFeedRepository

    with session_scope() as session:
        sub = CSFeedRepository(session).get_subscription(category_code)
        if not sub:
            raise NotFoundError("订阅不存在")
        daily_limit = sub.daily_limit

    if progress:
        progress("正在获取论文列表...", 10, 100)
    papers = ArxivClient().fetch_latest(
        query=f"cat:{category_code}", max_results=daily_limit, days_back=7
    )
    if progress:
        progress(f"抓取到 {len(papers)} 篇候选", 80, 100)
    return {
        "proposal": {
            "kind": "cs_feed_fetch",
            "category_code": category_code,
            "papers": [p.model_dump(mode="json") for p in papers],
        }
    }


# ---------- Workflow 可执行 handler（第三轮 REVIEW：注册表任务须可被独立 Executor 执行）----------


def skim_paper_proposal(*, paper_id: str, progress: ProgressFn = None, **_: Any) -> dict:
    """skim 纯计算（Go-authority 切片）：返回 proposal，不写领域表。

    权威面（Go Core apply-result / Python durable /complete 同事务 apply）
    在 fencing 校验通过后提交领域变化与 Task 终态。
    """
    from packages.ai.pipelines import PaperPipelines

    return PaperPipelines().skim_proposal(paper_id)


def deep_read_paper_proposal(*, paper_id: str, progress: ProgressFn = None, **_: Any) -> dict:
    """deep read 纯计算（Go-authority 切片）：返回 proposal，不写领域表"""
    from packages.ai.pipelines import PaperPipelines

    return PaperPipelines().deep_dive_proposal(paper_id)


def embed_paper_proposal(*, paper_id: str, progress: ProgressFn = None, **_: Any) -> dict:
    """embed 纯计算（Go-authority 切片）：返回向量 proposal，不写领域表"""
    from packages.ai.pipelines import PaperPipelines

    return PaperPipelines().embed_paper_proposal(paper_id)


def extract_claims_proposal(
    *, paper_id: str, source_text: str = "", progress: ProgressFn = None, **_: Any
) -> dict:
    """claim 抽取纯计算（proposal 模式）：LLM 抽取候选 claim 项，不写领域表。

    领域 apply（claims/evidence/research_run 指纹去重写入）在权威面完成。
    """
    from packages.ai.claim_extractor import ClaimExtractionService

    svc = ClaimExtractionService()
    paper_id, items, trace, run_meta = svc.extract_compute(
        paper_id, source_text=source_text or None
    )
    return {
        "proposal": {
            "kind": "extract_claims",
            "paper_id": paper_id,
            "items": items,
            "trace": trace,
            "run_meta": run_meta,
        }
    }


def upsert_paper_data(
    *,
    arxiv_id: str,
    title: str = "",
    abstract: str = "",
    metadata: dict | None = None,
    progress: ProgressFn = None,
    **_: Any,
) -> dict:
    """论文 upsert 纯计算（proposal 模式）：不写领域表。

    领域 apply 在权威面单事务执行：Go authority 走 applyUpsertPaperResult
    （papers + source_versions v1 + outbox），Python authority 走
    domain_apply.apply_upsert_proposal。返回 proposal 供下游节点经
    result_ref（paper_id）引用。
    """
    return {
        "proposal": {
            "kind": "upsert_paper",
            "arxiv_id": arxiv_id,
            "title": title or f"arXiv:{arxiv_id}",
            "abstract": abstract or "",
            "metadata": metadata or {},
        }
    }


def download_source_data(*, arxiv_id: str, progress: ProgressFn = None, **_: Any) -> dict:
    """PDF 下载（IO 计算，proposal 模式）：文件落盘由本 handler 承载，
    papers.pdf_path 回填在权威面单事务执行（Go applyDownloadSourceResult /
    domain_apply.apply_download_proposal）。"""
    from packages.integrations.arxiv_client import ArxivClient

    pdf_path = ArxivClient().download_pdf(arxiv_id)
    return {
        "proposal": {
            "kind": "download_source",
            "arxiv_id": arxiv_id,
            "pdf_path": pdf_path,
        }
    }


def send_brief_email_effect(
    *,
    recipient: str,
    subject: str = "PaperMind 每日简报",
    content_id: str = "",
    progress: ProgressFn = None,
    **_: Any,
) -> dict:
    """发送简报邮件（BuildDailyBrief 的 send 节点）——effect ledger 保护的唯一发送路径。

    幂等语义（第三轮 REVIEW P1）：发送前查账本，已登记则跳过；
    "先登记后发送崩溃会漏发"窗口以 manual_recovery 兜底（发送异常时账本
    不登记，Task 进 manual_recovery 由人工重放——人工重放时账本挡重复）。
    """
    from packages.application.commands.effect_ledger import has_effect, register_effect
    from packages.storage.db import session_scope

    effect_key = f"brief_mail:{recipient}:{content_id or subject}"
    with session_scope() as session:
        if has_effect(session, effect_key):
            return {"sent": False, "skipped": True, "effect_key": effect_key}

    from packages.storage.db import session_scope as _scope
    from packages.storage.repositories import GeneratedContentRepository

    html = ""
    if content_id:
        with _scope() as session:
            content = GeneratedContentRepository(session).get(content_id)
            html = content.markdown or ""
    from packages.domain.enums import EffectKind
    from packages.integrations.notifier import NotificationService

    # 第四轮 P1 修复：1) 检查 adapter 返回值——SMTP 未配置/发送失败不登记账本
    # （此前未发送也记 sent=True，之后永久跳过这封实际未发送的邮件）；
    # 2) kind 用 EffectKind.mail_send 枚举（此前传字符串 "email"，PG enum 会
    # 在邮件发出后拒绝 flush → 账本缺失 → 人工重放重复发送）。
    sent = NotificationService().send_email_html(recipient=recipient, subject=subject, html=html)
    if not sent:
        return {
            "sent": False,
            "error": "SMTP 未配置或发送失败（账本未登记，可重试）",
            "effect_key": effect_key,
        }
    with session_scope() as session:
        register_effect(session, effect_key=effect_key, kind=EffectKind.mail_send)
    return {"sent": True, "effect_key": effect_key}


# ---------- 引用图谱 / 生成 ----------


def _citation_edges_proposal(paper_id: str, edges: list[dict]) -> dict:
    """citation_edges proposal 公共封装：标题 → 归一化 arxiv_id（与旧路径
    _title_to_id 一致），papers 元数据 + 边由权威面单事务 upsert。"""
    from packages.ai.graph._common import _title_to_id

    def _paper_ref(title: str) -> dict:
        return {
            "arxiv_id": _title_to_id(title),
            "title": title,
            "abstract": "",
            "metadata": {"source": "semantic_scholar"},
        }

    return {
        "proposal": {
            "kind": "citation_edges",
            "paper_id": paper_id,
            "edges": [
                {
                    "source": _paper_ref(e["source_title"]),
                    "target": _paper_ref(e["target_title"]),
                    "context": e.get("context"),
                }
                for e in edges
            ],
        }
    }


def sync_citations_paper(
    *, paper_id: str, limit: int = 8, progress: ProgressFn = None, **_: Any
) -> dict:
    """单篇引用同步（proposal 模式）：抓取候选边，papers upsert + 边 upsert
    在权威面单事务执行。"""
    from packages.ai.graph.citation import CitationService

    if progress:
        progress("正在抓取引用候选...", 30, 100)
    fetched = CitationService().fetch_edges_for_paper(paper_id, limit=limit)
    if progress:
        progress(f"抓取到 {len(fetched['edges'])} 条候选边", 70, 100)
    return _citation_edges_proposal(fetched["paper_id"], fetched["edges"])


def sync_citations_incremental(
    *, paper_limit: int = 40, edge_limit_per_paper: int = 6, progress: ProgressFn = None, **_: Any
) -> dict:
    """增量引用同步（proposal 模式）：选取无引用边的最新论文并抓取候选边，
    papers upsert + 边 upsert 在权威面单事务执行。"""
    from sqlalchemy import select

    from packages.ai.graph.citation import CitationService
    from packages.storage.db import session_scope
    from packages.storage.models import Citation, Paper

    if progress:
        progress("正在筛选目标论文...", 15, 100)
    titles: list[tuple[str, str]] = []
    with session_scope() as session:
        rows = session.execute(
            select(Paper).order_by(Paper.created_at.desc()).limit(paper_limit * 3)
        ).scalars()
        touched: set[str] = set()
        for e in session.execute(select(Citation)).scalars():
            touched.add(e.source_paper_id)
            touched.add(e.target_paper_id)
        for p_ in rows:
            if str(p_.id) not in touched:
                titles.append((str(p_.id), p_.title or ""))
                if len(titles) >= paper_limit:
                    break

    service = CitationService()
    edges: list[dict] = []
    for idx, (pid, _title) in enumerate(titles):
        if progress:
            progress(
                f"抓取引用候选 ({idx + 1}/{len(titles)})...",
                15 + int(idx / max(len(titles), 1) * 60),
                100,
            )
        try:
            edges.extend(service.fetch_edges_for_paper(pid, limit=edge_limit_per_paper)["edges"])
        except Exception as exc:  # noqa: BLE001 — 单篇失败不阻断
            logging.warning("incremental skip %s: %s", pid[:8], exc)
    if progress:
        progress(f"抓取到 {len(edges)} 条候选边", 85, 100)
    out = _citation_edges_proposal("", edges)
    out["proposal"]["paper_ids"] = [pid for pid, _ in titles]
    return out


def sync_citations_topic(
    *,
    topic_id: str,
    paper_limit: int = 30,
    edge_limit_per_paper: int = 6,
    progress: ProgressFn = None,
    **_: Any,
) -> dict:
    """主题引用同步（proposal 模式）：主题内论文逐篇抓取候选边，领域写在
    权威面单事务执行。"""
    from packages.ai.graph.citation import CitationService
    from packages.storage.db import session_scope
    from packages.storage.repositories import PaperRepository, TopicRepository

    if progress:
        progress("正在筛选主题论文...", 15, 100)
    paper_ids: list[str] = []
    with session_scope() as session:
        topic = TopicRepository(session).get_by_id(topic_id)
        if topic is None:
            raise ValueError(f"topic {topic_id} not found")
        paper_ids = [
            str(p.id) for p in PaperRepository(session).list_by_topic(topic_id, limit=paper_limit)
        ]

    service = CitationService()
    edges: list[dict] = []
    for idx, pid in enumerate(paper_ids):
        if progress:
            progress(
                f"抓取引用候选 ({idx + 1}/{len(paper_ids)})...",
                15 + int(idx / max(len(paper_ids), 1) * 60),
                100,
            )
        try:
            edges.extend(service.fetch_edges_for_paper(pid, limit=edge_limit_per_paper)["edges"])
        except Exception as exc:  # noqa: BLE001
            logging.warning("topic sync skip %s: %s", pid[:8], exc)
    if progress:
        progress(f"抓取到 {len(edges)} 条候选边", 85, 100)
    out = _citation_edges_proposal(topic_id, edges)
    out["proposal"]["topic_id"] = topic_id
    return out


def topic_wiki_save(
    *, keyword: str, limit: int = 120, progress: ProgressFn = None, **_: Any
) -> dict:
    """主题 Wiki 生成并写入 generated_contents（HTTP 语义）"""
    from packages.application.commands.graph import get_topic_wiki

    # wiki 链路的 progress_callback 约定是 (msg, current, total)——与
    # packages/ai/graph/wiki.py 的 _progress 对齐（此前误写 (pct, msg)，
    # executor 调用时 TypeError → 任务 dead_letter）
    def _adapted(msg: str, current: int = 0, total: int = 100):
        if progress:
            progress(msg, current, total)

    result = get_topic_wiki(keyword=keyword, limit=limit, progress_callback=_adapted)

    # proposal 模式（A 档升级）：markdown 计算留在 handler（LLM 调用），
    # generated_contents 插入在权威面单事务执行
    markdown = result.pop("markdown", "")
    metadata = {k: v for k, v in result.items() if k != "content_id"}
    return {
        "proposal": {
            "kind": "save_generated_content",
            "content_type": "topic_wiki",
            "title": f"Topic Wiki: {keyword}",
            "markdown": markdown,
            "keyword": keyword,
            "metadata_json": metadata,
        }
    }


def _brief_date_str() -> str:
    from packages.ai.brief_service import user_date_str

    return user_date_str()


def daily_brief_publish(
    *, recipient: str | None = None, progress: ProgressFn = None, **_: Any
) -> dict:
    """每日简报（HTTP 语义：DailyBriefService.publish，返回含 content_id）"""
    from packages.ai.brief_service import DailyBriefService

    if progress:
        progress("正在生成每日简报...", 20, 100)
    result = DailyBriefService().publish(recipient=recipient, persist=False)
    if progress:
        progress("简报生成完成", 95, 100)
    # proposal 模式（A 档升级）：邮件发送留 handler（外部副作用 + effect ledger
    # 语义归 send_brief_email），generated_contents 插入在权威面单事务执行
    return {
        "proposal": {
            "kind": "save_generated_content",
            "content_type": "daily_brief",
            "title": f"Daily Brief: {_brief_date_str()}",
            "markdown": result.get("brief_markdown", ""),
            "metadata_json": result.get("brief_metadata") or {},
        },
        "saved_path": result.get("saved_path"),
        "email_sent": result.get("email_sent"),
    }


# ---------- 分析 / 翻译 ----------


def analyze_figures(
    *, paper_id: str, max_figures: int = 12, progress: ProgressFn = None, **_: Any
) -> dict:
    """论文图表分析（自 papers 命令迁入）"""
    from packages.ai.analysis_service import FigureService
    from packages.storage.db import session_scope
    from packages.storage.repositories import PaperRepository

    pid = paper_id
    with session_scope() as session:
        paper = PaperRepository(session).get_by_id(pid)
        pdf_path = paper.pdf_path
        paper_title = (paper.title or pid[:8])[:30]

    if progress:
        progress("正在提取图表...", 10, 100)
    results = FigureService().analyze_paper_figures(pid, pdf_path, max_figures, persist=False)

    total_figures = len(results)
    if progress and total_figures > 0:
        progress(f"正在生成解读 ({total_figures} 个图表)...", 50, 100)

    items = FigureService.get_paper_analyses(pid)
    for i, item in enumerate(items):
        if item.get("has_image"):
            item["image_url"] = f"/papers/{pid}/figures/{item['id']}/image"
        else:
            item["image_url"] = None
        if progress:
            progress(
                f"解读中 ({i + 1}/{total_figures})...", 50 + int((i + 1) / total_figures * 45), 100
            )

    if progress:
        progress("图表分析完成", 95, 100)
    # proposal 模式（A 档升级）：解读计算 + 图片文件落盘留 handler，
    # image_analyses 的删重建在权威面单事务执行
    return {
        "proposal": {
            "kind": "figure_analyses",
            "paper_id": str(pid),
            "analyses": [
                {
                    "page_number": item.get("page_number"),
                    "image_index": item.get("image_index"),
                    "image_type": item.get("image_type"),
                    "caption": item.get("caption"),
                    "description": item.get("description"),
                    "image_path": item.get("image_path"),
                    "bbox_json": item.get("bbox_json"),
                }
                for item in items
            ],
        },
        "paper_id": str(pid),
        "count": len(items),
        "title": paper_title,
    }


def translate_bilingual_pdf(
    *,
    paper_id: str,
    target_lang: str = "zh",
    mode: str = "fast",
    progress: ProgressFn = None,
    **_: Any,
) -> dict:
    """双语 PDF 翻译（fast=分段对照 / layout=pdf2zh 排版保留）"""
    from packages.ai.services.bilingual_pdf import (
        process_fast_translation,
        process_layout_translation,
    )
    from packages.storage.db import session_scope
    from packages.storage.repositories import PaperRepository

    with session_scope() as session:
        paper = PaperRepository(session).get_by_id(paper_id)
        pdf_path = paper.pdf_path
    if not pdf_path:
        raise ValueError(f"论文 {paper_id[:8]} 没有 PDF 文件")

    fn = process_fast_translation if mode == "fast" else process_layout_translation
    result = fn(paper_id, pdf_path, target_lang, progress_callback=progress, persist=False)
    # proposal 模式（A 档升级）：翻译计算/双语文档落盘留 handler，
    # paper_translations 缓存在权威面单事务 upsert
    return {
        "proposal": {
            "kind": "paper_translation",
            "paper_id": paper_id,
            "target_lang": target_lang,
            "mode": mode,
            "segments": result.get("segments"),
            "bilingual_pdf_path": result.get("bilingual_pdf_path"),
        },
        "pdf_url": result.get("pdf_url"),
    }
