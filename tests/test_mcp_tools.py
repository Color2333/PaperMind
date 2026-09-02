"""B5：MCP 工具层测试——工具只做协议转换，业务经 packages/application 层

验证：search_papers/get_paper/find_similar（读）+ trigger_skim/trigger_embed
（同步命令，LLM fake）+ trigger_daily_job/get_task_status（tracker 包装）。
不通过 fastmcp 协议栈，直接调用 mcp.py 的 _tool_* 普通函数。
"""

from __future__ import annotations

import json
import threading
import time
import uuid as _uuid

import pytest

import packages.ai.pipelines  # noqa: F401
from apps.api.mcp import (
    _tool_find_similar,
    _tool_get_daily_brief,
    _tool_get_paper,
    _tool_get_task_status,
    _tool_recommend_papers,
    _tool_search_papers,
    _tool_trigger_daily_job,
    _tool_trigger_embed,
    _tool_trigger_skim,
)
from packages.domain.schemas import PaperCreate
from packages.integrations.llm_client import LLMClient, LLMResult
from packages.storage.repositories import PaperRepository

FAKE_SKIM = {
    "one_liner": "MCP fake：流式说话人分离方法降低 DER 12%。",
    "innovations": ["创新点 A"],
    "keywords": ["mcp", "test"],
    "title_zh": "测试标题",
    "abstract_zh": "测试摘要",
    "relevance_score": 0.8,
}


@pytest.fixture()
def mcp_env(isolated_db, monkeypatch):
    def _fake_summarize(self, prompt, stage, model_override=None, max_tokens=None):
        payload = FAKE_SKIM
        content = json.dumps(payload, ensure_ascii=False)
        return LLMResult(
            content=content,
            parsed_json=payload,
            input_tokens=8,
            output_tokens=4,
            input_cost_usd=0.0,
            output_cost_usd=0.0,
            total_cost_usd=0.0,
        )

    def _fake_embed(self, text, dimensions=1536):
        return [0.5] * 8

    monkeypatch.setattr(LLMClient, "summarize_text", _fake_summarize)
    monkeypatch.setattr(LLMClient, "embed_text", _fake_embed)
    return isolated_db


def _mk_paper(session, arxiv_id: str, title: str, abstract: str) -> str:
    return (
        PaperRepository(session)
        .upsert_paper(PaperCreate(title=title, abstract=abstract, arxiv_id=arxiv_id))
        .id
    )


def test_search_papers_tool(mcp_env):
    from packages.storage.db import session_scope

    with session_scope() as session:
        pid = _mk_paper(
            session, "2608.7001", "MCP searchable paper", "Diarization with transformers."
        )
        _mk_paper(session, "2608.7002", "Unrelated title", "Nothing matches here.")

    result = _tool_search_papers(query="diarization", limit=10)
    assert result["total"] == 1
    assert result["items"][0]["id"] == pid

    # 空查询 = 按时间倒序全部
    result = _tool_search_papers(query="", limit=1)
    assert result["total"] == 2 and len(result["items"]) == 1

    # topic_id 过滤路径不报错（无匹配主题 → 空）
    result = _tool_search_papers(query="", limit=10, topic_id="no-such-topic")
    assert result["items"] == []


def test_get_paper_tool(mcp_env):
    from packages.storage.db import session_scope

    with session_scope() as session:
        pid = _mk_paper(session, "2608.7003", "Detail paper", "Abstract for detail.")

    detail = _tool_get_paper(str(pid))
    assert detail["id"] == str(pid)
    assert detail["title"] == "Detail paper"
    assert detail["skim_summary"] is None and detail["deep_dive"] is None
    assert detail["topics"] == [] and detail["tags"] == []

    assert _tool_get_paper(str(_uuid.uuid4())) == {"error": "论文不存在"}
    assert "无效的 paper_id" in _tool_get_paper("not-a-uuid")["error"]


def test_find_similar_tool(mcp_env):
    from packages.storage.db import session_scope

    with session_scope() as session:
        pid = _mk_paper(session, "2608.7004", "Seed paper", "Seed abstract.")

    # 无 embedding → note 兜底
    result = _tool_find_similar(str(pid), top_k=5)
    assert result["count"] == 0 and "无相似" in result["note"]
    assert _tool_find_similar(str(_uuid.uuid4()))["error"] == "论文不存在"
    assert "无效的 paper_id" in _tool_find_similar("bad-uuid")["error"]


def test_trigger_skim_and_embed_tools(mcp_env):
    from packages.storage.db import session_scope

    with session_scope() as session:
        pid = _mk_paper(session, "2608.7005", "Skim me", "Skim abstract text.")

    skim = _tool_trigger_skim(str(pid))
    assert skim["success"] is True
    assert skim["one_liner"] == FAKE_SKIM["one_liner"]
    assert skim["relevance_score"] == pytest.approx(0.8)

    embed = _tool_trigger_embed(str(pid))
    assert embed["success"] is True

    # 失败路径：论文不存在 → success False + error
    missing = _tool_trigger_skim(str(_uuid.uuid4()))
    assert missing["success"] is False and missing["error"]
    assert "无效的 paper_id" in _tool_trigger_skim("bad")["error"]


def test_trigger_daily_job_and_status(mcp_env, monkeypatch):
    import packages.ai.daily_runner as daily_runner

    monkeypatch.setattr(daily_runner, "run_daily_ingest", lambda: {"ingested": 0})
    monkeypatch.setattr(daily_runner, "run_daily_brief", lambda: {"ok": True})

    started = _tool_trigger_daily_job()
    task_id = started["task_id"]
    assert started["status"] == "started"

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status = _tool_get_task_status(task_id)
        assert "error" not in status
        if status["status"] == "completed":
            break
        threading.Event().wait(0.05)
    assert status["status"] == "completed"
    assert status["result"] == {"ingest": {"ingested": 0}, "brief": {"ok": True}}

    assert _tool_get_task_status("no-such-task") == {"error": "任务不存在或已过期"}


def test_recommend_and_brief_tools_smoke(mcp_env):
    # 空库：推荐为空；简报可构建（无数据时各区块为空）
    recs = _tool_recommend_papers(top_k=5)
    assert recs == {"count": 0, "items": []}
    text = _tool_get_daily_brief(limit=5)
    assert isinstance(text, str)
