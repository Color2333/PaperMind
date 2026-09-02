"""论文写命令（B8，设计②：UpdatePaperFlag / DownloadSourceVersion / StartFigureAnalysis）

缓存失效（folder_stats/推荐）属于传输层一致性，由调用方（router）在命令成功后执行；
命令只负责领域变更与任务提交。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from packages.domain.exceptions import NotFoundError, ValidationError

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.orm import Session

_FLAG_FIELDS = ("favorited", "rejected")


def toggle_paper_flag(session: Session, *, paper_id: UUID | str, field: str) -> dict[str, Any]:
    """切换 favorited / rejected 开关，返回 {"id", field: 新值}"""
    if field not in _FLAG_FIELDS:
        raise ValidationError(f"不支持的论文标记字段: {field}")
    from packages.storage.repositories import PaperRepository

    try:
        paper = PaperRepository(session).get_by_id(paper_id)
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc
    current = getattr(paper, field, False)
    setattr(paper, field, not current)
    session.commit()
    return {"id": str(paper.id), field: getattr(paper, field)}


def download_source(paper_id: UUID | str) -> dict[str, Any]:
    """从 arXiv 下载 PDF 并落库路径；返回 {"status", "pdf_path"}"""
    from packages.integrations.arxiv_client import ArxivClient
    from packages.storage.db import session_scope
    from packages.storage.repositories import PaperRepository

    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            paper = repo.get_by_id(paper_id)
        except ValueError as exc:
            raise NotFoundError(str(exc)) from exc
        from pathlib import Path

        if paper.pdf_path and Path(paper.pdf_path).exists():
            return {"status": "exists", "pdf_path": paper.pdf_path}
        if not paper.arxiv_id or paper.arxiv_id.startswith("ss-"):
            raise ValidationError("该论文没有有效的 arXiv ID，无法下载 PDF")
        arxiv_id = paper.arxiv_id

    pdf_path = ArxivClient().download_pdf(arxiv_id)
    with session_scope() as session:
        PaperRepository(session).set_pdf_path(paper_id, pdf_path)
    return {"status": "downloaded", "pdf_path": pdf_path}


def start_figure_analysis(paper_id: UUID | str, *, max_figures: int = 10) -> dict[str, Any]:
    """提交图表分析后台任务（precheck + tracker 提交；C3 后转 durable Job）"""
    from packages.domain.task_tracker import global_tracker
    from packages.storage.db import session_scope
    from packages.storage.repositories import PaperRepository

    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            paper = repo.get_by_id(paper_id)
        except ValueError as exc:
            raise NotFoundError(str(exc)) from exc
        if not paper.pdf_path:
            raise ValidationError("论文没有 PDF 文件")
        pdf_path = paper.pdf_path
        paper_title = paper.title[:50]
        pid = paper.id

    def _analyze_fn(progress_callback=None):
        from packages.ai.figure_service import FigureService

        if progress_callback:
            progress_callback("正在提取图表...", 10, 100)
        results = FigureService().analyze_paper_figures(pid, pdf_path, max_figures)

        total_figures = len(results)
        if progress_callback and total_figures > 0:
            progress_callback(f"正在生成解读 ({total_figures} 个图表)...", 50, 100)

        items = FigureService.get_paper_analyses(pid)
        for i, item in enumerate(items):
            if item.get("has_image"):
                item["image_url"] = f"/papers/{pid}/figures/{item['id']}/image"
            else:
                item["image_url"] = None
            if progress_callback:
                progress_callback(
                    f"解读中 ({i + 1}/{total_figures})...",
                    50 + int((i + 1) / total_figures * 45),
                    100,
                )

        if progress_callback:
            progress_callback("图表分析完成", 95, 100)
        return {"paper_id": str(pid), "count": len(items), "items": items}

    task_id = global_tracker.submit(
        task_type="figure_analysis",
        title=f"📊 图表分析：{paper_title}",
        fn=_analyze_fn,
        total=max_figures,
    )
    return {
        "task_id": task_id,
        "status": "started",
        "message": "图表分析已启动，正在处理...",
    }
