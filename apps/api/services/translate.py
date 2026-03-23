"""
翻译服务 - 段落对照翻译
"""

from packages.integrations.llm_client import LLMClient

llm = LLMClient()


def translate_text(text: str, target_lang: str = "zh") -> str:
    prompt = f"""Translate the following academic text to {target_lang}.
Maintain the academic tone and technical terminology.

Text:
{text}

Translation:"""
    result = llm.summarize_text(prompt, stage="translate", max_tokens=4096)
    return result.content


def translate_segments(segments: list[dict], target_lang: str = "zh") -> list[dict]:
    results = []
    for seg in segments:
        if seg.get("type") == "paragraph":
            translation = translate_text(seg["content"], target_lang)
            results.append({**seg, "translation": translation})
        else:
            results.append({**seg, "translation": seg.get("content", "")})
    return results
