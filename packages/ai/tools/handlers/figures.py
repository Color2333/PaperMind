"""论文图表解读。"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from packages.ai.tools.types import ToolProgress, ToolResult

if TYPE_CHECKING:
    from collections.abc import Iterator


def _analyze_figures(paper_id: str, max_figures: int = 10) -> Iterator[ToolProgress | ToolResult]:
    """提取并解读论文图表"""
    from packages.ai.figure_service import FigureService
    from packages.ai.tools.base import _require_paper

    # 用 _require_paper 统一解析（支持短前缀，返回 detached 但属性已加载的 paper）
    paper, err = _require_paper(paper_id)
    if err:
        yield err
        return
    if not paper.pdf_path:
        yield ToolResult(success=False, summary="论文没有 PDF 文件，无法提取图表")
        return
    pdf_path = paper.pdf_path
    title = paper.title
    pid = UUID(paper.id)  # 用完整 UUID，不用原始短前缀

    yield ToolProgress(message=f"正在提取「{(title or '')[:30]}」中的图表...", current=1, total=3)
    svc = FigureService()
    try:
        results = svc.analyze_paper_figures(
            pid,
            pdf_path,
            max_figures=max_figures,
        )
    except Exception as exc:
        yield ToolResult(success=False, summary=f"图表解读失败: {exc}")
        return

    if not results:
        yield ToolResult(
            success=True,
            data={"count": 0, "figures": []},
            summary=f"论文「{title}」中未检测到可解读的图表",
        )
        return

    figures_data = [
        {
            "page": r.page_number,
            "type": r.image_type,
            "caption": r.caption,
            "description": r.description[:500],
            "figure_type": getattr(r, "figure_type", r.image_type),
            "analysis": getattr(r, "analysis", r.description[:500]),
        }
        for r in results
    ]

    yield ToolResult(
        success=True,
        data={"count": len(results), "figures": figures_data},
        summary=f"已解读「{title}」中的 {len(results)} 张图表",
    )
