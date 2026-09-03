"""流水线命令（B5 起；设计② StartSkim/StartEmbedding 的同步语义封装）

MCP trigger_* 工具保持「同步执行并返回结果」的既有语义（Phase 4 capability
metadata 的 supports_async=false 路径）；Stage C 后 Start* 命令族转为创建 Job，
同步语义由 Job 同步等待或 tool 层轮询实现。

构造 PaperPipelines 于每次调用（构造轻量；不再依赖 apps.api.deps 单例）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from packages.application.commands.task_registry import get_spec

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


# ---------- Start* 任务命令（C3 退出门：只写 durable Job/Task，Executor 执行）----------


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
    """提交粗读任务（durable Job，Executor 执行）；task_id 即 durable Task id"""
    from packages.application.commands.jobs import submit_job

    title = _paper_title(paper_id) or str(paper_id)[:8]
    spec = get_spec("skim_paper")
    return submit_job(
        kind="StartSkim",
        capability="skim_paper",
        title=f"粗读：{title[:30]}",
        input_ref={"paper_id": str(paper_id)},
        resource_class=spec.resource_class,
        timeout_s=spec.timeout_s,
        max_attempts=spec.max_attempts,
    )


def start_deep_read(paper_id) -> dict:
    from packages.application.commands.jobs import submit_job

    title = _paper_title(paper_id) or str(paper_id)[:8]
    spec = get_spec("deep_read_paper")
    return submit_job(
        kind="StartDeepRead",
        capability="deep_read_paper",
        title=f"精读：{title[:30]}",
        input_ref={"paper_id": str(paper_id)},
        resource_class=spec.resource_class,
        timeout_s=spec.timeout_s,
        max_attempts=spec.max_attempts,
    )


def start_embed(paper_id) -> dict:
    from packages.application.commands.jobs import submit_job

    title = _paper_title(paper_id) or str(paper_id)[:8]
    spec = get_spec("embed_paper")
    return submit_job(
        kind="StartEmbedding",
        capability="embed_paper",
        title=f"嵌入：{title[:30]}",
        input_ref={"paper_id": str(paper_id)},
        resource_class=spec.resource_class,
        timeout_s=spec.timeout_s,
        max_attempts=spec.max_attempts,
    )


def start_skim_batch(paper_ids: list[str]) -> dict:
    """批量粗读（前端批量按钮的单一任务化入口）"""
    from packages.application.commands.jobs import submit_job

    spec = get_spec("skim_papers_batch")
    return submit_job(
        kind="StartSkimBatch",
        capability="skim_papers_batch",
        title=f"批量粗读 {len(paper_ids)} 篇",
        input_ref={"paper_ids": [str(p) for p in paper_ids]},
        resource_class=spec.resource_class,
        timeout_s=spec.timeout_s,
        max_attempts=spec.max_attempts,
    )
