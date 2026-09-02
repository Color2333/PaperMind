"""每日任务命令（B5；设计② StartDailyIngest）

沿用内存 tracker 提交（C3 收敛为 durable Job）；后台线程内顺序执行
run_daily_ingest + run_daily_brief，语义与现 MCP trigger_daily_job 一致。
"""

from __future__ import annotations


def start_daily_ingest() -> dict:
    """提交每日抓取+简报任务，立即返回 task_id"""
    from packages.domain.task_tracker import global_tracker

    def _run_daily(progress_callback=None):
        from packages.ai.daily_runner import run_daily_brief, run_daily_ingest

        ingest = run_daily_ingest()
        brief = run_daily_brief()
        return {"ingest": ingest, "brief": brief}

    task_id = global_tracker.submit(
        task_type="mcp_daily",
        title="MCP 触发的每日抓取+简报",
        fn=_run_daily,
        total=2,
        category="mcp",
    )
    return {"task_id": task_id, "status": "started", "message": "用 get_task_status 查进度"}
