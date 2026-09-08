"""
端到端回归：主用户流程（导入论文 → skim/deep read → ask → brief）

覆盖 HTTP 路由 → service → repository 全链路，保护后续重构（application 层迁移、
durable execution 等）不破坏外部行为。对应重构路线图目标 A3。

测试边界：
- 不导入 apps.api.main（避免 MCP/batch lifespan、run_migrations 触碰真实库），
  改用真实 routers 组装最小 app；认证/中间件行为由 test_auth_tokens 覆盖。
- 不依赖真实 LLM / arXiv / 视觉模型：在类级 fake LLMClient、ArxivClient、
  VisionPdfReader（monkeypatch 自动恢复），后台任务线程同样生效。
- 每个测试使用独立 tmp 文件级 SQLite（WAL），rebind packages.storage.db 全局
  engine/SessionLocal；embedding 检索走 SQLite 分支的 Python cosine（生产同路径）。
- PDF 为 fitz 现场生成的单页真实 PDF，PdfTextExtractor 走真实解析。
"""

from __future__ import annotations

import json
import threading
import time
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

import packages.ai.pipelines.paper_pipelines as paper_pipelines_module
import packages.storage.db as db_module
import packages.storage.models  # noqa: F401  # 注册全部表到 Base.metadata
from packages.ai.seed_research import seed_sample
from packages.ai.vision_reader import VisionPdfReader
from packages.config import get_settings
from packages.domain.enums import (
    ClaimOrigin,
    ClaimStatus,
    EventAggregate,
    EventType,
    ReadStatus,
)
from packages.domain.schemas import PaperCreate
from packages.integrations.arxiv_client import ArxivClient
from packages.integrations.llm_client import LLMClient, LLMResult
from packages.storage.db import Base, session_scope
from packages.storage.models import (
    AnalysisReport,
    Claim,
    CollectionAction,
    Evidence,
    Paper,
    PromptTrace,
)
from packages.storage.repositories import ResearchEventRepository, SourceVersionRepository

# ---------- 确定性 fake 输出 ----------

_EMBED_DIM = 64

FAKE_SKIM = {
    "one_liner": "提出基于 transformer 的流式说话人分离方法，在 LibriSpeech 上相对降低 DER 12%。",
    "innovations": ["流式 transformer 分离架构", "多通道特征融合"],
    "keywords": ["speaker diarization", "transformer", "streaming"],
    "title_zh": "基于Transformer的流式说话人分离",
    "abstract_zh": "本文提出一种流式 transformer 说话人分离方法，并验证多通道融合带来的增益。",
    "relevance_score": 0.9,
}

FAKE_DEEP = {
    "method_summary": "Method: streaming transformer diarization with multi-channel feature fusion.",
    "experiments_summary": "Experiments: 12% relative DER reduction on LibriSpeech test set.",
    "ablation_summary": "Ablation: each proposed module contributes measurable gains.",
    "reviewer_risks": ["Generalization to far-field recordings is under-validated."],
}

FAKE_RAG_ANSWER = (
    "根据知识库：[fake-rag-answer] 该流式 transformer 方法在 LibriSpeech 上取得 12% 相对 DER 改善。"
)

# D3：deep read 触发的 claim_extraction stage 返回带精确引用的判断
FAKE_CLAIMS = {
    "claims": [
        {
            "statement": (
                "The paper proposes streaming transformer diarization with multi-channel fusion."
            ),
            "statement_zh": "该论文提出带多通道融合的流式 transformer 说话人分离方法。",
            "quote": "Streaming transformer diarization. Method and experiments.",
            "locator": {"section": "1"},
            "certainty": "conditional",
        }
    ]
}

PAPER_TITLES = {
    1: "Fake paper one: transformer-based streaming speaker diarization",
    2: "Fake paper two: multi-channel end-to-end diarization survey",
}


def _fake_summarize_text(
    self,
    prompt: str,
    stage: str,
    model_override: str | None = None,
    max_tokens: int | None = None,
) -> LLMResult:
    """按 stage 返回确定性 JSON，真实 complete_json 的解析路径照常执行"""
    payload = {
        "skim": FAKE_SKIM,
        "deep": FAKE_DEEP,
        "claim_extraction": FAKE_CLAIMS,
    }.get(stage, {"answer": FAKE_RAG_ANSWER})
    content = json.dumps(payload, ensure_ascii=False)
    return LLMResult(
        content=content,
        parsed_json=payload,
        input_tokens=128,
        output_tokens=64,
        input_cost_usd=0.0,
        output_cost_usd=0.0,
        total_cost_usd=0.0,
    )


def _fake_embed_text(self, text: str, dimensions: int = 1536) -> list[float]:
    """字符分桶的确定性向量：同文本同向量，相似文本有重叠分量"""
    vals = [0.0] * _EMBED_DIM
    for idx, ch in enumerate((text or "").encode("utf-8")):
        vals[idx % _EMBED_DIM] += float(ch) / 255.0
    scale = max(sum(v * v for v in vals) ** 0.5, 1e-6)
    return [v / scale for v in vals]


def _fake_fetch_latest(
    self,
    query: str,
    max_results: int = 20,
    sort_by: str = "submittedDate",
    start: int = 0,
    days_back: int = 0,
) -> list[PaperCreate]:
    if start > 0:  # 单页返回全部，后续页为空 → 不触发递归抓取
        return []
    return [
        PaperCreate(
            source="arxiv",
            source_id=f"2608.1000{i}",
            arxiv_id=f"2608.1000{i}",
            title=PAPER_TITLES[i],
            abstract=(
                f"Paper variant {i} proposes a novel streaming diarization approach {i}. "
                "It reports relative DER reductions on LibriSpeech with transformer models."
            ),
            publication_date=date(2026, 8, 30),
            metadata={},
        )
        for i in (1, 2)
    ]


def _make_fake_download_pdf(tmp_dir: Path):
    def _download(self, arxiv_id: str) -> str:
        path = tmp_dir / f"{arxiv_id.replace('/', '_')}.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 90), "Streaming transformer diarization. Method and experiments.")
        doc.save(str(path))
        doc.close()
        return str(path)

    return _download


# ---------- 测试环境 ----------


def _build_app() -> FastAPI:
    """真实 routers 组装的最小 app（不含 main.py 的 lifespan/MCP/认证）"""
    from fastapi.responses import JSONResponse

    from apps.api.routers import content, graph, jobs, papers, pipelines, research, topics
    from packages.domain.exceptions import AppError

    app = FastAPI()

    @app.exception_handler(AppError)
    async def _app_error_handler(_request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    app.include_router(papers.router)
    app.include_router(topics.router)
    app.include_router(pipelines.router)
    app.include_router(research.router)
    app.include_router(content.router)
    app.include_router(jobs.router)
    app.include_router(graph.router)
    return app


@pytest.fixture()
def e2e_env(tmp_path, monkeypatch):
    db_path = tmp_path / "e2e.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 60},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragma(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")  # API 线程轮询与后台任务线程并发
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(
        db_module, "SessionLocal", sessionmaker(bind=engine, autocommit=False, autoflush=False)
    )

    # 类级 fake：deps 模块已构造的单例实例同样生效（方法解析走类）
    monkeypatch.setattr(LLMClient, "summarize_text", _fake_summarize_text)
    monkeypatch.setattr(LLMClient, "embed_text", _fake_embed_text)
    monkeypatch.setattr(ArxivClient, "fetch_latest", _fake_fetch_latest)
    monkeypatch.setattr(ArxivClient, "download_pdf", _make_fake_download_pdf(tmp_path))
    monkeypatch.setattr(
        VisionPdfReader,
        "extract_page_descriptions",
        lambda self, pdf_path: "[fake vision] page 1: method and experiments described",
    )
    # 入库后的后台引用关联不在主链路内，置空避免引入图谱外部依赖
    monkeypatch.setattr(paper_pipelines_module, "_bg_auto_link", lambda paper_ids: None)
    # ingest 分页间隔 sleep(3) 在单页 fake 下无意义，跳过
    monkeypatch.setattr(time, "sleep", lambda _s: None)

    # 简报输出落到 tmp，避免污染仓库 data/
    brief_dir = tmp_path / "briefs"
    brief_dir.mkdir()
    monkeypatch.setattr(get_settings(), "brief_output_root", brief_dir)

    app = _build_app()
    yield SimpleNamespace(client=TestClient(app), engine=engine, tmp_path=tmp_path)
    engine.dispose()


def _wait_task(client: TestClient, task_id: str, timeout: float = 60.0) -> dict:
    """轮询 /tasks/{id} 直到完成；失败时给出任务错误信息

    C3 退出口后任务由 Executor 执行——测试进程内用 InlineExecutor 驱动
    durable store（与生产同一 handler/fencing 语义；不经 Go Core）。
    """
    from tests.helpers.inline_executor import InlineExecutor

    inline = InlineExecutor()
    deadline = time.monotonic() + timeout
    last: dict | None = None
    while time.monotonic() < deadline:
        inline.run_until_idle(timeout=1.0)
        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200, resp.text
        last = resp.json()
        if last.get("finished"):
            if not last.get("success"):
                pytest.fail(f"后台任务失败: {last.get('error')}")
            return last
        threading.Event().wait(0.05)
    pytest.fail(f"任务 {task_id} 超时未完成，最后状态: {last}")


def _ingest_two_papers(client: TestClient) -> list[dict]:
    resp = client.post("/ingest/arxiv", params={"query": "speaker diarization", "max_results": 2})
    assert resp.status_code == 200, resp.text
    task_id = resp.json()["task_id"]
    _wait_task(client, task_id)
    data = client.get(f"/tasks/{task_id}/result").json()
    assert data["total"] == 2
    # 任务结果携带 inserted_ids（paper uuid）；arxiv_id 从库读（mock 源固定）
    with session_scope() as session:
        rows = (
            session.execute(select(Paper).where(Paper.arxiv_id.in_(["2608.10001", "2608.10002"])))
            .scalars()
            .all()
        )
        return [{"id": r.id, "arxiv_id": r.arxiv_id, "title": r.title} for r in rows]


# ---------- 测试 ----------


def test_ingest_arxiv_creates_papers_records_and_dedupes(e2e_env):
    client = e2e_env.client

    papers = _ingest_two_papers(client)
    assert {p["arxiv_id"] for p in papers} == {"2608.10001", "2608.10002"}

    with session_scope() as session:
        rows = list(session.execute(select(Paper)).scalars())
        assert len(rows) == 2
        assert all(p.read_status == ReadStatus.unread for p in rows)
        # 入库行动记录已落库（pipeline_runs 观测双轨随 A 档退役——
        # 执行观测唯一权威是 durable task / Go 任务图）
        actions = list(
            session.execute(
                select(CollectionAction).where(CollectionAction.query == "speaker diarization")
            ).scalars()
        )
        assert len(actions) == 1
        # D2：入库同事务建 v1 SourceVersion + SourceAdded 事件
        for row in rows:
            versions = SourceVersionRepository(session).list_for_paper(row.id)
            assert len(versions) == 1 and versions[0].is_current
            added = ResearchEventRepository(session).list_by_aggregate(
                EventAggregate.source, row.id
            )
            assert [e.type for e in added].count(EventType.source_added) == 1

    # 同批再导一次：upsert 去重，不产生新论文（任务语义：提交 → 驱动 → 验库）
    resp = client.post("/ingest/arxiv", params={"query": "speaker diarization", "max_results": 2})
    assert resp.status_code == 200
    dedupe_task = resp.json()["task_id"]
    _wait_task(client, dedupe_task)
    dedupe_data = client.get(f"/tasks/{dedupe_task}/result").json()
    assert dedupe_data["total"] == 0  # handler 预过滤已存在论文 → 空 proposal 为合法 no-op
    with session_scope() as session:
        rows = list(session.execute(select(Paper)).scalars())
        assert len(rows) == 2
        # 去重导入不得追加版本
        for row in rows:
            assert len(SourceVersionRepository(session).list_for_paper(row.id)) == 1


def test_main_research_flow_import_skim_deep_ask_brief(e2e_env):
    """主用户流程回归：导入 → 下载 PDF → skim → deep read → embed → ask → brief"""
    client = e2e_env.client
    papers = _ingest_two_papers(client)
    paper_id = papers[0]["id"]
    title = papers[0]["title"]

    # ---- skim ----
    resp = client.post(f"/pipelines/skim/{paper_id}")
    assert resp.status_code == 200, resp.text
    task_id = resp.json()["task_id"]
    _wait_task(client, task_id)

    skim_result = client.get(f"/tasks/{task_id}/result").json()
    assert skim_result["one_liner"] == FAKE_SKIM["one_liner"]
    assert client.get("/tasks/active").status_code == 200

    with session_scope() as session:
        paper = session.execute(select(Paper).where(Paper.id == paper_id)).scalar_one()
        assert paper.read_status == ReadStatus.skimmed
        assert paper.metadata_json["keywords"] == FAKE_SKIM["keywords"]
        report = session.execute(
            select(AnalysisReport).where(AnalysisReport.paper_id == paper_id)
        ).scalar_one()
        assert report.skim_score == pytest.approx(0.9)
        assert (
            session.execute(select(PromptTrace).where(PromptTrace.stage == "skim"))
            .scalars()
            .first()
            is not None
        )

    # ---- 下载 PDF（deep read 前置）----
    resp = client.post(f"/papers/{paper_id}/download-pdf")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "downloaded"
    assert Path(resp.json()["pdf_path"]).exists()

    # ---- deep read ----
    resp = client.post(f"/pipelines/deep/{paper_id}")
    assert resp.status_code == 200, resp.text
    _wait_task(client, resp.json()["task_id"])
    deep_result = client.get(f"/tasks/{resp.json()['task_id']}/result").json()
    assert deep_result["method_summary"] == FAKE_DEEP["method_summary"]

    with session_scope() as session:
        paper = session.execute(select(Paper).where(Paper.id == paper_id)).scalar_one()
        assert paper.read_status == ReadStatus.deep_read

    # ---- D3：claims 由独立 extract_claims 任务承载（proposal 架构：
    # deep read 纯计算不写领域表；claims 指纹去重 apply 在权威面同事务）----
    resp = client.post(
        "/jobs/durable",
        json={
            "kind": "ExtractClaims",
            "capability": "extract_claims",
            "title": "claim 抽取",
            "input_ref": {"paper_id": paper_id, "source_text": "[fake source text for claims]"},
            "timeout_s": 300,
        },
    )
    assert resp.status_code == 200, resp.text
    claims_task_id = resp.json()["task_id"]
    _wait_task(client, claims_task_id)

    with session_scope() as session:
        extracted = (
            session.execute(select(Claim).where(Claim.origin == ClaimOrigin.papermind))
            .scalars()
            .all()
        )
        assert len(extracted) == 1
        assert extracted[0].status is ClaimStatus.pending_verification
        assert extracted[0].run_id
        claim_evidence = list(
            session.execute(select(Evidence).where(Evidence.claim_id == extracted[0].id)).scalars()
        )
        assert len(claim_evidence) == 1
        assert claim_evidence[0].quote == FAKE_CLAIMS["claims"][0]["quote"]
        assert claim_evidence[0].locator == {"section": "1"}

    # ---- embed ----
    resp = client.post(f"/pipelines/embed/{paper_id}")
    assert resp.status_code == 200, resp.text
    _wait_task(client, resp.json()["task_id"])
    with session_scope() as session:
        paper = session.execute(select(Paper).where(Paper.id == paper_id)).scalar_one()
        assert paper.embedding is not None and len(paper.embedding) == _EMBED_DIM

    # ---- ask（RAG：词法 + 语义双路检索）----
    resp = client.post("/rag/ask", json={"question": "speaker diarization transformer", "top_k": 5})
    assert resp.status_code == 200, resp.text
    ask_resp = resp.json()
    assert FAKE_RAG_ANSWER in ask_resp["answer"]
    assert paper_id in ask_resp["cited_paper_ids"]
    assert ask_resp["evidence"] and ask_resp["evidence"][0]["paper_id"] == paper_id

    # ---- daily brief ----
    resp = client.post("/brief/daily", json={})
    assert resp.status_code == 200, resp.text
    brief_task = resp.json()["task_id"]
    _wait_task(client, brief_task)
    brief_result = client.get(f"/tasks/{brief_task}/result").json()
    assert brief_result["email_sent"] is False
    assert brief_result["content_id"]

    detail = client.get(f"/generated/{brief_result['content_id']}")
    assert detail.status_code == 200, detail.text
    assert title in detail.json()["markdown"]

    listing = client.get("/generated/list", params={"type": "daily_brief"})
    assert listing.status_code == 200
    assert any(item["id"] == brief_result["content_id"] for item in listing.json()["items"])


def test_rag_ask_without_context_returns_fallback(e2e_env):
    """空库提问：返回兜底文案而非报错（前端直接渲染该响应）"""
    resp = e2e_env.client.post("/rag/ask", json={"question": "anything obscure", "top_k": 5})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "没有足够上下文" in body["answer"]
    assert body["cited_paper_ids"] == []


def test_research_state_query_endpoints(e2e_env):
    """D4：question 聚合 / claims 列表 / 证据追溯 / diff 四个只读端点"""
    client = e2e_env.client
    _ingest_two_papers(client)
    with session_scope() as session:
        stats = seed_sample(session, arxiv_ids=["2608.10001", "2608.10002"])
        question_id = stats["question_id"]

    # 聚合视图
    resp = client.get(f"/research/questions/{question_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"].startswith("视听说话人分离")
    assert body["claim_counts"]["by_status"] == {"confirmed": 2, "draft": 1}

    # claims 列表 + 证据计数
    resp = client.get(f"/research/questions/{question_id}/claims")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 3
    author_items = [i for i in items if i["origin"] == "author"]
    assert len(author_items) == 2
    assert all(i["status"] == "confirmed" and i["evidence_count"] == 1 for i in author_items)

    # 证据追溯：claim → evidence → source_version → paper
    claim_id = author_items[0]["id"]
    resp = client.get(f"/research/claims/{claim_id}/evidence")
    assert resp.status_code == 200, resp.text
    detail = resp.json()
    assert detail["claim"]["id"] == claim_id
    evidence = detail["evidence"][0]
    assert evidence["locator"] == {"section": "abstract"}
    assert evidence["source_version"]["version_label"] == 1
    assert evidence["source_version"]["paper"]["arxiv_id"] in {"2608.10001", "2608.10002"}

    # diff：added/confirmed/strengthened 至少齐备
    resp = client.get(f"/research/questions/{question_id}/diff")
    assert resp.status_code == 200, resp.text
    diff_kinds = {item["diff_kind"] for item in resp.json()["items"]}
    assert {"added", "confirmed", "strengthened"} <= diff_kinds

    # 时间过滤：最近 1 小时应包含全部事件
    resp = client.get(f"/research/questions/{question_id}/diff", params={"since_hours": 1})
    assert resp.json()["items"]

    # 不存在 → 404（AppError 处理器）
    resp = client.get("/research/questions/doesnotexist")
    assert resp.status_code == 404


def test_research_export_endpoints(e2e_env):
    """D5：Research Object 导出——JSON/Markdown、确定性 content_hash"""
    client = e2e_env.client
    _ingest_two_papers(client)
    with session_scope() as session:
        stats = seed_sample(session, arxiv_ids=["2608.10001", "2608.10002"])
        question_id = stats["question_id"]

    # JSON 导出
    resp = client.get(f"/research/questions/{question_id}/export")
    assert resp.status_code == 200, resp.text
    ro = resp.json()
    assert ro["content_hash"].startswith("sha256:")
    obj = ro["research_object"]
    assert obj["ro_type"] == "papermind-research-object"
    assert len(obj["claims"]) == 3
    assert len(obj["evidence"]) == 2
    assert len(obj["relations"]) == 2
    assert len(obj["source_versions"]) == 2
    assert obj["source_versions"][0]["content_hash"]
    assert obj["provenance"]["research_runs"], "seed 的 papermind 综合判断应带 Run"

    # 确定性：同一数据两次导出 content_hash 一致（generated_at 不参与 hash）
    ro_again = client.get(f"/research/questions/{question_id}/export").json()
    assert ro_again["content_hash"] == ro["content_hash"]

    # Markdown 导出
    resp = client.get(f"/research/questions/{question_id}/export", params={"format": "markdown"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/markdown")
    markdown = resp.text
    assert "papermind-research-object" not in markdown  # renderer 输出人读内容
    assert obj["claims"][0]["statement"] in markdown
    assert ro["content_hash"] in markdown
    assert "Provenance" in markdown
    # 非法 format → 422
    assert (
        client.get(
            f"/research/questions/{question_id}/export", params={"format": "pdf"}
        ).status_code
        == 422
    )


def test_papers_read_endpoints_use_application_layer(e2e_env, monkeypatch):
    """B2：papers 读路径改调 application.queries——返回形状逐字段兼容"""
    client = e2e_env.client
    papers = _ingest_two_papers(client)
    pid = papers[0]["id"]

    # latest
    resp = client.get("/papers/latest", params={"page_size": 10})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2 and body["page"] == 1
    item = next(i for i in body["items"] if i["id"] == pid)
    assert item["title"] == PAPER_TITLES[1]
    assert item["read_status"] == "unread" and item["topics"] == [] and item["tags"] == []

    # detail
    resp = client.get(f"/papers/{pid}")
    assert resp.status_code == 200, resp.text
    detail = resp.json()
    assert detail["id"] == pid and detail["has_embedding"] is False
    assert detail["skim_report"] is None and detail["deep_report"] is None

    # 404 形状兼容（detail 字段）
    resp = client.get("/papers/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404 and "detail" in resp.json()

    # similar（无 embedding → 空）
    resp = client.get(f"/papers/{pid}/similar")
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []

    # search-multi：fake 渠道，不触网
    from packages.integrations import registry as channel_registry_module

    class _FakeChannel:
        def fetch(self, query, max_results):
            return []

    monkeypatch.setattr(
        channel_registry_module.ChannelRegistry,
        "register_default_channels",
        classmethod(lambda cls: None),
    )
    monkeypatch.setattr(
        channel_registry_module.ChannelRegistry,
        "get",
        classmethod(lambda cls, name, **kwargs: _FakeChannel()),
    )
    resp = client.post(
        "/papers/search-multi", params={"query": "diarization", "channels": ["arxiv"]}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["channel_stats"]["arxiv"]["total"] == 0


def test_b7_query_endpoints(e2e_env):
    """B7：topics/stats/distribution、actions、pipelines runs、tasks、trends、graph 全部经 application 层"""
    client = e2e_env.client
    _ingest_two_papers(client)

    # topics 读路径
    resp = client.get("/topics")
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []
    assert client.get("/topics/stats").status_code == 200
    assert client.get("/topics/distribution").status_code == 200

    # actions（ingest 已产生行动记录）
    resp = client.get("/actions")
    assert resp.status_code == 200, resp.text
    actions = resp.json()
    assert actions["total"] == 1
    action_id = actions["items"][0]["id"]
    detail = client.get(f"/actions/{action_id}")
    assert detail.status_code == 200 and detail.json()["id"] == action_id
    papers = client.get(f"/actions/{action_id}/papers")
    assert papers.status_code == 200 and len(papers.json()["items"]) == 2
    assert client.get("/actions/no-such-action").status_code == 404

    # pipelines runs + tasks（过渡观测）
    # 观测双轨已退役：/pipelines/runs 保持 200 空列表；权威观测是 /jobs
    runs = client.get("/pipelines/runs")
    assert runs.status_code == 200
    jobs = client.get("/jobs")
    assert jobs.status_code == 200 and jobs.json()["items"]
    active = client.get("/tasks/active")
    assert active.status_code == 200 and "tasks" in active.json()

    # trends / today（LLM fake 生效）
    assert client.get("/trends/hot", params={"days": 7, "top_k": 5}).status_code == 200
    assert client.get("/trends/emerging", params={"days": 14}).status_code == 200
    assert client.get("/today").status_code == 200

    # graph GET 查询族（空库 → 空结构不报错）
    assert client.get("/graph/overview").status_code == 200
    resp = client.get("/graph/timeline", params={"keyword": "diarization", "limit": 10})
    assert resp.status_code == 200, resp.text
    assert client.get("/graph/cocitation-clusters", params={"min_cocite": 2}).status_code == 200


def test_b8_command_endpoints(e2e_env):
    """B8：写路径命令面——论文 flag 切换 / 引用同步任务提交 / daily-report generate-only"""
    client = e2e_env.client
    papers = _ingest_two_papers(client)
    pid = papers[0]["id"]

    # 论文 flag 切换（commands/papers.toggle_paper_flag）
    resp = client.patch(f"/papers/{pid}/favorite")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": pid, "favorited": True}
    assert client.patch(f"/papers/{pid}/favorite").json()["favorited"] is False
    assert client.patch(f"/papers/{pid}/reject").json()["rejected"] is True

    # 引用同步任务提交（commands/graph → durable Job；task_id 即 durable Task id）
    resp = client.post("/citations/sync/incremental")
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["task_id"]) == 32  # durable Task id（UUIDv7 hex）

    # daily-report generate-only（同步命令，LLM fake 生效）
    resp = client.post("/jobs/daily-report/generate-only", params={"use_cache": False})
    assert resp.status_code == 200, resp.text
    assert "html" in resp.json() and resp.json()["used_cache"] is False


def test_c3_unified_job_endpoints(e2e_env):
    """C3：durable Job 统一观察面——/jobs 列表、/jobs/{id} graph、/tasks durability 优先"""
    client = e2e_env.client
    papers = _ingest_two_papers(client)
    pid = papers[0]["id"]

    # 提交 skim（现走 durable 桥接）
    resp = client.post(f"/pipelines/skim/{pid}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    task_id, job_id = body["task_id"], body["job_id"]

    # 等待完成（tracker 通道执行；durable 状态由桥接同步）
    _wait_task(client, task_id)

    # GET /jobs：skim 的 Job 应出现在列表且 succeeded
    resp = client.get("/jobs", params={"kind": "StartSkim"})
    assert resp.status_code == 200, resp.text
    jobs = resp.json()["items"]
    matched = [j for j in jobs if j["id"] == job_id]
    assert matched and matched[0]["status"] == "succeeded"

    # GET /jobs/{id}：graph 含子 Task
    resp = client.get(f"/jobs/{job_id}")
    assert resp.status_code == 200, resp.text
    graph = resp.json()
    assert graph["kind"] == "StartSkim"
    assert len(graph["tasks"]) == 1
    assert graph["tasks"][0]["capability"] == "skim_paper"
    assert graph["tasks"][0]["status"] == "succeeded"
    # C3 退出口：新提交的 task_id 即 durable id，不再写 external_ref 过渡引用
    assert graph["tasks"][0]["external_ref"] is None

    # /tasks/{tracker_id}：durability 优先——重启后 tracker 丢失也能查到
    resp = client.get(f"/tasks/{task_id}")
    assert resp.status_code == 200, resp.text
    view = resp.json()
    assert view["durable"] is True and view["finished"] is True and view["success"] is True

    # /tasks/{id}/result：durability 侧结果
    resp = client.get(f"/tasks/{task_id}/result")
    assert resp.status_code == 200, resp.text
    assert resp.json()["one_liner"] == FAKE_SKIM["one_liner"]

    # /tasks/active：durable 在途语义——已完成任务不再出现在列表中
    resp = client.get("/tasks/active")
    assert resp.status_code == 200, resp.text
    merged = {t["task_id"]: t for t in resp.json()["tasks"]}
    assert task_id not in merged


# ---------- F7：surface contract 测试 ----------


def test_f7_surface_contract_papers(e2e_env):
    """F7：papers 四面数据一致——detail vs latest vs /papers/search-multi"""
    client = e2e_env.client
    papers = _ingest_two_papers(client)
    pid = papers[0]["id"]

    detail = client.get(f"/papers/{pid}").json()
    latest = client.get("/papers/latest", params={"page_size": 10}).json()
    item = next(i for i in latest["items"] if i["id"] == pid)

    assert detail["id"] == item["id"]
    assert detail["title"] == item["title"]
    assert detail["arxiv_id"] == item["arxiv_id"]
    assert detail["read_status"] == item["read_status"]
    assert detail["has_embedding"] == item["has_embedding"]

    # search 也应命中
    search = client.post("/papers/search-multi", params={"query": "diarization"}).json()
    # search-multi 走外部渠道，空 fake 不产出——只验证端点可用
    assert "channel_stats" in search


def test_f7_surface_contract_research_state(e2e_env):
    """F7：research state 三面一致——claims 列表 vs evidence 详情 vs diff"""
    client = e2e_env.client
    _ingest_two_papers(client)

    with session_scope() as session:
        from sqlalchemy import select

        from packages.ai.seed_research import seed_sample
        from packages.storage.models import ResearchQuestion

        seed_sample(session, arxiv_ids=["2608.10001", "2608.10002"])
        rq = session.execute(select(ResearchQuestion)).scalars().first()
        qid = rq.id

    claims = client.get(f"/research/questions/{qid}/claims").json()["items"]
    author_claims = [c for c in claims if c["origin"] == "author"]
    assert len(author_claims) == 2
    assert all(c["status"] == "confirmed" for c in author_claims)

    for c in author_claims:
        ev = client.get(f"/research/claims/{c['id']}/evidence").json()
        assert ev["claim"]["id"] == c["id"]
        assert ev["claim"]["status"] == c["status"]
        for e in ev["evidence"]:
            assert e["source_version"]["paper"]["arxiv_id"] in ("2608.10001", "2608.10002")

    diff = client.get(f"/research/questions/{qid}/diff").json()
    kinds = {d["diff_kind"] for d in diff["items"]}
    assert {"added", "confirmed", "strengthened"} <= kinds


def test_f7_surface_contract_jobs(e2e_env):
    """F7：jobs graph 与 durable store 一致——tasks/attempts/paper_id"""
    client = e2e_env.client
    papers = _ingest_two_papers(client)
    pid = papers[0]["id"]

    resp = client.post(f"/pipelines/skim/{pid}")
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    from tests.helpers.inline_executor import InlineExecutor

    inline = InlineExecutor(capabilities=["skim_paper"])
    deadline = time.monotonic() + 30
    status = ""
    while time.monotonic() < deadline:
        inline.run_until_idle(timeout=1.0)
        graph = client.get(f"/jobs/{job_id}").json()
        status = graph["status"]
        if status in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(0.1)

    assert status == "succeeded"
    assert len(graph["tasks"]) >= 1
    for t in graph["tasks"]:
        assert t["capability"]
        assert t["status"] in ("succeeded", "failed", "dead_letter")

    for a in graph.get("attempts", []):
        matching = [t for t in graph["tasks"] if t["id"] == a["task_id"]]
        assert matching
