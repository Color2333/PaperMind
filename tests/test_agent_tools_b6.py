"""B6（第一批）：agent 工具改调 application——read/batch/search 三组 handler 测试"""

from __future__ import annotations

import json

import pytest

from packages.ai.tools.handlers.batch import (
    _batch_embed_papers,
    _create_batch_job,
    _get_batch_job_status,
)
from packages.ai.tools.handlers.read import _embed_paper, _skim_paper
from packages.ai.tools.handlers.search import _list_papers_by_filter, _search_papers
from packages.domain.schemas import PaperCreate
from packages.integrations.llm_client import LLMClient, LLMResult
from packages.storage.repositories import PaperRepository

FAKE_SKIM = {
    "one_liner": "Agent fake：流式分离降低 DER。",
    "innovations": ["创新点 X"],
    "keywords": ["agent", "test"],
    "title_zh": "代理测试",
    "abstract_zh": "代理测试摘要",
    "relevance_score": 0.7,
}


@pytest.fixture()
def agent_env(isolated_db, monkeypatch):
    def _fake_summarize(self, prompt, stage, model_override=None, max_tokens=None):
        return LLMResult(
            content=json.dumps(FAKE_SKIM, ensure_ascii=False),
            parsed_json=FAKE_SKIM,
            input_tokens=8,
            output_tokens=4,
            input_cost_usd=0.0,
            output_cost_usd=0.0,
            total_cost_usd=0.0,
        )

    def _fake_embed(self, text, dimensions=1536):
        return [0.25] * 8

    monkeypatch.setattr(LLMClient, "summarize_text", _fake_summarize)
    monkeypatch.setattr(LLMClient, "embed_text", _fake_embed)
    return isolated_db


def _mk_paper(session, arxiv_id: str, title: str, abstract: str) -> str:
    return (
        PaperRepository(session)
        .upsert_paper(PaperCreate(title=title, abstract=abstract, arxiv_id=arxiv_id))
        .id
    )


def test_agent_search_papers(agent_env):
    from packages.storage.db import session_scope

    with session_scope() as session:
        _mk_paper(session, "2608.8001", "Transformer diarization", "Diarization methods.")
        _mk_paper(session, "2608.8002", "Cooking book", "Recipes only.")

    result = _search_papers("diarization")
    assert result.success is True
    assert result.data["count"] == 1
    assert (
        "diarization" in result.data["papers"][0]["title"].lower()
        or "diarization" in result.data["papers"][0]["abstract"].lower()
    )

    empty = _search_papers("quantum-astro-nonexistent")
    assert empty.success is True and empty.data["count"] == 0


def test_agent_list_papers_by_filter(agent_env):
    from packages.storage.db import session_scope

    with session_scope() as session:
        _mk_paper(session, "2608.8003", "Filter A", "Abstract A.")
        _mk_paper(session, "2608.8004", "Filter B", "Abstract B.")

    result = _list_papers_by_filter(status="unread", limit=10)
    assert result.success is True
    assert result.data["total"] == 2
    assert {i["read_status"] for i in result.data["items"]} == {"unread"}


def test_agent_batch_job_roundtrip(agent_env):
    from packages.storage.db import session_scope

    with session_scope() as session:
        pid = _mk_paper(session, "2608.8005", "Batch paper", "Batch abstract.")

    created = _batch_embed_papers([pid])
    assert created.success is True
    job_id = created.data["job_id"]

    status = _get_batch_job_status(job_id)
    assert status.success is True
    # C11 退出口：状态/进度投影自 durable ProcessUnreadBatch（queued + 1 task）
    assert status.data["status"] in ("queued", "running", "succeeded")
    assert status.data["total"] == 1
    assert "durable_job_id" in status.data

    # 空列表拒绝
    empty = _create_batch_job("skim", [])
    assert empty.success is False

    missing = _get_batch_job_status("no-such-job")
    assert missing.success is False


def test_agent_skim_and_embed(agent_env):
    from packages.storage.db import session_scope

    with session_scope() as session:
        pid = _mk_paper(session, "2608.8006", "Skim agent", "Agent skim abstract.")

    events = list(_skim_paper(pid))
    final = events[-1]
    assert final.success is True
    assert final.data["one_liner"] == FAKE_SKIM["one_liner"]

    # embed：已嵌入 → 跳过；未嵌入 → 执行
    from packages.storage.repositories import PaperRepository as PR

    with session_scope() as session:
        paper = PR(session).get_by_id(pid)
        paper.embedding = [0.1] * 8

    skipped = list(_embed_paper(pid))[-1]
    assert skipped.success is True and skipped.data["status"] == "already_embedded"

    with session_scope() as session:
        paper = PR(session).get_by_id(pid)
        paper.embedding = None

    embedded = list(_embed_paper(pid))[-1]
    assert embedded.success is True and embedded.data["status"] == "embedded"
