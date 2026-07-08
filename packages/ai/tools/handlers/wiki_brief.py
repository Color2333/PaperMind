"""Wiki 生成 / 每日简报 / 研究空白识别。"""

from __future__ import annotations

import logging
from uuid import UUID

from packages.ai.brief_service import DailyBriefService
from packages.ai.graph_service import GraphService
from packages.ai.tools.types import ToolProgress, ToolResult
from packages.storage.db import session_scope
from packages.storage.repositories import PaperRepository

logger = logging.getLogger(__name__)


def _generate_wiki(type: str, keyword_or_id: str):
    """Wiki 生成 - generator，yield 进度和最终结果"""
    import time

    from packages.domain.task_tracker import global_tracker

    if type == "topic":
        with session_scope() as session:
            papers = PaperRepository(session).full_text_candidates(query=keyword_or_id, limit=3)
            if not papers:
                yield ToolResult(
                    success=False,
                    summary=(f"知识库中没有与 '{keyword_or_id}' 相关的论文，请先导入"),
                )
                return

        # 提交后台任务
        gs = GraphService()
        task_id = global_tracker.submit(
            task_type="topic_wiki",
            title=f"Wiki: {keyword_or_id}",
            fn=lambda progress_callback=None: gs.topic_wiki(
                keyword=keyword_or_id,
                limit=120,
                progress_callback=progress_callback,
            ),
        )
        yield ToolProgress(
            message=f"已提交后台任务，正在为「{keyword_or_id}」生成 Wiki...",
            current=1,
            total=10,
        )

        # 轮询进度
        last_msg = ""
        while True:
            time.sleep(3)
            status = global_tracker.get_task(task_id)
            if not status:
                break
            if status.get("finished"):
                if not status.get("success"):
                    yield ToolResult(
                        success=False,
                        summary=f"Wiki 生成失败: {status.get('error', '未知错误')}",
                    )
                    return
                break
            msg = status.get("message", "")
            pct = status.get("progress_pct", 0)
            step = max(1, min(9, int(pct / 10)))
            if msg and msg != last_msg:
                yield ToolProgress(message=msg, current=step, total=10)
                last_msg = msg

        result = global_tracker.get_result(task_id) or {}
        result["title"] = f"Wiki: {keyword_or_id}"
        yield ToolProgress(message="Wiki 生成完毕", current=10, total=10)
    elif type == "paper":
        try:
            pid = UUID(keyword_or_id)
        except ValueError:
            yield ToolResult(success=False, summary="无效的 paper_id 格式")
            return
        with session_scope() as session:
            try:
                paper = PaperRepository(session).get_by_id(pid)
                paper_title = paper.title
            except ValueError:
                yield ToolResult(success=False, summary=f"论文 {keyword_or_id[:8]}... 不存在")
                return
        yield ToolProgress(message="正在为论文生成 Wiki...", current=1, total=2)
        result = GraphService().paper_wiki(paper_id=keyword_or_id)
        result["title"] = f"Wiki: {paper_title[:40]}"
        yield ToolProgress(message="Wiki 生成完毕，正在渲染...", current=2, total=2)
    else:
        yield ToolResult(success=False, summary=f"无效的 type: {type}，应为 topic 或 paper")
        return
    yield ToolResult(
        success=True,
        data=result,
        summary=f"已生成 {type} wiki",
    )


def _generate_daily_brief(recipient: str = ""):
    """简报生成 - generator，yield 进度和最终结果"""
    from datetime import UTC, datetime

    from packages.integrations.notifier import NotificationService
    from packages.storage.repositories import GeneratedContentRepository

    yield ToolProgress(message="正在收集今日论文数据...", current=1, total=4)
    svc = DailyBriefService()

    yield ToolProgress(message="正在生成简报内容...", current=2, total=4)
    html_content = svc.build_html()
    ts_label = datetime.now(UTC).strftime("%Y-%m-%d")
    ts_file = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    yield ToolProgress(message="正在保存简报...", current=3, total=4)
    notifier = NotificationService()
    saved_path = notifier.save_brief_html(f"daily_brief_{ts_file}.html", html_content)

    email_sent = False
    clean_recipient = recipient.strip() if recipient else ""
    if clean_recipient:
        yield ToolProgress(message="正在发送邮件...", current=4, total=4)
        email_sent = notifier.send_email_html(
            clean_recipient, "PaperMind Daily Brief", html_content
        )

    db_saved = False
    for attempt in range(3):
        try:
            with session_scope() as session:
                repo = GeneratedContentRepository(session)
                repo.create(
                    content_type="daily_brief",
                    title=f"Daily Brief: {ts_label}",
                    markdown=html_content,
                )
            db_saved = True
            break
        except Exception as exc:
            logger.warning("简报保存到数据库失败 (attempt %d): %s", attempt + 1, exc)
            import time

            time.sleep(1)

    if not db_saved:
        logger.error("简报保存到数据库最终失败，但文件已保存: %s", saved_path)

    yield ToolResult(
        success=True,
        data={
            "saved_path": saved_path,
            "email_sent": email_sent,
            "html": html_content,
            "title": f"研究简报: {ts_label}",
        },
        summary="简报已生成" + ("并发送" if email_sent else ""),
    )


def _identify_research_gaps(keyword: str, limit: int = 100) -> ToolResult:
    """识别研究空白"""
    from packages.ai.graph_service import GraphService

    svc = GraphService()
    try:
        result = svc.detect_research_gaps(keyword=keyword, limit=limit)
    except Exception as exc:
        return ToolResult(success=False, summary=f"研究空白分析失败: {exc}")

    analysis = result.get("analysis", {})
    gaps = analysis.get("research_gaps", [])
    trend = analysis.get("trend_analysis", {})
    network = result.get("network_stats", {})

    gap_lines = []
    for i, g in enumerate(gaps[:5], 1):
        conf = g.get("confidence", 0)
        diff = g.get("difficulty", "?")
        gap_lines.append(
            f"{i}. **{g.get('gap_title', '')}** (置信度={conf:.0%}, 难度={diff})\n"
            f"   {g.get('description', '')[:200]}"
        )

    hot = ", ".join(trend.get("hot_directions", [])[:5])
    emerging = ", ".join(trend.get("emerging_opportunities", [])[:5])

    summary = (
        f"「{keyword}」领域研究空白分析\n\n"
        f"**网络规模**: {network.get('total_papers', 0)} 论文, "
        f"{network.get('edge_count', 0)} 引用边, "
        f"密度={network.get('density', 0):.4f}\n\n"
        f"**识别到 {len(gaps)} 个研究空白**:\n"
        + "\n".join(gap_lines)
        + f"\n\n**热门方向**: {hot}\n"
        + f"**新兴机会**: {emerging}\n\n"
        + f"**总结**: {analysis.get('overall_summary', '')[:500]}"
    )

    return ToolResult(
        success=True,
        data={"network_stats": network, "analysis": analysis},
        summary=summary,
    )
