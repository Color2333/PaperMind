"""推理链深度分析。"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from packages.ai.tools.types import ToolProgress, ToolResult
from packages.storage.db import session_scope
from packages.storage.repositories import PaperRepository

if TYPE_CHECKING:
    from collections.abc import Iterator


def _reasoning_analysis(paper_id: str) -> Iterator[ToolProgress | ToolResult]:
    """推理链深度分析"""
    from packages.ai.reasoning_service import ReasoningService

    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            paper = repo.get_by_id(UUID(paper_id))
        except (ValueError, Exception) as exc:
            yield ToolResult(success=False, summary=f"论文不存在: {exc}")
            return
        title = paper.title

    yield ToolProgress(message=f"正在分析「{(title or '')[:30]}」的推理链...", current=1, total=2)
    svc = ReasoningService()
    try:
        result = svc.analyze(UUID(paper_id))
    except Exception as exc:
        yield ToolResult(success=False, summary=f"推理链分析失败: {exc}")
        return

    reasoning = result.get("reasoning", {})
    steps = reasoning.get("reasoning_steps", [])
    impact = reasoning.get("impact_assessment", {})

    step_lines = []
    for s in steps[:6]:
        step_lines.append(f"**{s.get('step', '')}**: {s.get('conclusion', '')}")

    scores_text = (
        f"创新性={impact.get('novelty_score', 0):.1f} "
        f"严谨性={impact.get('rigor_score', 0):.1f} "
        f"影响力={impact.get('impact_score', 0):.1f}"
    )

    summary = (
        f"「{title}」推理链分析完成\n\n"
        + "\n".join(step_lines)
        + f"\n\n**评分**: {scores_text}\n\n"
        + f"**综合评估**: {impact.get('overall_assessment', '')[:500]}"
    )

    yield ToolResult(
        success=True,
        data=reasoning,
        summary=summary,
    )
