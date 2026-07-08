"""
翻译 API - 段落对照翻译 / 布局保留翻译

- /translate/selection   划词翻译（无状态，纯实时）
- /translate/segments     段落实时翻译（无状态）
- /translate/bilingual-pdf POST  起异步翻译任务（global_tracker），结果落库
- /translate/bilingual-pdf/{paper_id} GET  查询翻译缓存
- /translate/bilingual-pdf/{paper_id}/file GET  下载布局保留双语 PDF
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from apps.api.services.translate import (
    extract_segments_from_pdf,
    translate_segments,
    translate_text,
)
from packages.domain.task_tracker import global_tracker
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
    起异步双语翻译任务（global_tracker），结果落库 PaperTranslation。

    - **fast**: 提取分段 + 并发翻译，生成 JSON 对照数据（前端渲染），落 segments
    - **layout**: 调用 pdf2zh 生成完整排版双语 PDF，落 bilingual_pdf_path
    """
    from packages.storage.repositories import PaperRepository

    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            paper = repo.get_by_id(req.paper_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if not paper.pdf_path:
            raise HTTPException(status_code=400, detail="论文没有 PDF 文件")
        pdf_path = paper.pdf_path

    paper_id = str(req.paper_id)

    if req.mode == "fast":
        task_id = global_tracker.submit(
            "bilingual_pdf",
            f"快速翻译 {paper_id[:8]}",
            _process_fast_translation,
            paper_id,
            pdf_path,
            req.target_lang,
            total=1,
            category="analysis",
        )
    else:
        task_id = global_tracker.submit(
            "bilingual_pdf",
            f"布局翻译 {paper_id[:8]}",
            _process_layout_translation,
            paper_id,
            pdf_path,
            req.target_lang,
            total=1,
            category="analysis",
        )

    return {
        "task_id": task_id,
        "status": "started",
        "message": "快速翻译" if req.mode == "fast" else "布局保留翻译（预计 3-5 分钟）",
    }


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


# ---------- 后台处理 ----------


def _process_fast_translation(
    paper_id: str, pdf_path: str, target_lang: str, progress_callback=None
) -> dict:
    """快速翻译：提取分段 → 并发翻译 → 落库 → 返回 segments"""
    segments = extract_segments_from_pdf(pdf_path)
    total = len(segments)
    if progress_callback:
        progress_callback(f"开始翻译 {total} 段", 0, total)

    results: list[dict] = []
    done = 0
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(translate_text, seg["content"], target_lang): seg
            for seg in segments
            if seg.get("type") == "paragraph"
        }
        for future in as_completed(futures):
            seg = futures[future]
            translation = future.result()
            results.append({**seg, "translation": translation})
            done += 1
            if progress_callback:
                progress_callback(f"已翻译 {done}/{total}", done, total)

    # 按原分段顺序排序（id 形如 "p-1"、"p-2"）
    def _sort_key(s: dict) -> int:
        sid = s.get("id", "")
        try:
            return int(sid.split("-")[1])
        except (IndexError, ValueError):
            return 0

    results.sort(key=_sort_key)

    _save_translation(paper_id, target_lang, "fast", segments=results)
    return {"segments": results}


def _process_layout_translation(
    paper_id: str, pdf_path: str, target_lang: str, progress_callback=None
) -> dict:
    """布局保留翻译：pdf2zh CLI → 移动产物 → 落库 → 返回 pdf_url"""
    import shutil
    import subprocess

    from packages.config import get_settings

    if not shutil.which("pdf2zh"):
        raise RuntimeError("未安装 pdf2zh，请先运行 pip install pdf2zh")

    if progress_callback:
        progress_callback("开始布局保留翻译", 0, 1)

    settings = get_settings()
    out_dir = settings.pdf_storage_root / "bilingual"
    out_dir.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        ["pdf2zh", pdf_path, "-lo", target_lang, "-o", str(out_dir)],
        capture_output=True,
        text=True,
        timeout=600,  # 10 分钟超时
    )
    if result.returncode != 0:
        raise RuntimeError(f"pdf2zh 失败：{result.stderr[:500]}")

    # pdf2zh 输出文件名不固定，取目录下最新生成的 PDF
    produced = sorted(out_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not produced:
        raise RuntimeError("pdf2zh 未生成输出文件")

    src = produced[0]
    dest = out_dir / f"{paper_id}_{target_lang}.pdf"
    if src != dest:
        src.replace(dest)

    _save_translation(paper_id, target_lang, "layout", bilingual_pdf_path=str(dest))
    if progress_callback:
        progress_callback("完成", 1, 1)
    return {
        "bilingual_pdf_path": str(dest),
        "pdf_url": f"/translate/bilingual-pdf/{paper_id}/file?target_lang={target_lang}&mode=layout",
    }


def _save_translation(
    paper_id: str,
    target_lang: str,
    mode: str,
    *,
    segments: list[dict] | None = None,
    bilingual_pdf_path: str | None = None,
) -> None:
    """upsert 翻译缓存（同 paper_id+target_lang+mode 唯一）"""
    from sqlalchemy import select

    with session_scope() as session:
        existing = session.execute(
            select(PaperTranslation).where(
                PaperTranslation.paper_id == paper_id,
                PaperTranslation.target_lang == target_lang,
                PaperTranslation.mode == mode,
            )
        ).scalar_one_or_none()
        if existing:
            if segments is not None:
                existing.segments = segments
            if bilingual_pdf_path is not None:
                existing.bilingual_pdf_path = bilingual_pdf_path
        else:
            session.add(
                PaperTranslation(
                    paper_id=paper_id,
                    target_lang=target_lang,
                    mode=mode,
                    segments=segments,
                    bilingual_pdf_path=bilingual_pdf_path,
                )
            )
        session.commit()
