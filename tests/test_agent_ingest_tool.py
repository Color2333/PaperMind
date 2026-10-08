"""ingest 工具任务语义：提交 import_selected durable 任务 + 轮询观察面进度

直写路径已退役（proposal 模式去重收尾）：_ingest_arxiv 只提交任务并桥接
durable 观察面，不再直写领域表。入库落库/主题关联/幂等由
test_phase3_apply_dispatch（apply_ingest_papers_proposal）与 Go apply 测试覆盖。
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from packages.ai.tools.handlers.ingest import _ingest_arxiv, _search_arxiv
from packages.ai.tools.types import ToolProgress
from packages.domain.schemas import PaperCreate
from packages.integrations.arxiv_client import ArxivClient
from packages.integrations.llm_client import LLMResult


@pytest.fixture()
def search_env(isolated_db, monkeypatch):
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

    monkeypatch.setattr(ArxivClient, "fetch_latest", _fake_fetch_latest)
    return isolated_db


def test_search_arxiv_tool(search_env):
    result = _search_arxiv("diarization", max_results=5)
    assert result.success is True
    assert result.data["count"] == 1
    assert result.data["candidates"][0]["arxiv_id"] == "2608.9001"


@pytest.fixture()
def task_env(monkeypatch):
    """任务语义桩：捕获 submit_job 参数 + 可编程的观察面（info/result）"""
    state = {"submitted": None, "info": {}, "result": {}}

    def _fake_submit_job(**kw):
        state["submitted"] = kw
        return {"task_id": "task-it-1", "job_id": "job-it-1"}

    def _fake_get_task_info(task_id):
        return state["info"].get(task_id)

    def _fake_get_task_result(task_id):
        return state["result"].get(task_id)

    monkeypatch.setattr("packages.application.commands.jobs.submit_job", _fake_submit_job)
    monkeypatch.setattr("packages.application.queries.tasks.get_task_info", _fake_get_task_info)
    monkeypatch.setattr("packages.application.queries.tasks.get_task_result", _fake_get_task_result)
    return state


def test_ingest_arxiv_submits_import_selected_task(task_env):
    """工具不直写：提交 import_selected 任务（input_ref 携带选中 ID）+ 返回 task_id"""
    task_env["info"]["task-it-1"] = {"finished": True, "success": True}
    task_env["result"]["task-it-1"] = {"total": 1, "inserted_ids": ["p-1"], "topic_id": None}

    events = list(_ingest_arxiv("agent test topic", arxiv_ids=["2608.9001"]))
    submitted = task_env["submitted"]
    assert submitted["capability"] == "import_selected"
    assert submitted["input_ref"]["arxiv_ids"] == ["2608.9001"]
    assert submitted["input_ref"]["query"] == "agent test topic"

    final = events[-1]
    assert final.success is True
    assert final.data["task_id"] == "task-it-1"
    assert final.data["total"] == 1
    assert "入库 1 篇" in final.summary


def test_ingest_arxiv_reports_zero_total_as_failure(task_env):
    """任务完成但 total=0（全部已存在/未返回）→ success=False"""
    task_env["info"]["task-it-1"] = {"finished": True, "success": True}
    task_env["result"]["task-it-1"] = {"total": 0, "inserted_ids": [], "topic_id": None}

    events = list(_ingest_arxiv("agent test topic", arxiv_ids=["2608.9999"]))
    final = events[-1]
    assert final.success is False
    assert "入库 0 篇" in final.summary


def test_ingest_arxiv_task_failure_reports_error(task_env):
    """任务终态失败 → success=False + 任务 error"""
    task_env["info"]["task-it-1"] = {
        "finished": True,
        "success": False,
        "error": "元数据获取失败",
    }

    events = list(_ingest_arxiv("agent test topic", arxiv_ids=["2608.9001"]))
    final = events[-1]
    assert final.success is False
    assert "元数据获取失败" in final.summary


def test_ingest_arxiv_progress_bridged(task_env, monkeypatch):
    """观察面 message 变化 → ToolProgress 透传"""
    task_env["info"]["task-it-1"] = {
        "finished": False,
        "success": None,
        "message": "已获取 1/2 篇元数据",
        "progress": 0.5,
    }
    task_env["result"]["task-it-1"] = {"total": 1, "inserted_ids": ["p-1"], "topic_id": None}
    calls = {"n": 0}

    def _info(task_id):
        calls["n"] += 1
        if calls["n"] == 1:
            return task_env["info"]["task-it-1"]
        return {"finished": True, "success": True}

    monkeypatch.setattr("packages.application.queries.tasks.get_task_info", _info)

    events = list(_ingest_arxiv("agent test topic", arxiv_ids=["2608.9001"]))
    progresses = [e for e in events if isinstance(e, ToolProgress)]
    assert progresses, "进度事件应透传"
    assert any("元数据" in p.message for p in progresses)
    final = events[-1]
    assert final.success is True


def test_ingest_arxiv_no_ids_no_submit(task_env):
    events = list(_ingest_arxiv("agent test topic", arxiv_ids=[]))
    assert task_env["submitted"] is None, "未选中论文不得提交任务"
    assert events[-1].success is False


def test_ingest_ieee_handler_missing_key_raises(search_env):
    """IEEE handler：API Key 未配置 → 显式 RuntimeError（任务面可见失败）"""
    from packages.ai import task_handlers as th

    class FakeIeee:
        api_key = None

    import packages.integrations.ieee_client as ieee_mod

    orig = ieee_mod.IeeeClient
    ieee_mod.IeeeClient = FakeIeee
    try:
        with pytest.raises(RuntimeError, match="IEEE_API_KEY"):
            th.ingest_ieee_proposal(query="test", max_results=5)
    finally:
        ieee_mod.IeeeClient = orig


def test_ingest_ieee_handler_returns_proposal(search_env, monkeypatch):
    """IEEE handler：网络抓取留 handler，DOI/合成键只读去重，返回 ingest_papers proposal"""
    from packages.ai import task_handlers as th

    class FakePaper:
        def __init__(self, doc_id, doi):
            self.arxiv_id = None
            self.source_id = doc_id
            self.doi = doi
            self.source = "ieee"
            self.title = f"IEEE paper {doc_id}"
            self.abstract = ""

        def model_dump(self, mode="json"):
            return {
                "arxiv_id": self.arxiv_id,
                "source": self.source,
                "source_id": self.source_id,
                "doi": self.doi,
                "title": self.title,
                "abstract": self.abstract,
                "metadata": {},
            }

    class FakeIeee:
        api_key = "k"

        def fetch_by_keywords(self, query, max_results=20):
            return [FakePaper("10185093", "10.1109/a"), FakePaper("10185094", "10.1109/b")]

    class FakeRepo:
        def list_existing_dois(self, dois):
            return {"10.1109/a"}  # 第一篇 DOI 已存在

        def list_existing_arxiv_ids(self, ids):
            return set()

    monkeypatch.setattr("packages.integrations.ieee_client.IeeeClient", FakeIeee)

    class _Sess:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("packages.storage.db.session_scope", lambda: _Sess())
    monkeypatch.setattr("packages.storage.repositories.PaperRepository", lambda s: FakeRepo())

    out = th.ingest_ieee_proposal(query="federated", max_results=5)
    proposal = out["proposal"]
    assert proposal["kind"] == "ingest_papers"
    assert proposal["action_type"] == "manual_collect"
    papers = proposal["papers"]
    assert len(papers) == 1  # DOI 已存在的被过滤
    assert papers[0]["arxiv_id"] == "ieee:10185094"  # 合成键约定
    assert papers[0]["source"] == "ieee"
    assert papers[0]["doi"] == "10.1109/b"


def test_llm_fake_still_shapes_json():
    """守门：LLMResult 构造形状未漂移（handler 依赖 parsed_json）"""
    payload = {"one_liner": "x"}
    r = LLMResult(
        content=json.dumps(payload),
        parsed_json=payload,
        input_tokens=1,
        output_tokens=1,
        input_cost_usd=0.0,
        output_cost_usd=0.0,
        total_cost_usd=0.0,
    )
    assert r.parsed_json["one_liner"] == "x"
