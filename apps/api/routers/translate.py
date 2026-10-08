"""
翻译 API - 段落对照翻译 / 布局保留翻译

- /translate/selection   划词翻译（无状态，纯实时）
- /translate/segments     段落实时翻译（无状态）
- /translate/bilingual-pdf POST  起异步翻译任务（durable Job + Executor），结果落库
- /translate/bilingual-pdf/{paper_id} GET  查询翻译缓存
- /translate/bilingual-pdf/{paper_id}/file GET  下载布局保留双语 PDF
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from packages.ai.services.translate import (
    translate_segments,
    translate_text,
)
from packages.storage.db import session_scope
from packages.storage.models import PaperTranslation

router = APIRouter(prefix="/translate", tags=["translate"])


class TranslateRequest(BaseModel):
    text: str
    target_lang: str = "zh"


class TranslateResponse(BaseModel):
    original: str
    translation: str


class SegmentTranslationItem(BaseModel):
    id: str
    type: str
    content: str
    translation: str | None = None
    pageNumber: int | None = None


class BilingualPdfRequest(BaseModel):
    paper_id: UUID
    target_lang: str = "zh"
    mode: str = "fast"  # "fast" | "layout"


@router.post("/selection", response_model=TranslateResponse)
def translate_selection(req: TranslateRequest):
    try:
        translation = translate_text(req.text, req.target_lang)
        return TranslateResponse(original=req.text, translation=translation)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/segments")
def translate_segments_endpoint(segments: list[SegmentTranslationItem], target_lang: str = "zh"):
    """段落实时翻译（无状态，不落库 —— 持久化走 /bilingual-pdf 任务）"""
    try:
        seg_dicts = [s.model_dump() for s in segments]
        results = translate_segments(seg_dicts, target_lang)
        return {"segments": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/bilingual-pdf")
async def create_bilingual_pdf(req: BilingualPdfRequest):
    """
    起异步双语翻译任务（durable Job + Executor 执行），结果落库 PaperTranslation。

    - **fast**: 提取分段 + 并发翻译，生成 JSON 对照数据（前端渲染），落 segments
    - **layout**: 调用 pdf2zh 生成完整排版双语 PDF，落 bilingual_pdf_path
    """
    from packages.application.commands.translate import start_bilingual_pdf
    from packages.domain.exceptions import AppError

    try:
        return start_bilingual_pdf(
            paper_id=req.paper_id, target_lang=req.target_lang, mode=req.mode
        )
    except AppError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/bilingual-pdf/{paper_id}")
def get_bilingual_pdf_cache(paper_id: UUID, target_lang: str = "zh", mode: str = "fast"):
    """查询翻译缓存：命中返回 segments（fast）或 pdf_url（layout），未命中返回 {cached:false}"""
    from sqlalchemy import select

    with session_scope() as session:
        existing = session.execute(
            select(PaperTranslation).where(
                PaperTranslation.paper_id == str(paper_id),
                PaperTranslation.target_lang == target_lang,
                PaperTranslation.mode == mode,
            )
        ).scalar_one_or_none()
        if not existing:
            return {"cached": False}
        if mode == "fast":
            return {"cached": True, "segments": existing.segments or []}
        return {
            "cached": True,
            "pdf_url": f"/translate/bilingual-pdf/{paper_id}/file?target_lang={target_lang}&mode=layout",
        }


@router.get("/bilingual-pdf/{paper_id}/file")
def download_bilingual_pdf(paper_id: UUID, target_lang: str = "zh", mode: str = "layout"):
    """下载布局保留翻译生成的双语 PDF"""
    from pathlib import Path

    from sqlalchemy import select

    with session_scope() as session:
        existing = session.execute(
            select(PaperTranslation).where(
                PaperTranslation.paper_id == str(paper_id),
                PaperTranslation.target_lang == target_lang,
                PaperTranslation.mode == mode,
            )
        ).scalar_one_or_none()
        if not existing or not existing.bilingual_pdf_path:
            raise HTTPException(status_code=404, detail="翻译文件不存在")
        pdf_path = Path(existing.bilingual_pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="翻译文件已丢失")
    return FileResponse(
        str(pdf_path),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{paper_id}_{target_lang}.pdf"'},
    )
