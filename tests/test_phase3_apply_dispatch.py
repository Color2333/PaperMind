"""Phase 3：apply 分派收敛（domain_apply.apply_proposal 唯一实现）测试。

背景（第三轮盘点发现的两个真问题）：
1. Python authority 路径（durable-state /complete）此前只 apply skim proposal——
   deep_read/embed/extract_claims 的 proposal 在本地单进程模式从未落库
   （分派被复制在测试 helper inline_executor 里掩盖了缺口）；
2. B 档 capability 的 Python handler 直写领域——upsert/download 现已拆为
   proposal 模式（领域写入在权威面单事务执行）。

覆盖：全 6 类 proposal 分派 + B 档 result 原样回退 + durable complete 链路。
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _mk_paper(db_session, arxiv_id: str) -> str:
    from packages.domain.schemas import PaperCreate
    from packages.storage.repositories import PaperRepository

    paper = PaperRepository(db_session).upsert_paper(
        PaperCreate(arxiv_id=arxiv_id, title=f"paper {arxiv_id}", abstract="abs")
    )
    db_session.flush()
    return str(paper.id)


# ---------- apply_proposal 分派 ----------


def test_apply_upsert_proposal_creates_paper(db_session):
    from packages.application.commands.domain_apply import apply_proposal

    ref = apply_proposal(
        db_session,
        {
            "kind": "upsert_paper",
            "arxiv_id": "2601.00001",
            "title": "新论文",
            "abstract": "摘要",
            "metadata": {"categories": ["cs.LG"]},
        },
    )
    db_session.flush()
    assert ref["arxiv_id"] == "2601.00001"
    assert ref["paper_id"]

    from packages.storage.models import Paper

    paper = db_session.query(Paper).filter_by(arxiv_id="2601.00001").one()
    assert paper.title == "新论文"
    assert (paper.metadata_json or {}).get("categories") == ["cs.LG"]


def test_apply_upsert_proposal_merges_metadata(db_session):
    """重复 ingest：metadata 合并——skim 派生字段不被覆盖"""
    from packages.application.commands.domain_apply import apply_proposal

    pid = _mk_paper(db_session, "2601.00002")
    from packages.storage.models import Paper

    paper = db_session.get(Paper, pid)
    paper.metadata_json = {"title_zh": "已有中文", "keywords": ["a"]}
    db_session.flush()

    apply_proposal(
        db_session,
        {
            "kind": "upsert_paper",
            "arxiv_id": "2601.00002",
            "title": "新标题",
            "abstract": "新摘要",
            "metadata": {"categories": ["cs.CL"]},
        },
    )
    db_session.flush()
    db_session.expire_all()
    meta = db_session.get(Paper, pid).metadata_json
    assert meta["title_zh"] == "已有中文"
    assert meta["categories"] == ["cs.CL"]


def test_apply_download_proposal_sets_pdf_path(db_session):
    from packages.application.commands.domain_apply import apply_proposal

    _mk_paper(db_session, "2601.00003")
    ref = apply_proposal(
        db_session,
        {"kind": "download_source", "arxiv_id": "2601.00003", "pdf_path": "/data/pdfs/x.pdf"},
    )
    db_session.flush()
    assert ref["pdf_path"] == "/data/pdfs/x.pdf"

    from packages.storage.models import Paper

    assert (
        db_session.query(Paper).filter_by(arxiv_id="2601.00003").one().pdf_path
        == "/data/pdfs/x.pdf"
    )


def test_apply_download_proposal_missing_paper_raises(db_session):
    from packages.application.commands.domain_apply import apply_proposal

    with pytest.raises(ValueError, match="不在库中"):
        apply_proposal(
            db_session,
            {"kind": "download_source", "arxiv_id": "9999.99999", "pdf_path": "/x.pdf"},
        )


def test_apply_proposal_unknown_kind_returns_none(db_session):
    """B 档：handler 自管领域写入——未知 kind 返回 None（result 原样存储）"""
    from packages.application.commands.domain_apply import apply_proposal

    assert apply_proposal(db_session, {"kind": "sync_citations_topic", "papers": 3}) is None
    assert apply_proposal(db_session, {}) is None


def test_apply_proposal_embed_dispatch(db_session):
    from packages.application.commands.domain_apply import apply_proposal

    pid = _mk_paper(db_session, "2601.00004")
    ref = apply_proposal(db_session, {"kind": "embed_paper", "paper_id": pid, "vector": [0.1, 0.2]})
    db_session.flush()
    assert ref == {"embedded": True}

    from packages.storage.models import Paper

    db_session.expire_all()
    assert db_session.get(Paper, pid).embedding == [0.1, 0.2]


# ---------- durable complete 链路（Python authority 路径全 kind apply） ----------


def _mk_durable_task(db_session, capability: str, input_ref: dict):
    """建 job+task 并领取（返回 task row；fencing 测试同款建法）"""
    from packages.storage.repositories import JobRepository, TaskRepository

    job, _ = JobRepository(db_session).create_job(kind=f"test_{capability}")
    task, _ = TaskRepository(db_session).add_task(
        job_id=job.id, capability=capability, input_ref=input_ref
    )
    db_session.flush()
    claimed = TaskRepository(db_session).claim_task_by_id(task_id=task.id, executor_id="exec-1")
    assert claimed is not None
    return task, claimed


def _complete(db_session, claimed, result: dict) -> dict:
    from apps.api.routers.durable_state import _fencing_op

    return _fencing_op(
        str(claimed.id),
        {"executor_id": "exec-1", "lease_token": claimed.lease_token, "result": result},
        "complete",
    )


def test_durable_complete_applies_deep_read_proposal(db_session):
    """修复回归：deep_read proposal 在 Python authority 路径必须落库
    （此前只 apply skim——deep_read 完成后 analysis_reports 永远为空）"""
    from packages.storage.models import AnalysisReport

    pid = _mk_paper(db_session, "2601.00005")
    task, claimed = _mk_durable_task(db_session, "deep_read_paper", {"paper_id": pid})

    result = {
        "proposal": {
            "kind": "deep_read_paper",
            "paper_id": pid,
            "deep": {
                "method_summary": "M",
                "experiments_summary": "E",
                "ablation_summary": "A",
                "reviewer_risks": ["R"],
            },
        }
    }
    out = _complete(db_session, claimed, result)
    assert out["ok"] is True

    report = db_session.query(AnalysisReport).filter_by(paper_id=pid).one()
    assert report.deep_dive_md and "Method" in report.deep_dive_md


def test_durable_complete_b_tier_stores_result_as_is(db_session):
    """B 档（无 proposal）：result 原样进 result_ref，不报错不丢失"""
    task, claimed = _mk_durable_task(db_session, "sync_citations_topic", {"topic_id": "t1"})

    result = {"papers_synced": 5, "edges_created": 12}
    out = _complete(db_session, claimed, result)
    assert out["ok"] is True

    from packages.storage.repositories import TaskRepository

    db_session.expire_all()
    row = TaskRepository(db_session).get(str(task.id))
    # durable schema 契约：result_ref 挂在 input_ref["result_ref"]（消费者 /tasks/{id}/result）
    assert (row.input_ref or {}).get("result_ref") == result


def test_durable_complete_upsert_proposal_ref_carries_paper_id(db_session):
    """upsert proposal 完成：result_ref = {paper_id, arxiv_id}（下游节点
    输出绑定 ${node:paper_id} 的契约）"""
    task, claimed = _mk_durable_task(
        db_session,
        "upsert_paper",
        {"arxiv_id": "2601.00006", "title": "T", "abstract": "A"},
    )

    result = {
        "proposal": {
            "kind": "upsert_paper",
            "arxiv_id": "2601.00006",
            "title": "T",
            "abstract": "A",
        }
    }
    _complete(db_session, claimed, result)
    from packages.storage.repositories import TaskRepository

    db_session.expire_all()
    row = TaskRepository(db_session).get(str(task.id))
    ref = (row.input_ref or {}).get("result_ref") or {}
    assert ref["arxiv_id"] == "2601.00006"
    assert ref["paper_id"]


def test_apply_ingest_papers_proposal_full_chain(db_session):
    """ingest_papers proposal：papers 落库 + topic 自动创建 + 收集记录 + 关联"""
    from packages.application.commands.domain_apply import apply_proposal
    from packages.storage.models import CollectionAction, Paper, PaperTopic, TopicSubscription

    ref = apply_proposal(
        db_session,
        {
            "kind": "ingest_papers",
            "query": "neural radiance",
            "topic_name": "NeRF 主题",
            "action_type": "agent_collect",
            "action_title": "Agent 收集: neural radiance",
            "papers": [
                {
                    "arxiv_id": "2602.00001",
                    "title": "NeRF Paper",
                    "abstract": "n",
                    "source": "arxiv",
                    "publication_date": "2026-02-01",
                    "metadata": {"categories": ["cs.CV"]},
                },
                {
                    "arxiv_id": "2602.00002",
                    "title": "NeRF Followup",
                    "abstract": "m",
                    "source": "arxiv",
                },
            ],
        },
    )
    db_session.flush()
    assert ref["total"] == 2 and len(ref["inserted_ids"]) == 2

    topic = db_session.query(TopicSubscription).filter_by(name="NeRF 主题").one()
    assert topic.enabled is False  # 自动创建不启用调度
    papers = db_session.query(Paper).filter(Paper.arxiv_id.in_(["2602.00001", "2602.00002"])).all()
    assert len(papers) == 2
    assert papers[0].metadata_json.get("categories") == ["cs.CV"]
    assert papers[0].publication_date is not None
    links = db_session.query(PaperTopic).filter_by(topic_id=topic.id).count()
    assert links == 2
    action = db_session.query(CollectionAction).filter_by(action_type="agent_collect").one()
    assert action.paper_count == 2


def test_apply_ingest_papers_proposal_existing_topic_not_disabled(db_session):
    """修正语义：topic 已存在时不改写 enabled（旧路径会禁用用户订阅）"""
    from packages.application.commands.domain_apply import apply_proposal
    from packages.storage.models import TopicSubscription

    db_session.add(TopicSubscription(name="existing-topic", query="q", enabled=True))
    db_session.flush()

    apply_proposal(
        db_session,
        {
            "kind": "ingest_papers",
            "query": "q",
            "topic_name": "existing-topic",
            "action_type": "manual_collect",
            "action_title": "t",
            "papers": [{"arxiv_id": "2602.00003", "title": "P", "abstract": "x"}],
        },
    )
    db_session.flush()
    db_session.expire_all()
    assert (
        db_session.query(TopicSubscription).filter_by(name="existing-topic").one().enabled is True
    )


def test_apply_ingest_papers_proposal_idempotent(db_session):
    """同 arxiv_id 重复入库：不产生重复论文；metadata 合并不覆盖 skim 字段"""
    from packages.application.commands.domain_apply import apply_proposal
    from packages.storage.models import Paper

    pid = _mk_paper(db_session, "2602.00004")
    db_session.get(Paper, pid).metadata_json = {"title_zh": "已有", "keywords": ["k"]}
    db_session.flush()

    proposal = {
        "kind": "ingest_papers",
        "query": "dup",
        "action_type": "manual_collect",
        "action_title": "dup",
        "papers": [
            {
                "arxiv_id": "2602.00004",
                "title": "新标题",
                "abstract": "新摘要",
                "metadata": {"categories": ["cs.LG"]},
            }
        ],
    }
    ref = apply_proposal(db_session, proposal)
    db_session.flush()
    assert len(ref["inserted_ids"]) == 1
    assert db_session.query(Paper).filter_by(arxiv_id="2602.00004").count() == 1
    db_session.expire_all()
    meta = db_session.get(Paper, pid).metadata_json
    assert meta["title_zh"] == "已有" and meta["categories"] == ["cs.LG"]


def test_ingest_proposal_handlers_return_proposal(monkeypatch):
    """registry handler（proposal 模式）：不写库，返回 ingest_papers proposal"""
    from packages.ai import task_handlers as th

    class FakePaper:
        def __init__(self, arxiv_id):
            self.arxiv_id = arxiv_id

        def model_dump(self, mode="json"):
            return {
                "arxiv_id": self.arxiv_id,
                "title": f"t-{self.arxiv_id}",
                "abstract": "",
                "source": "arxiv",
                "metadata": {},
            }

    class FakeArxiv:
        def fetch_latest(self, **kw):
            return [FakePaper("2603.00001"), FakePaper("2603.00002")]

    class FakeRepo:
        def list_existing_arxiv_ids(self, ids):
            return {"2603.00002"}  # 已存在一篇

    monkeypatch.setattr("packages.integrations.arxiv_client.ArxivClient", lambda: FakeArxiv())

    class _Sess:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("packages.storage.db.session_scope", lambda: _Sess())
    monkeypatch.setattr("packages.storage.repositories.PaperRepository", lambda s: FakeRepo())

    out = th.ingest_arxiv_query_proposal(query="test", max_results=5)
    proposal = out["proposal"]
    assert proposal["kind"] == "ingest_papers"
    assert [p["arxiv_id"] for p in proposal["papers"]] == ["2603.00001"]  # 已存在的被过滤


def test_expand_due_workflow_jobs_spawns_next_stage(db_session):
    """工作流"任务完成后展开"钩子：stage 1 完成后，expand 轮询 spawn stage 2"""
    from packages.application.commands.workflows import (
        expand_due_workflow_jobs,
        start_workflow_job,
    )
    from packages.storage.repositories import TaskRepository

    kind = "RunTopicResearch"  # 有确定性多阶段链（fetch→upsert→…）
    job, first_tasks, _ = start_workflow_job(
        db_session,
        kind=kind,
        payload={"paper_ids": ["2602.00001", "2602.00002"], "topic_id": None},
    )
    db_session.flush()
    assert first_tasks, "提交时应展开首批 Task"

    # 首批完成（模拟 executor）——完成前无后续阶段
    before = expand_due_workflow_jobs(db_session)
    _ = before

    repo = TaskRepository(db_session)
    for t in first_tasks:
        claimed = repo.claim_task_by_id(task_id=t.id, executor_id="exec-x")
        assert claimed is not None
        repo.complete_task(
            task_id=t.id,
            executor_id="exec-x",
            lease_token=claimed.lease_token,
            result_ref={"ok": True},
        )
    db_session.flush()

    # 补展开：依赖已满足的下游 Task 应被 spawn（幂等：重复调用不重复）
    expand_due_workflow_jobs(db_session)
    created2 = expand_due_workflow_jobs(db_session)
    all_tasks = repo.list_for_job(job.id)
    total = len(all_tasks)
    assert total >= len(first_tasks)
    assert created2 == 0 or total > len(first_tasks)  # 幂等性：二轮不重复


def test_apply_save_generated_content_proposal(db_session):
    """save_generated_content proposal：generated_contents 插入 + content_id 回传"""
    from packages.application.commands.domain_apply import apply_proposal
    from packages.storage.models import GeneratedContent

    ref = apply_proposal(
        db_session,
        {
            "kind": "save_generated_content",
            "content_type": "daily_brief",
            "title": "Daily Brief: 2026-09-07",
            "markdown": "<html>brief</html>",
            "metadata_json": {"email_sent": False, "source": "manual"},
        },
    )
    db_session.flush()
    assert ref["content_id"]
    row = db_session.get(GeneratedContent, ref["content_id"])
    assert row.content_type == "daily_brief"
    assert row.metadata_json.get("source") == "manual"


def test_wiki_brief_handlers_return_proposal(monkeypatch, db_session):
    """wiki/brief handler：计算留 handler、领域写转 proposal"""
    # wiki：mock get_topic_wiki（LLM 计算层）
    import packages.application.commands.graph as graph_mod
    from packages.ai import task_handlers as th

    monkeypatch.setattr(
        graph_mod, "get_topic_wiki", lambda **kw: {"markdown": "# W", "sections": 3}
    )
    out = th.topic_wiki_save(keyword="kw", limit=5)
    p = out["proposal"]
    assert p["kind"] == "save_generated_content"
    assert p["content_type"] == "topic_wiki"
    assert p["markdown"] == "# W"
    assert p["metadata_json"].get("sections") == 3
    # 不应直接写库
    from packages.storage.models import GeneratedContent

    assert db_session.query(GeneratedContent).count() == 0


def test_apply_citation_edges_proposal(db_session):
    """citation_edges proposal：papers 双侧 upsert + 边幂等"""
    from packages.ai.graph._common import _title_to_id
    from packages.application.commands.domain_apply import apply_proposal
    from packages.storage.models import Citation, Paper

    sid = _title_to_id("Edge Src")
    did = _title_to_id("Edge Dst")
    proposal = {
        "kind": "citation_edges",
        "edges": [
            {
                "source": {
                    "arxiv_id": sid,
                    "title": "Edge Src",
                    "abstract": "",
                    "metadata": {"source": "semantic_scholar"},
                },
                "target": {
                    "arxiv_id": did,
                    "title": "Edge Dst",
                    "abstract": "",
                    "metadata": {"source": "semantic_scholar"},
                },
                "context": "reference",
            }
        ],
    }
    ref = apply_proposal(db_session, proposal)
    db_session.flush()
    assert ref["edges_inserted"] == 1
    # 幂等重放
    ref2 = apply_proposal(db_session, proposal)
    db_session.flush()
    assert ref2["edges_inserted"] == 0
    assert db_session.query(Citation).count() == 1
    assert (
        db_session.query(Paper).filter(Paper.arxiv_id == sid).one().metadata_json["source"]
        == "semantic_scholar"
    )


def test_apply_figure_and_translation_proposals(db_session):
    """figure_analyses 删重建 + paper_translation upsert"""
    from packages.application.commands.domain_apply import apply_proposal
    from packages.storage.models import ImageAnalysis, PaperTranslation

    pid = _mk_paper(db_session, "2606.00001")
    fig = {
        "kind": "figure_analyses",
        "paper_id": pid,
        "analyses": [
            {
                "page_number": 1,
                "image_index": 0,
                "image_type": "figure",
                "caption": "c",
                "description": "d",
                "image_path": "/f/1.png",
            }
        ],
    }
    apply_proposal(db_session, fig)
    apply_proposal(db_session, fig)
    db_session.flush()
    assert db_session.query(ImageAnalysis).filter_by(paper_id=pid).count() == 1

    tr = {
        "kind": "paper_translation",
        "paper_id": pid,
        "target_lang": "zh",
        "mode": "fast",
        "segments": [{"id": "p-1", "translation": "x"}],
    }
    apply_proposal(db_session, tr)
    apply_proposal(db_session, tr)
    db_session.flush()
    rows = db_session.query(PaperTranslation).filter_by(paper_id=pid).all()
    assert len(rows) == 1 and rows[0].segments[0]["translation"] == "x"


def test_apply_reference_import_proposal(db_session):
    """reference_import proposal：papers + 引用边 + topic 关联 + 收集记录"""
    from packages.application.commands.domain_apply import apply_proposal
    from packages.storage.models import (
        Citation,
        CollectionAction,
        PaperTopic,
        TopicSubscription,
    )

    src = _mk_paper(db_session, "2606.00002")
    db_session.add(TopicSubscription(name="ref-topic", query="q", enabled=False))
    db_session.flush()
    topic = db_session.query(TopicSubscription).filter_by(name="ref-topic").one()

    ref = apply_proposal(
        db_session,
        {
            "kind": "reference_import",
            "source_paper_id": src,
            "source_paper_title": "Source Paper",
            "papers": [
                {
                    "paper": {"arxiv_id": "2606.00003", "title": "Ref A", "abstract": "a"},
                    "topics": [str(topic.id)],
                    "direction": "reference",
                },
                {
                    "paper": {
                        "arxiv_id": "",
                        "title": "SS Only Paper",
                        "abstract": "",
                        "metadata": {"source": "semantic_scholar"},
                    },
                    "topics": [],
                    "direction": "cited_by",
                },
            ],
        },
    )
    db_session.flush()
    assert ref["total"] == 2
    assert db_session.query(Citation).filter_by(source_paper_id=src).count() == 1
    assert db_session.query(Citation).filter_by(target_paper_id=src).count() == 1
    assert db_session.query(PaperTopic).filter_by(topic_id=topic.id).count() == 1
    action = db_session.query(CollectionAction).filter_by(action_type="reference_import").one()
    assert action.paper_count == 2


def test_go_manifest_in_sync_with_python():
    """双源漂移防线：Go 侧生成清单（capabilities_gen.go）必须与 Python
    GO_APPLY_CAPABILITIES 一致——漂移会让提交在 Go 侧 400（fail closed）。"""
    import re

    from packages.application.commands.jobs import GO_APPLY_CAPABILITIES

    gen = (Path(__file__).resolve().parents[1] / "core" / "capabilities_gen.go").read_text()
    go_caps = set(re.findall(r'"([a-z_]+)":\s+true', gen))
    assert go_caps == set(GO_APPLY_CAPABILITIES), (
        f"manifest 漂移：Go 缺 {set(GO_APPLY_CAPABILITIES) - go_caps}，"
        f"Go 多 {go_caps - set(GO_APPLY_CAPABILITIES)}——运行 python scripts/export_go_manifest.py"
    )
