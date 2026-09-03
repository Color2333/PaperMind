"""翻译命令（B8 后期，设计② TranslateContent）"""

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
    *, paper_id: UUID, target_lang: str = "zh", mode: str = "fast"
) -> dict[str, Any]:
    """起异步双语 PDF 翻译任务"""
    from apps.api.routers.translate import _process_fast_translation, _process_layout_translation
    from packages.domain.task_tracker import global_tracker

    fn = _process_fast_translation if mode == "fast" else _process_layout_translation
    task_id = global_tracker.submit(
        task_type="bilingual_pdf",
        title=f"翻译: {str(paper_id)[:8]} ({mode})",
        fn=lambda progress_callback=None: fn(paper_id, target_lang),
    )
    return {"task_id": task_id, "status": "started"}


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
