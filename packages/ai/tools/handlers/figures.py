"""论文图表解读。"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from packages.ai.tools.types import ToolProgress, ToolResult
from packages.storage.db import session_scope
from packages.storage.repositories import PaperRepository

if TYPE_CHECKING:
    from collections.abc import Iterator


def _analyze_figures(paper_id: str, max_figures: int = 10) -> Iterator[ToolProgress | ToolResult]:
    """提取并解读论文图表"""
    from packages.ai.figure_service import FigureService

    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            paper = repo.get_by_id(UUID(paper_id))
        except (ValueError, Exception) as exc:
            yield ToolResult(success=False, summary=f"论文不存在: {exc}")
            return
        if not paper.pdf_path:
            yield ToolResult(success=False, summary="论文没有 PDF 文件，无法提取图表")
            return
        pdf_path = paper.pdf_path
        title = paper.title

    yield ToolProgress(message=f"正在提取「{(title or '')[:30]}」中的图表...", current=1, total=3)
    svc = FigureService()
    try:
        results = svc.analyze_paper_figures(
            UUID(paper_id),
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
