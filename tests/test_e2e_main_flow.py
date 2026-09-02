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
from packages.ai.vision_reader import VisionPdfReader
from packages.config import get_settings
from packages.domain.enums import ReadStatus
from packages.domain.schemas import PaperCreate
from packages.integrations.arxiv_client import ArxivClient
from packages.integrations.llm_client import LLMClient, LLMResult
from packages.storage.db import Base, session_scope
from packages.storage.models import AnalysisReport, Paper, PipelineRun, PromptTrace

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
    payload = {"skim": FAKE_SKIM, "deep": FAKE_DEEP}.get(stage, {"answer": FAKE_RAG_ANSWER})
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
                "We study streaming speaker diarization with transformer architectures. "
                f"Paper variant {i} reports relative DER reductions on LibriSpeech."
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
    from apps.api.routers import content, papers, pipelines, topics

    app = FastAPI()
    app.include_router(papers.router)
    app.include_router(topics.router)
    app.include_router(pipelines.router)
    app.include_router(content.router)
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
    """轮询 /tasks/{id} 直到完成；失败时给出任务错误信息"""
    deadline = time.monotonic() + timeout
    last: dict | None = None
    while time.monotonic() < deadline:
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
    data = resp.json()
    assert data["ingested"] == 2
    assert len(data["papers"]) == 2
    return data["papers"]


# ---------- 测试 ----------


def test_ingest_arxiv_creates_papers_records_and_dedupes(e2e_env):
    client = e2e_env.client

    papers = _ingest_two_papers(client)
    assert {p["arxiv_id"] for p in papers} == {"2608.10001", "2608.10002"}

    with session_scope() as session:
        rows = list(session.execute(select(Paper)).scalars())
        assert len(rows) == 2
        assert all(p.read_status == ReadStatus.unread for p in rows)
        # 入库行动记录与 pipeline_runs 均已落库
        runs = list(
            session.execute(
                select(PipelineRun).where(PipelineRun.pipeline_name == "ingest_arxiv")
            ).scalars()
        )
        assert len(runs) == 1
        assert runs[0].error_message is None

    # 同批再导一次：upsert 去重，不产生新论文
    resp = client.post("/ingest/arxiv", params={"query": "speaker diarization", "max_results": 2})
    assert resp.status_code == 200
    assert resp.json()["ingested"] == 0
    with session_scope() as session:
        assert len(list(session.execute(select(Paper)).scalars())) == 2


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
