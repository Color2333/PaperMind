"""B6（收尾）：ingest 工具改调 application——入库→主题→PDF→embed+skim 全链路"""

from __future__ import annotations

import json
from datetime import date

import pytest

from packages.ai.tools.handlers.ingest import _ingest_arxiv, _search_arxiv
from packages.ai.tools.types import ToolProgress
from packages.domain.schemas import PaperCreate
from packages.integrations.arxiv_client import ArxivClient
from packages.integrations.llm_client import LLMClient, LLMResult
from packages.storage.db import session_scope
from packages.storage.models import Paper, TopicSubscription


@pytest.fixture()
def ingest_env(isolated_db, monkeypatch, tmp_path):
    paper = PaperCreate(
        source="arxiv",
        source_id="2608.9001",
        arxiv_id="2608.9001",
        title="Ingest tool paper",
        abstract="Streaming diarization for agents. Second sentence.",
        publication_date=date(2026, 8, 30),
        metadata={},
    )

    def _fake_fetch_latest(self, query, max_results=20, sort_by="relevance", start=0, days_back=0):
        return [paper] if start == 0 else []

    def _fake_fetch_by_ids(self, ids):
        return []

    def _fake_download(self, arxiv_id):
        return str(tmp_path / f"{arxiv_id}.pdf")

    def _fake_summarize(self, prompt, stage, model_override=None, max_tokens=None):
        payload = {
            "one_liner": "Ingest fake：流式分离有效。",
            "innovations": ["A"],
            "keywords": ["k"],
        }
        return LLMResult(
            content=json.dumps(payload, ensure_ascii=False),
            parsed_json=payload,
            input_tokens=8,
            output_tokens=4,
            input_cost_usd=0.0,
            output_cost_usd=0.0,
            total_cost_usd=0.0,
        )

    def _fake_embed(self, text, dimensions=1536):
        return [0.3] * 8

    monkeypatch.setattr(ArxivClient, "fetch_latest", _fake_fetch_latest)
    monkeypatch.setattr(ArxivClient, "fetch_by_ids", _fake_fetch_by_ids)
    monkeypatch.setattr(ArxivClient, "download_pdf", _fake_download)
    monkeypatch.setattr(LLMClient, "summarize_text", _fake_summarize)
    monkeypatch.setattr(LLMClient, "embed_text", _fake_embed)
    return isolated_db


def test_search_arxiv_tool(ingest_env):
    result = _search_arxiv("diarization", max_results=5)
    assert result.success is True
    assert result.data["count"] == 1
    assert result.data["candidates"][0]["arxiv_id"] == "2608.9001"


def test_ingest_arxiv_ids_not_found_reports_failure(ingest_env, monkeypatch):
    """REVIEW P1-2：选中的 ID 未从 arXiv 返回 → success=False + 可行动原因"""
    monkeypatch.setattr(ArxivClient, "fetch_latest", lambda self, **kw: [])
    monkeypatch.setattr(ArxivClient, "fetch_by_ids", lambda self, ids: [])

    events = list(_ingest_arxiv("agent test topic", arxiv_ids=["2608.9999"]))
    final = events[-1]
    assert final.success is False, "完全失败不得报告为成功"
    assert final.data["status"] == "failed"
    assert "未从 arXiv 返回" in final.summary


def test_ingest_arxiv_all_upsert_failure_reports_failure(ingest_env, monkeypatch):
    """REVIEW P1-2：全部写库失败 → success=False，摘要带失败数量与原因"""
    from packages.storage.repositories import PaperRepository

    def _boom(self, data):
        raise RuntimeError("db down")

    monkeypatch.setattr(PaperRepository, "upsert_paper", _boom)

    events = list(_ingest_arxiv("agent test topic", arxiv_ids=["2608.9001"]))
    final = events[-1]
    assert final.success is False
    assert final.data["status"] == "failed"
    assert final.data["total"] == 0
    assert len(final.data["failed"]) == 1
    assert "1 篇失败" in final.summary
    assert "db down" in final.summary


def test_ingest_arxiv_partial_reports_partial(ingest_env, monkeypatch):
    """REVIEW P1-2：部分成功 → success=True 且 data.status='partial'"""
    from packages.storage.repositories import PaperRepository

    orig_upsert = PaperRepository.upsert_paper

    def _flaky(self, data):
        if data.arxiv_id == "2608.9002":
            raise RuntimeError("second paper fails")
        return orig_upsert(self, data)

    monkeypatch.setattr(PaperRepository, "upsert_paper", _flaky)
    monkeypatch.setattr(
        ArxivClient,
        "fetch_latest",
        lambda self, **kw: (
            [
                PaperCreate(
                    source="arxiv",
                    source_id="2608.9001",
                    arxiv_id="2608.9001",
                    title="Paper one",
                    abstract="First.",
                    publication_date=date(2026, 8, 30),
                    metadata={},
                ),
                PaperCreate(
                    source="arxiv",
                    source_id="2608.9002",
                    arxiv_id="2608.9002",
                    title="Paper two",
                    abstract="Second.",
                    publication_date=date(2026, 8, 30),
                    metadata={},
                ),
            ]
            if kw.get("start", 0) == 0
            else []
        ),
    )

    events = list(_ingest_arxiv("agent test topic", arxiv_ids=["2608.9001", "2608.9002"]))
    final = events[-1]
    assert final.success is True
    assert final.data["status"] == "partial"
    assert final.data["total"] == 1
    assert len(final.data["failed"]) == 1
    assert "1 篇失败已跳过" in final.summary


def test_ingest_arxiv_full_flow(ingest_env):
    events = list(_ingest_arxiv("agent test topic", arxiv_ids=["2608.9001"]))
    progresses = [e for e in events if isinstance(e, ToolProgress)]
    final = events[-1]
    assert final.success is True
    assert final.data["total"] == 1
    assert final.data["embedded"] == 1
    assert final.data["skimmed"] == 1
    assert final.data["topic"] == "agent test topic"
    assert final.data["suggest_subscribe"] is True
    assert final.data["paper_ids"], "应返回入库论文 id"
    assert progresses, "进度事件应透传"

    with session_scope() as session:
        paper = session.query(Paper).filter(Paper.arxiv_id == "2608.9001").one()
        assert paper.read_status.value == "skimmed"  # embed+skim 自动执行
        topic = session.query(TopicSubscription).filter_by(name="agent test topic").one()
        assert topic.enabled is False  # 自动建的主题默认不启用订阅

    # 重复入库：upsert 去重，不再新增论文
    events2 = list(_ingest_arxiv("agent test topic", arxiv_ids=["2608.9001"]))
    final2 = events2[-1]
    assert final2.success is True and final2.data["total"] == 1
