"""流水线命令（B5 起；设计② StartSkim/StartEmbedding 的同步语义封装）

MCP trigger_* 工具保持「同步执行并返回结果」的既有语义（Phase 4 capability
metadata 的 supports_async=false 路径）；Stage C 后 Start* 命令族转为创建 Job，
同步语义由 Job 同步等待或 tool 层轮询实现。

构造 PaperPipelines 于每次调用（构造轻量；不再依赖 apps.api.deps 单例）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from packages.domain.schemas import DeepDiveReport, SkimReport


def run_skim(paper_id) -> SkimReport:
    """同步执行粗读；失败抛异常（协议层决定如何呈现）"""
    from packages.ai.pipelines import PaperPipelines

    return PaperPipelines().skim(paper_id)


def run_deep_read(paper_id) -> DeepDiveReport:
    from packages.ai.pipelines import PaperPipelines

    return PaperPipelines().deep_dive(paper_id)


def run_embed(paper_id) -> None:
    from packages.ai.pipelines import PaperPipelines

    PaperPipelines().embed_paper(paper_id)


# ---------- Start* 任务命令（B8；tracker 过渡，C3 转 durable Job）----------


def _paper_title(paper_id) -> str | None:
    from packages.storage.db import session_scope
    from packages.storage.repositories import PaperRepository

    try:
        with session_scope() as session:
            paper = PaperRepository(session).get_by_id(paper_id)
            return (paper.title or "")[:40]
    except Exception:
        return None


def start_skim(paper_id) -> dict:
    """提交粗读后台任务，返回 {"task_id", "status"}"""
    from packages.domain.task_tracker import global_tracker

    title = _paper_title(paper_id) or str(paper_id)[:8]

    def _fn(progress_callback=None):
        if progress_callback:
            progress_callback("正在粗读...", 30, 100)
        skim = run_skim(paper_id)
        if progress_callback:
            progress_callback("完成", 100, 100)
        return skim.model_dump()

    task_id = global_tracker.submit(
        "skim", f"粗读：{title[:30]}", _fn, total=100, category="analysis"
    )
    return {"task_id": task_id, "status": "running"}


def start_deep_read(paper_id) -> dict:
    from packages.domain.task_tracker import global_tracker

    title = _paper_title(paper_id) or str(paper_id)[:8]

    def _fn(progress_callback=None):
        if progress_callback:
            progress_callback("正在精读...", 20, 100)
        deep = run_deep_read(paper_id)
        if progress_callback:
            progress_callback("完成", 100, 100)
        return deep.model_dump()

    task_id = global_tracker.submit(
        "deep_read", f"精读：{title[:30]}", _fn, total=100, category="analysis"
    )
    return {"task_id": task_id, "status": "running"}


def start_embed(paper_id) -> dict:
    from packages.domain.task_tracker import global_tracker

    title = _paper_title(paper_id) or str(paper_id)[:8]

    def _fn(progress_callback=None):
        if progress_callback:
            progress_callback("正在计算向量嵌入...", 50, 100)
        run_embed(paper_id)
        if progress_callback:
            progress_callback("完成", 100, 100)
        return {"status": "embedded", "paper_id": str(paper_id)}

    task_id = global_tracker.submit(
        "embed", f"嵌入：{title[:30]}", _fn, total=100, category="analysis"
    )
    return {"task_id": task_id, "status": "running"}
