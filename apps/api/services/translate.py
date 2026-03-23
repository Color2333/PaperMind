"""
翻译服务 - 段落对照翻译
"""

from concurrent.futures import ThreadPoolExecutor

import fitz  # PyMuPDF

from packages.integrations.llm_client import LLMClient

llm = LLMClient()

# 翻译并发控制
_max_workers = 5


def translate_text(text: str, target_lang: str = "zh") -> str:
    prompt = f"""Translate the following academic text to {target_lang}.
Maintain the academic tone and technical terminology.

Text:
{text}

Translation:"""
    result = llm.summarize_text(prompt, stage="translate", max_tokens=4096)
    return result.content


def translate_segments(segments: list[dict], target_lang: str = "zh") -> list[dict]:
    """批量翻译分段（并发）"""
    results = []

    def _translate_single(seg: dict) -> dict:
        if seg.get("type") == "paragraph":
            translation = translate_text(seg["content"], target_lang)
            return {**seg, "translation": translation}
        return {**seg, "translation": seg.get("content", "")}

    with ThreadPoolExecutor(max_workers=_max_workers) as executor:
        results = list(executor.map(_translate_single, segments))

    return results


def extract_segments_from_pdf(pdf_path: str, max_pages: int = 30) -> list[dict]:
    """从 PDF 提取带页码的分段（快速版本）"""
    doc = fitz.open(pdf_path)
    paragraphs: list[dict] = []
    para_idx = 0
    max_pages = min(max_pages, len(doc))

    for page_num in range(max_pages):
        page = doc.load_page(page_num)
        page_text = page.get_text("text").strip()
        if not page_text:
            continue

        # 按双换行分割段落
        blocks = page_text.split("\n\n")
        for block in blocks:
            block = block.strip()
            if len(block) < 20:
                continue
            para_idx += 1
            paragraphs.append(
                {
                    "id": f"p-{para_idx}",
                    "type": "paragraph",
                    "content": block[:2000],
                    "pageNumber": page_num + 1,
                }
            )

    doc.close()
    return paragraphs
