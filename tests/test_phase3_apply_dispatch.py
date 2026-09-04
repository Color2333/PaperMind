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
