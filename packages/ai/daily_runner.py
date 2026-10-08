"""
每日/每周定时任务编排 - 智能调度 + 精读限额

去重第九刀（Go 迁移收尾）：本模块全部领域写经权威面任务链——编排器只
submit_job + 轮询 durable 观察面（任务完成后展开的设计边界：编排任务留在
Python authority，子任务领域写全部在 Go 单事务 apply）。
"""

from __future__ import annotations

import logging
import time

from packages.ai.brief_service import DailyBriefService
from packages.storage.db import session_scope
from packages.storage.models import TopicSubscription

logger = logging.getLogger(__name__)

# 编排器轮询参数（子任务观察面）
_POLL_INTERVAL_S = 2.0
_INGEST_WAIT_S = 600.0
_PROCESS_WAIT_S = 1200.0
_DEEP_WAIT_S = 900.0


def _submit_task(
    *,
    capability: str,
    input_ref: dict,
    title: str,
    created_by: str,
    timeout_s: int,
) -> dict:
    """提交子任务（权威面 Job/Task），返回 {task_id, job_id}"""
    from packages.application.commands.jobs import submit_job

    return submit_job(
        kind="CoreTask",
        capability=capability,
        title=title,
        input_ref=input_ref,
        idempotency_key=None,
        timeout_s=timeout_s,
        created_by=created_by,
    )


def _wait_task(task_id: str, *, timeout_s: float, progress=None, message: str = "") -> dict | None:
    """轮询单任务至终态；成功返回 result，失败/超时/不可见返回 None"""
    from packages.application.queries.tasks import get_task_info, get_task_result

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        time.sleep(_POLL_INTERVAL_S)
        info = get_task_info(task_id)
        if not info:
            continue
        if info.get("finished"):
            if not info.get("success"):
                return None
            return get_task_result(task_id) or {}
        if progress and message:
            with_suppress = getattr(info, "get", lambda *_: None)("message") or message
            progress(with_suppress, 0, 0)
    return None


def _wait_tasks(
    task_ids: list[str],
    *,
    timeout_s: float,
    progress=None,
    base: int = 0,
    span: int = 100,
) -> list[str]:
    """批量轮询至全部终态；返回失败/超时未完成的 task_id（调用方逐篇容错）"""
    from packages.application.queries.tasks import get_task_info

    pending = list(task_ids)
    deadline = time.monotonic() + timeout_s
    while pending and time.monotonic() < deadline:
        time.sleep(_POLL_INTERVAL_S)
        still = []
        for tid in pending:
            info = get_task_info(tid)
            if not info or not info.get("finished"):
                still.append(tid)
        pending = still
        if progress and pending:
            done = len(task_ids) - len(pending)
            progress(
                f"处理中 ({done}/{len(task_ids)})...",
                base + int(done / max(len(task_ids), 1) * span),
                100,
            )
    return pending


def run_topic_ingest(topic_id: str, progress_callback: callable | None = None) -> dict:
    """
    单独处理一个主题的抓取 + 处理 - 智能精读限额（任务链编排器）

    领域写全部经权威面任务链（Go apply 单事务）：
      1. ingest_arxiv_query   —— 抓取入库（幂等去重在 handler 只读预筛）
      2. embed/skim（逐篇）    —— 新论文并行粗读 + 嵌入
      3. deep_read_paper      —— 粗读分数排序取前 N（>= 阈值）精读

    本函数只提交任务并轮询观察面；重试/退避由 durable 任务层承接。
    """
    from sqlalchemy import select

    from packages.storage.models import AnalysisReport

    with session_scope() as session:
        topic = session.get(TopicSubscription, topic_id)
        if not topic:
            return {"topic_id": topic_id, "status": "not_found"}
        topic_name = topic.name
        max_deep_reads = getattr(topic, "max_deep_reads_per_run", 2)
        enable_date_filter = getattr(topic, "enable_date_filter", False)
        date_filter_days = getattr(topic, "date_filter_days", 7)
        days_back = date_filter_days if enable_date_filter else 0

        # 编排所需的主题配置在 Session 关闭前取值（免 DetachedInstanceError）
        query = topic.query
        max_results = topic.max_results_per_run

    # ---- 第一步：抓取入库（ingest_arxiv_query 任务，A 档）----
    if progress_callback:
        progress_callback("正在抓取论文...", 5, 100)
    try:
        ingest_task = _submit_task(
            capability="ingest_arxiv_query",
            input_ref={
                "query": query,
                "max_results": max_results,
                "topic_id": topic_id,
                "days_back": days_back,
                "action_type": "auto_collect",
            },
            title=f"主题抓取: {topic_name[:40]}",
            created_by="topic_ingest",
            timeout_s=900,
        )
    except Exception as exc:
        logger.error("主题 [%s] 抓取任务提交失败: %s", topic_name, exc)
        return {
            "topic_id": topic_id,
            "topic_name": topic_name,
            "status": "failed",
            "error": str(exc),
            "inserted": 0,
        }

    ingest_result = _wait_task(
        ingest_task["task_id"], timeout_s=_INGEST_WAIT_S, progress=progress_callback
    )
    inserted_ids: list[str] = list((ingest_result or {}).get("inserted_ids") or [])
    if ingest_result is None:
        return {
            "topic_id": topic_id,
            "topic_name": topic_name,
            "status": "failed",
            "error": "抓取任务失败或超时",
            "inserted": 0,
        }
    if not inserted_ids:
        logger.info("⚠️  主题 [%s] 没有新论文，跳过处理", topic_name)
        if progress_callback:
            progress_callback("没有新论文", 100, 100)
        return {
            "topic_id": topic_id,
            "topic_name": topic_name,
            "status": "no_new_papers",
            "inserted": 0,
            "new_count": 0,
            "total_count": 0,
        }

    total_new = len(inserted_ids)
    logger.info(
        "📝 主题 [%s] 新抓取 %d 篇论文，精读配额：%d 篇", topic_name, total_new, max_deep_reads
    )

    # ---- 第二步：粗读 + 嵌入（embed_paper + skim_paper 任务，A 档）----
    if progress_callback:
        progress_callback("开始粗读 + 嵌入...", 30, 100)
    child_tasks: list[str] = []
    for pid in inserted_ids:
        for cap in ("embed_paper", "skim_paper"):
            try:
                task = _submit_task(
                    capability=cap,
                    input_ref={"paper_id": pid},
                    title=f"主题处理 {cap.split('_')[0]} {pid[:8]}",
                    created_by="topic_ingest",
                    timeout_s=900 if cap == "skim_paper" else 300,
                )
                child_tasks.append(task["task_id"])
            except Exception as exc:
                logger.warning("%s %s 提交失败: %s", cap, pid[:8], exc)

    unfinished = _wait_tasks(
        child_tasks,
        timeout_s=_PROCESS_WAIT_S,
        progress=progress_callback,
        base=30,
        span=40,
    )
    if unfinished:
        logger.warning("主题 [%s] %d 个处理任务未在期限内完成", topic_name, len(unfinished))

    # ---- 第三步：按粗读分数选前 N 精读（deep_read_paper 任务，A 档）----
    if progress_callback:
        progress_callback("选择高分论文...", 70, 100)
    scored: list[tuple[float, str]] = []
    with session_scope() as session:
        rows = session.execute(
            select(AnalysisReport.paper_id, AnalysisReport.skim_score).where(
                AnalysisReport.paper_id.in_(inserted_ids)
            )
        ).all()
        from packages.config import get_settings

        threshold = get_settings().skim_score_threshold
        for paper_id, score in rows:
            if score is not None and score >= threshold:
                scored.append((float(score), str(paper_id)))
    scored.sort(reverse=True)
    deep_ids = [pid for _score, pid in scored[:max_deep_reads]]

    deep_done = 0
    deep_tasks: list[str] = []
    for pid in deep_ids:
        try:
            task = _submit_task(
                capability="deep_read_paper",
                input_ref={"paper_id": pid},
                title=f"精读 {pid[:8]}",
                created_by="topic_ingest",
                timeout_s=1800,
            )
            deep_tasks.append(task["task_id"])
        except Exception as exc:
            logger.warning("deep_read %s 提交失败: %s", pid[:8], exc)
    if deep_tasks:
        unfinished_deep = _wait_tasks(
            deep_tasks,
            timeout_s=_DEEP_WAIT_S,
            progress=progress_callback,
            base=70,
            span=30,
        )
        deep_done = len(deep_tasks) - len(unfinished_deep)

    if progress_callback:
        progress_callback("处理完成", 100, 100)

    return {
        "topic_id": topic_id,
        "topic_name": topic_name,
        "status": "ok",
        "inserted": total_new,
        "new_count": total_new,
        "skimmed": total_new,
        "deep_read": deep_done,
        "max_deep_reads": max_deep_reads,
    }


def run_daily_ingest() -> dict:
    """兼容旧调用：遍历所有 enabled 主题执行抓取（任务链编排，见 run_topic_ingest）"""
    from packages.storage.repositories import TopicRepository

    with session_scope() as session:
        topic_repo = TopicRepository(session)
        topics = topic_repo.list_topics(enabled_only=True)
        if not topics:
            topics = [
                topic_repo.upsert_topic(
                    name="default-ml",
                    query="cat:cs.LG OR cat:cs.CL",
                    enabled=True,
                    max_results_per_run=20,
                    retry_limit=2,
                )
            ]
        topic_ids = [t.id for t in topics]

    results = []
    for tid in topic_ids:
        results.append(run_topic_ingest(tid))

    total_inserted = sum(r.get("inserted", 0) for r in results)
    total_processed = sum(r.get("skimmed", 0) for r in results)
    return {
        "newly_inserted": total_inserted,
        "processed": total_processed,
        "topics": results,
    }


def run_daily_brief() -> dict:
    """生成每日简报，从数据库读取收件人配置（proposal 模式：领域写同事务 apply）"""
    from packages.storage.repositories import DailyReportConfigRepository

    recipient = None
    try:
        with session_scope() as session:
            config = DailyReportConfigRepository(session).get_config()
            if config.send_email_report and config.recipient_emails:
                recipient = config.recipient_emails.split(",")[0]
    except Exception as e:
        logger.warning(f"读取收件人配置失败：{e}")

    # persist=False：publish 不直写 generated_contents，把领域写所需字段带回，
    # 由 domain_apply.apply_proposal 单事务落库（与 daily_brief_publish 任务
    # handler 同源；邮件发送仍在此处——外部副作用非领域写）
    from packages.ai.brief_service import user_date_str
    from packages.application.commands.domain_apply import apply_proposal

    result = DailyBriefService().publish(recipient=recipient, persist=False)
    proposal = {
        "kind": "save_generated_content",
        "content_type": "daily_brief",
        "title": f"Daily Brief: {user_date_str()}",
        "markdown": result.get("brief_markdown", ""),
        "metadata_json": result.get("brief_metadata") or {},
    }
    with session_scope() as session:
        applied = apply_proposal(session, proposal) or {}
    return {**result, **applied}
