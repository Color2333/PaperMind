"""
AI 关键词建议服务 - 自然语言 → arXiv 搜索关键词
@author Bamzc
"""
from __future__ import annotations

import json
import logging
import re

from packages.integrations.llm_client import LLMClient

logger = logging.getLogger(__name__)

SUGGEST_PROMPT = """\
你是学术论文搜索专家。用户描述了他们的研究兴趣，请为其生成 3-5 组 arXiv 搜索关键词。

要求：
1. 每组包含 name（简短中文名）、query（arXiv API 搜索语法）、reason（推荐理由）
2. query 使用 arXiv 搜索语法：all: 全文、ti: 标题、abs: 摘要、cat: 分类
3. 多词用 AND / OR 连接，最多 3 个关键词避免过滤过严
4. 覆盖用户兴趣的不同角度（核心方向、细分领域、热门变体）

用户描述：{description}

请严格按照以下 JSON 格式输出，不要输出任何其他内容：
{{"suggestions": [{{"name": "...", "query": "...", "reason": "..."}}]}}
"""


def _extract_items(parsed: object) -> list[dict]:
    """从解析结果中提取关键词列表"""
    items: list = []
    if isinstance(parsed, dict):
        for key in ("suggestions", "keywords", "items"):
            if isinstance(parsed.get(key), list):
                items = parsed[key]
                break
        if not items and all(k in parsed for k in ("name", "query")):
            items = [parsed]
    elif isinstance(parsed, list):
        items = parsed
    return [
        {
            "name": str(it.get("name", "")),
            "query": str(it.get("query", "")),
            "reason": str(it.get("reason", "")),
        }
        for it in items
        if isinstance(it, dict) and it.get("query")
    ]


class KeywordService:
    """将自然语言研究兴趣转换为 arXiv 搜索关键词"""

    def __init__(self) -> None:
        self.llm = LLMClient()

    def suggest(self, description: str) -> list[dict]:
        """生成关键词建议"""
        prompt = SUGGEST_PROMPT.format(description=description)
        result = self.llm.summarize_text(
            prompt, stage="deep", max_tokens=4096,
        )
        self.llm.trace_result(result, stage="keyword_suggest", prompt_digest=f"suggest:{description[:80]}")

        # 尝试从返回文本中提取 JSON
        text = result.content.strip()
        # 去掉 ```json ... ``` 包裹
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            text = m.group(1).strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(
                "AI keyword suggestion JSON parse failed: %s",
                text[:200],
            )
            return []

        return _extract_items(parsed)
