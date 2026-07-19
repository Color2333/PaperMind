"""论文粗读 / 精读 / 向量化。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from packages.ai.pipelines import PaperPipelines
from packages.ai.tools.base import _require_paper
from packages.ai.tools.types import ToolProgress, ToolResult

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)


def _skim_paper(paper_id: str) -> Iterator[ToolProgress | ToolResult]:
    paper, err = _require_paper(paper_id)
    if err:
        yield err
        return
    if not paper.abstract:
        yield ToolResult(success=False, summary="该论文缺少摘要，无法执行粗读")
        return
    # 用 paper.id（_require_paper 已 resolve 成完整 UUID），不用原始 paper_id
    # （原始可能是短前缀，UUID(paper_id) 会崩 "badly formed hexadecimal UUID"）
    pid = UUID(paper.id)
    title = (paper.title or "")[:40]
    yield ToolProgress(message=f"正在粗读「{title}」...", current=1, total=2)
    try:
        report = PaperPipelines().skim(pid)
        one_liner = report.one_liner
        yield ToolResult(
            success=True,
            data=report.model_dump(),
            summary=f"粗读完成: {one_liner[:80]}" + ("..." if len(one_liner) > 80 else ""),
        )
    except Exception as exc:
        logger.exception("skim_paper failed: %s", exc)
        yield ToolResult(success=False, summary=f"粗读失败: {exc!s}")


def _deep_read_paper(paper_id: str) -> Iterator[ToolProgress | ToolResult]:
    paper, err = _require_paper(paper_id)
    if err:
        yield err
        return
    if not paper.arxiv_id and not paper.pdf_path:
        yield ToolResult(success=False, summary="该论文无 arXiv ID 且无 PDF，无法精读")
        return
    pid = UUID(paper.id)
    title = (paper.title or "")[:40]
    yield ToolProgress(message=f"正在精读「{title}」，预计 30-60 秒...", current=1, total=3)
    try:
        report = PaperPipelines().deep_dive(pid)
        yield ToolResult(
            success=True,
            data=report.model_dump(),
            summary=f"精读完成: {(paper.title or '')[:60]}",
        )
    except Exception as exc:
        logger.exception("deep_read_paper failed: %s", exc)
        yield ToolResult(success=False, summary=f"精读失败: {exc!s}")


def _embed_paper(paper_id: str) -> Iterator[ToolProgress | ToolResult]:
    paper, err = _require_paper(paper_id)
    if err:
        yield err
        return
    pid = UUID(paper.id)
    if paper.embedding:
        yield ToolResult(
            success=True,
            data={"paper_id": paper.id, "status": "already_embedded"},
            summary="该论文已有向量，跳过",
        )
        return
    if not paper.title and not paper.abstract:
        yield ToolResult(
            success=False,
            summary="该论文缺少标题和摘要，无法向量化",
        )
        return
    yield ToolProgress(message="正在向量化...", current=1, total=2)
    try:
        PaperPipelines().embed_paper(pid)
        yield ToolResult(
            success=True,
            data={"paper_id": paper.id, "status": "embedded"},
            summary="向量化完成",
        )
    except Exception as exc:
        logger.exception("embed_paper failed: %s", exc)
        yield ToolResult(success=False, summary=f"向量化失败: {exc!s}")
