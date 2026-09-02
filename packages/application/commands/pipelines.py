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
