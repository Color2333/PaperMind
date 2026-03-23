"""
翻译 API - 段落对照翻译 / 布局保留翻译
"""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from apps.api.services.translate import (
    extract_segments_from_pdf,
    translate_segments,
    translate_text,
)

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


class BilingualPdfResponse(BaseModel):
    job_id: str
    status: str
    message: str


@router.post("/selection", response_model=TranslateResponse)
def translate_selection(req: TranslateRequest):
    try:
        translation = translate_text(req.text, req.target_lang)
        return TranslateResponse(original=req.text, translation=translation)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/segments")
def translate_segments_endpoint(segments: list[SegmentTranslationItem], target_lang: str = "zh"):
    try:
        seg_dicts = [s.model_dump() for s in segments]
        results = translate_segments(seg_dicts, target_lang)
        return {"segments": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/bilingual-pdf", response_model=BilingualPdfResponse)
async def create_bilingual_pdf(req: BilingualPdfRequest, background_tasks: BackgroundTasks):
    """
    生成双语 PDF（异步任务）

    - **fast**: 快速翻译，生成 JSON 对照数据（前端渲染）
    - **layout**: 布局保留，调用 PDFMathTranslate 生成完整双语 PDF
    """
    from uuid import uuid4

    from packages.storage.db import session_scope
    from packages.storage.repositories import PaperRepository

    job_id = str(uuid4())

    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            paper = repo.get_by_id(req.paper_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if not paper.pdf_path:
            raise HTTPException(status_code=400, detail="论文没有 PDF 文件")

    # 根据模式选择处理方式
    if req.mode == "fast":
        # 快速模式：提取分段 + 并发翻译
        background_tasks.add_task(
            _process_fast_translation, job_id, paper.pdf_path, req.target_lang
        )
        return BilingualPdfResponse(
            job_id=job_id, status="processing", message="快速翻译中，预计 1-2 分钟完成"
        )
    else:
        # 布局保留模式：调用 PDFMathTranslate
        background_tasks.add_task(
            _process_layout_translation, job_id, paper.pdf_path, req.target_lang
        )
        return BilingualPdfResponse(
            job_id=job_id, status="processing", message="布局保留翻译中，预计 3-5 分钟完成"
        )


def _process_fast_translation(job_id: str, pdf_path: str, target_lang: str):
    """快速翻译处理"""
    try:
        # 1. 提取分段
        segments = extract_segments_from_pdf(pdf_path)
        # 2. 并发翻译
        translate_segments(segments, target_lang)
        # 3. 保存结果（可以存到文件或数据库）
        # TODO: 保存翻译结果
    except Exception:
        # TODO: 更新任务状态为失败
        pass


def _process_layout_translation(job_id: str, pdf_path: str, target_lang: str):
    """布局保留翻译处理（调用 PDFMathTranslate）"""
    try:
        import subprocess
        from pathlib import Path

        output_dir = Path("/tmp/pdf2zh_output")
        output_dir.mkdir(exist_ok=True)

        # 调用 PDFMathTranslate CLI
        result = subprocess.run(
            ["pdf2zh", pdf_path, "-lo", target_lang, "-o", str(output_dir)],
            capture_output=True,
            text=True,
            timeout=600,  # 10 分钟超时
        )

        if result.returncode != 0:
            raise RuntimeError(f"PDFMathTranslate 失败：{result.stderr}")

        # TODO: 移动生成的 PDF 到存储目录
    except Exception:
        # TODO: 更新任务状态为失败
        pass
