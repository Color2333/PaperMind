"""双语 PDF 翻译服务（自 apps/api/routers/translate.py 下沉；C3 退出 tracker 时迁移）

- process_fast_translation：提取分段 → 并发翻译 → 落库 → 返回 segments
- process_layout_translation：pdf2zh CLI → 移动产物 → 落库 → 返回 pdf_url

执行载体为 durable Task（capability `translate_bilingual_pdf`）；
本模块只含纯业务，不感知任务系统。
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from packages.ai.services.translate import translate_text
from packages.storage.db import session_scope
from packages.storage.models import PaperTranslation

logger = logging.getLogger(__name__)


def save_translation(
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


def process_fast_translation(
    paper_id: str, pdf_path: str, target_lang: str, progress_callback=None, *, persist: bool = True
) -> dict:
    """快速翻译：提取分段 → 并发翻译 → 落库 → 返回 segments"""
    from packages.ai.services.translate import extract_segments_from_pdf

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

    if persist:
        save_translation(paper_id, target_lang, "fast", segments=results)
    return {"segments": results}


def process_layout_translation(
    paper_id: str, pdf_path: str, target_lang: str, progress_callback=None, *, persist: bool = True
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

    if persist:
        save_translation(paper_id, target_lang, "layout", bilingual_pdf_path=str(dest))
    if progress_callback:
        progress_callback("完成", 1, 1)
    return {
        "bilingual_pdf_path": str(dest),
        "pdf_url": f"/translate/bilingual-pdf/{paper_id}/file?target_lang={target_lang}&mode=layout",
    }
