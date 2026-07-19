"""推理链深度分析。"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from packages.ai.tools.types import ToolProgress, ToolResult

if TYPE_CHECKING:
    from collections.abc import Iterator


def _reasoning_analysis(paper_id: str) -> Iterator[ToolProgress | ToolResult]:
    """推理链深度分析"""
    from packages.ai.reasoning_service import ReasoningService
    from packages.ai.tools.base import _require_paper

    # 用 _require_paper 统一解析（支持短前缀，返回 detached 但属性已加载的 paper）
    paper, err = _require_paper(paper_id)
    if err:
        yield err
        return
    title = paper.title
    pid = UUID(paper.id)  # 用完整 UUID，不用原始短前缀

    yield ToolProgress(message=f"正在分析「{(title or '')[:30]}」的推理链...", current=1, total=2)
    svc = ReasoningService()
    try:
        result = svc.analyze(pid)
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
