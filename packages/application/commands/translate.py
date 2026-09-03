"""翻译命令（B8 后期，设计② TranslateContent；C3 退出门起长任务走 durable Job）"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from packages.domain.exceptions import NotFoundError

if TYPE_CHECKING:
    from uuid import UUID


def translate_selection(*, text: str, target_lang: str = "zh") -> dict[str, Any]:
    from packages.ai.services.translate import translate_text

    return {"original": text, "translation": translate_text(text, target_lang)}


def translate_segments(*, segments: list[dict], target_lang: str = "zh") -> dict[str, Any]:
    from packages.ai.services.translate import translate_segments as _translate

    return {"segments": _translate(segments, target_lang)}


def start_bilingual_pdf(
    *, paper_id: UUID | str, target_lang: str = "zh", mode: str = "fast"
) -> dict[str, Any]:
    """起异步双语 PDF 翻译任务（durable Job；PDF 缺失在提交时快速失败）"""
    from packages.application.commands.jobs import submit_job
    from packages.application.commands.task_registry import get_spec
    from packages.storage.db import session_scope
    from packages.storage.repositories import PaperRepository

    pid = str(paper_id)
    with session_scope() as session:
        try:
            paper = PaperRepository(session).get_by_id(paper_id)
        except (ValueError, NotFoundError) as exc:
            raise NotFoundError(f"论文不存在: {pid}") from exc
        if not paper.pdf_path:
            raise ValueError("论文没有 PDF 文件")
        title = (paper.title or pid[:8])[:30]

    spec = get_spec("translate_bilingual_pdf")
    submitted = submit_job(
        kind="TranslateBilingualPdf",
        capability="translate_bilingual_pdf",
        title=f"翻译：{title} ({mode})",
        input_ref={"paper_id": pid, "target_lang": target_lang, "mode": mode},
        resource_class=spec.resource_class,
        timeout_s=spec.timeout_s,
        max_attempts=spec.max_attempts,
        created_by="api",
    )
    return {
        "task_id": submitted["task_id"],
        "job_id": submitted["job_id"],
        "status": submitted["status"],
        "message": "快速翻译" if mode == "fast" else "布局保留翻译（预计 3-5 分钟）",
    }


def get_bilingual_pdf_cache(
    *, paper_id: UUID, target_lang: str = "zh", mode: str = "fast"
) -> dict[str, Any]:
    from packages.storage.db import session_scope
    from packages.storage.models import PaperTranslation

    with session_scope() as session:
        from sqlalchemy import select

        row = session.execute(
            select(PaperTranslation).where(
                PaperTranslation.paper_id == str(paper_id),
                PaperTranslation.target_lang == target_lang,
                PaperTranslation.mode == mode,
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("翻译缓存不存在")
        return {"paper_id": str(paper_id), "segments": row.segments or [], "mode": mode}
