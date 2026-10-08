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
    """提交图表分析后台任务（durable Job，Executor 执行）"""
    from packages.application.commands.jobs import submit_job
    from packages.application.commands.task_registry import get_spec
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
        paper_title = paper.title[:50]
        pid = paper.id

    spec = get_spec("analyze_figures")
    submitted = submit_job(
        kind="StartFigureAnalysis",
        capability="analyze_figures",
        title=f"📊 图表分析：{paper_title}",
        input_ref={"paper_id": str(pid), "max_figures": max_figures},
        resource_class=spec.resource_class,
        timeout_s=spec.timeout_s,
        max_attempts=spec.max_attempts,
    )
    task_id = submitted["task_id"]
    return {
        "task_id": task_id,
        "status": "started",
        "message": "图表分析已启动，正在处理...",
    }
