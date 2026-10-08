"""PaperMind MCP server —— 挂载到现有 FastAPI，供 hermes agent / pm CLI 接入。

Streamable HTTP transport（MCP 2025-06-18 规范）。鉴权两级：
1. DB API 令牌（pmt_ 前缀，pm login / 网页签发，带 scope）
2. 静态 MCP_AUTH_TOKEN（hermes 常驻应急用）
两者都未配置时不启用鉴权（仅开发用）。

暴露论文查询 / 每日简报 / 论文推荐 / 触发处理任务四类工具；工具只做协议转换，
业务全部经 packages/application 层（B5，设计②），不引用 apps.api.deps 服务单例。

@author Color2333
"""

from __future__ import annotations

import hmac
import os
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.server.auth.auth import AccessToken, TokenVerifier

from packages.domain.exceptions import NotFoundError

# 静态令牌（hermes 常驻用，免续期）。未配置时仅依赖 DB 令牌；都没有则不鉴权（仅开发用）。
_MCP_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")


class _DbFallbackVerifier(TokenVerifier):
    """先查 DB API 令牌（pm login / 网页签发，哈希存储 + scope），失败回落静态令牌。"""

    def __init__(self, static_token: str, **kwargs):
        super().__init__(**kwargs)
        self._static_token = static_token

    async def verify_token(self, token: str) -> AccessToken | None:
        from starlette.concurrency import run_in_threadpool

        from apps.api.token_auth import lookup_api_token

        info = await run_in_threadpool(lookup_api_token, token)
        if info is not None:
            access = AccessToken(
                token=token,
                client_id=info.name,
                scopes=info.scopes,
                claims={"sub": info.name, "auth_method": "api_token", "scopes": info.scopes},
            )
        elif self._static_token and hmac.compare_digest(token, self._static_token):
            access = AccessToken(
                token=token,
                client_id="hermes-agent",
                scopes=["read", "write"],
                claims={"sub": "hermes", "auth_method": "static", "scopes": ["read", "write"]},
            )
        else:
            return None
        # required_scopes 子集校验（与 StaticTokenVerifier 行为一致）
        if self.required_scopes and not set(self.required_scopes) <= set(access.scopes or []):
            return None
        return access


from packages.config import get_settings  # noqa: E402

if _MCP_TOKEN or get_settings().auth_password:
    _verifier = _DbFallbackVerifier(static_token=_MCP_TOKEN, required_scopes=["read"])
    mcp = FastMCP("papermind-mcp", auth=_verifier)
else:
    # 未配任何凭证：开发模式不鉴权（生产必须配 MCP_AUTH_TOKEN 或使用 DB 令牌）
    mcp = FastMCP("papermind-mcp")


# ---------- 工具实现（只做协议转换；业务在 packages/application 层）----------


def _to_text(content: str | dict) -> str:
    """把内容转成适合 MCP tool 返回的 JSON 文本（hermes 用文本即可）。"""
    import json

    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


def _tool_search_papers(query: str = "", limit: int = 10, topic_id: str = "") -> dict:
    from packages.application.queries.papers import list_papers
    from packages.storage.db import session_scope

    limit = max(1, min(limit, 50))
    with session_scope() as session:
        # list_papers 返回 canonical result（items+total+分页元信息），MCP 消费其超集
        return list_papers(
            session, page=1, page_size=limit, search=query or None, topic_id=topic_id or None
        )


def _tool_get_paper(paper_id: str) -> dict:
    from packages.application.queries.papers import get_paper
    from packages.storage.db import session_scope

    try:
        pid = UUID(paper_id)
    except ValueError as e:
        return {"error": f"无效的 paper_id: {e}"}

    with session_scope() as session:
        try:
            detail = get_paper(session, pid)
        except NotFoundError:
            return {"error": "论文不存在"}
    # MCP 契约保持原字段名（skim_summary/skim_score/deep_dive）
    skim = detail.get("skim_report") or {}
    deep = detail.get("deep_report") or {}
    return {
        "id": detail["id"],
        "title": detail["title"],
        "arxiv_id": detail["arxiv_id"],
        "abstract": detail["abstract"],
        "read_status": detail["read_status"],
        "publication_date": detail["publication_date"],
        "topics": detail["topics"],
        "tags": detail["tags"],
        "title_zh": detail["title_zh"],
        "abstract_zh": detail["abstract_zh"],
        "skim_summary": skim.get("summary_md"),
        "skim_score": skim.get("skim_score"),
        "deep_dive": deep.get("deep_dive_md"),
    }


def _tool_get_daily_brief(limit: int = 30) -> str:
    import re

    from packages.application.commands.content import get_daily_brief_html

    html = get_daily_brief_html(limit=limit)
    # 从 HTML 提取纯文本摘要（去标签），hermes 用文本更友好
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    # 截断避免过长（MCP tool 输出有上限）
    return text[:8000] if len(text) > 8000 else text


def _tool_recommend_papers(top_k: int = 10) -> dict:
    from packages.application.queries.content import get_recommendations

    top_k = max(1, min(top_k, 30))
    recs = get_recommendations(top_k=top_k)
    return {"count": len(recs), "items": recs}


def _tool_find_similar(paper_id: str, top_k: int = 5) -> dict:
    from packages.application.queries.papers import get_similar_papers
    from packages.storage.db import session_scope

    try:
        pid = UUID(paper_id)
    except ValueError as e:
        return {"error": f"无效的 paper_id: {e}"}

    top_k = max(1, min(top_k, 20))
    with session_scope() as session:
        try:
            result = get_similar_papers(session, pid, top_k=top_k)
        except NotFoundError:
            return {"error": "论文不存在"}
    items = result["items"]
    if not items:
        return {"count": 0, "items": [], "note": "无相似论文或种子论文无 embedding"}
    return {
        "count": len(items),
        "seed_paper_id": paper_id,
        "items": [{"id": i["id"], "title": i["title"], "arxiv_id": i["arxiv_id"]} for i in items],
    }


def _tool_trigger_skim(paper_id: str) -> dict:
    from packages.application.commands.pipelines import run_skim

    try:
        pid = UUID(paper_id)
    except ValueError as e:
        return {"error": f"无效的 paper_id: {e}"}

    try:
        result = run_skim(pid)
        return {
            "paper_id": paper_id,
            "success": True,
            "one_liner": result.one_liner,
            "innovations": result.innovations,
            "keywords": result.keywords,
            "title_zh": result.title_zh,
            "abstract_zh": result.abstract_zh,
            "relevance_score": result.relevance_score,
        }
    except Exception as e:  # noqa: BLE001
        return {"paper_id": paper_id, "success": False, "error": str(e)}


def _tool_trigger_embed(paper_id: str) -> dict:
    from packages.application.commands.pipelines import run_embed

    try:
        pid = UUID(paper_id)
    except ValueError as e:
        return {"error": f"无效的 paper_id: {e}"}

    try:
        run_embed(pid)
        return {"paper_id": paper_id, "success": True, "note": "嵌入完成"}
    except Exception as e:  # noqa: BLE001
        return {"paper_id": paper_id, "success": False, "error": str(e)}


def _tool_trigger_daily_job() -> dict:
    from packages.application.commands.daily import start_daily_ingest

    return start_daily_ingest()


def _tool_get_task_status(task_id: str) -> dict:
    from packages.application.queries.tasks import get_task_status as app_get_task_status

    info = app_get_task_status(task_id)
    if info is None:
        return {"error": "任务不存在或已过期"}
    task = info["task"]
    return {
        "task_id": task["task_id"],
        "status": task["status"],
        "progress": task["progress"],
        "message": task["message"],
        "result": info["result"],
    }


@mcp.tool
def search_papers(query: str = "", limit: int = 10, topic_id: str = "") -> dict:
    """在 PaperMind 论文库中检索论文。

    Args:
        query: 自由文本检索词（匹配标题/摘要/arxiv_id），空则按时间倒序。
        limit: 最多返回条数，默认 10，上限 50。
        topic_id: 可选，按主题过滤。
    """
    return _tool_search_papers(query=query, limit=limit, topic_id=topic_id)


@mcp.tool
def get_paper(paper_id: str) -> dict:
    """获取单篇论文详情（含 skim 摘要/精读内容/主题/标签）。

    Args:
        paper_id: 论文 UUID。
    """
    return _tool_get_paper(paper_id)


@mcp.tool
def get_daily_brief(limit: int = 30) -> str:
    """生成并返回今日研究简报（纯文本摘要版，含高分论文/推荐/趋势）。

    Args:
        limit: 简报论文数量，默认 30。
    """
    return _tool_get_daily_brief(limit=limit)


@mcp.tool
def recommend_papers(top_k: int = 10) -> dict:
    """基于已读论文 embedding 的个性化推荐。

    Args:
        top_k: 返回数量，默认 10，上限 30。
    """
    return _tool_recommend_papers(top_k=top_k)


@mcp.tool
def find_similar(paper_id: str, top_k: int = 5) -> dict:
    """查找与指定论文相似的其他论文（基于 embedding 余弦相似度）。

    Args:
        paper_id: 种子论文 UUID。
        top_k: 返回数量，默认 5，上限 20。
    """
    return _tool_find_similar(paper_id=paper_id, top_k=top_k)


@mcp.tool
def trigger_skim(paper_id: str) -> dict:
    """触发单篇论文粗读（skim），返回 skim 结果（一句话/创新点/分数）。

    Args:
        paper_id: 论文 UUID。
    """
    return _tool_trigger_skim(paper_id)


@mcp.tool
def trigger_embed(paper_id: str) -> dict:
    """触发单篇论文嵌入（重新计算 embedding 并落库）。

    Args:
        paper_id: 论文 UUID。
    """
    return _tool_trigger_embed(paper_id)


@mcp.tool
def trigger_daily_job() -> dict:
    """触发每日抓取+简报任务（异步，立即返回 task_id，用 get_task_status 查进度）。

    返回的 task_id 可用 get_task_status 工具轮询状态。
    """
    return _tool_trigger_daily_job()


@mcp.tool
def get_task_status(task_id: str) -> dict:
    """查询异步任务状态（trigger_daily_job 返回的 task_id）。

    Args:
        task_id: 任务 ID。
    """
    return _tool_get_task_status(task_id)


def get_mcp_asgi_app():
    """返回可挂载到 FastAPI 的 ASGI 子 app（端点挂到 /mcp 后为 /mcp/）。"""
    return mcp.http_app(path="/")
