"""Research Object 基础导出（D5，设计① §10 / 设计文档 §4.4）

把一个 ResearchQuestion 导出为自包含、可携带的研究对象：
- JSON：question + claims + evidence + relations + source_versions + provenance；
- Markdown：面向人阅读的同一内容渲染；
- content_hash：对 research_object 载荷的 sha256（canonical JSON、不含生成时间），
  同一数据两次导出 hash 一致——这是"可验证的文件校验值"的最小落地。

长期与 RO-Crate 兼容（ro_type 预留），首版不引入完整 RO-Crate 描述文件。
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, or_, select

from packages.application.queries import research_state
from packages.domain.enums import EventAggregate, EventType
from packages.storage.models import (
    ClaimRelation,
    Evidence,
    Paper,
    ResearchEvent,
    ResearchRun,
    SourceVersion,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

RO_TYPE = "papermind-research-object"
RO_VERSION = 1


def _canonical(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def export_research_object(session: Session, question_id: str) -> dict:
    """导出问题为 Research Object（content_hash 覆盖除自身/生成时间外的全部内容）"""
    question_view = research_state.get_research_question(session, question_id)
    claims_view = research_state.list_claims(session, question_id, limit=10000)
    claim_ids = [c["id"] for c in claims_view["items"]]

    evidence_rows = []
    if claim_ids:
        evidence_rows = list(
            session.execute(
                select(Evidence, SourceVersion, Paper)
                .join(SourceVersion, Evidence.source_version_id == SourceVersion.id)
                .join(Paper, SourceVersion.paper_id == Paper.id)
                .where(Evidence.claim_id.in_(claim_ids))
                .order_by(Evidence.id)
            ).all()
        )
    claim_ids_filter = claim_ids or ["-"]
    relation_rows = list(
        session.execute(
            select(ClaimRelation)
            .where(
                or_(
                    ClaimRelation.subject_claim_id.in_(claim_ids_filter),
                    ClaimRelation.object_claim_id.in_(claim_ids_filter),
                )
            )
            .order_by(ClaimRelation.id)
        ).scalars()
    )
    version_ids = sorted({str(sv.id) for _, sv, _ in evidence_rows})
    source_versions = []
    if version_ids:
        for version, paper in session.execute(
            select(SourceVersion, Paper)
            .join(Paper, SourceVersion.paper_id == Paper.id)
            .where(SourceVersion.id.in_(version_ids))
            .order_by(SourceVersion.paper_id, SourceVersion.version_label)
        ).all():
            source_versions.append(
                {
                    "id": version.id,
                    "paper": {"id": paper.id, "title": paper.title, "arxiv_id": paper.arxiv_id},
                    "version_label": version.version_label,
                    "external_version": version.external_version,
                    "content_hash": version.content_hash,
                    "fetched_at": _iso(version.fetched_at),
                    "is_current": version.is_current,
                }
            )

    run_ids = sorted({rid for rid in (c.get("run_id") for c in claims_view["items"]) if rid})
    runs = []
    if run_ids:
        for run in (
            session.execute(select(ResearchRun).where(ResearchRun.id.in_(run_ids))).scalars().all()
        ):
            runs.append(
                {
                    "id": run.id,
                    "kind": run.kind,
                    "trigger": str(run.trigger),
                    "status": str(run.status),
                    "model_policy": run.model_policy or {},
                    "cost_refs": run.cost_refs or [],
                    "started_at": _iso(run.started_at),
                    "finished_at": _iso(run.finished_at),
                }
            )

    events_count = 0
    if claim_ids:
        events_count = int(
            session.execute(
                select(func.count())
                .select_from(ResearchEvent)
                .where(
                    ResearchEvent.aggregate_type == EventAggregate.claim,
                    ResearchEvent.aggregate_id.in_(claim_ids),
                )
            ).scalar()
            or 0
        )

    research_object = {
        "ro_type": RO_TYPE,
        "ro_version": RO_VERSION,
        "question": question_view,
        "claims": claims_view["items"],
        "evidence": [
            {
                "id": evidence.id,
                "claim_id": evidence.claim_id,
                "kind": str(evidence.kind),
                "stance": str(evidence.stance),
                "locator": evidence.locator or {},
                "quote": evidence.quote,
                "experiment_conditions": evidence.experiment_conditions,
                "extracted_by": str(evidence.extracted_by),
                "source_version_id": evidence.source_version_id,
            }
            for evidence, _, _ in evidence_rows
        ],
        "relations": [
            {
                "id": rel.id,
                "subject_claim_id": rel.subject_claim_id,
                "object_claim_id": rel.object_claim_id,
                "predicate": str(rel.predicate),
                "origin": str(rel.origin),
            }
            for rel in relation_rows
        ],
        "source_versions": source_versions,
        "provenance": {
            "research_runs": runs,
            "claim_events_count": events_count,
            "event_types_covered": sorted(
                {str(e.value) for e in EventType if e in _TRACKED_EVENT_TYPES}
            ),
        },
    }
    content_hash = (
        "sha256:" + hashlib.sha256(_canonical(research_object).encode("utf-8")).hexdigest()
    )
    return {
        "content_hash": content_hash,
        "generated_at": datetime.now(UTC).isoformat(),
        "research_object": research_object,
    }


_TRACKED_EVENT_TYPES = {
    EventType.claim_proposed,
    EventType.claim_confirmed,
    EventType.claim_revised,
    EventType.claim_invalidated,
    EventType.claim_relation_recorded,
    EventType.evidence_extracted,
    EventType.retraction_detected,
}


def render_markdown(ro: dict) -> str:
    """同一 Research Object 的人读渲染（renderer 不改业务语义）"""
    obj = ro["research_object"]
    question = obj["question"]
    claim_by_id = {c["id"]: c for c in obj["claims"]}
    lines: list[str] = []
    lines.append(f"# {question['title']}")
    lines.append("")
    lines.append(f"> {question['question']}")
    lines.append("")
    lines.append(f"- 内容校验值：`{ro['content_hash']}`")
    lines.append(f"- 导出时间：{ro['generated_at']}")
    lines.append(
        f"- Claim 统计：{question['claim_counts']['by_status']} / certainty："
        f"{question['claim_counts']['by_certainty']}"
    )
    lines.append("")
    lines.append(f"## Claims（{len(obj['claims'])} 条）")
    lines.append("")
    for claim in obj["claims"]:
        lines.append(f"### [{claim['status']}/{claim['certainty']}] {claim['statement']}")
        lines.append("")
        lines.append(f"- 判断来源：`{claim['origin']}`；创建于 {claim.get('created_at')}")
        if claim.get("statement_zh"):
            lines.append(f"- 中文转述：{claim['statement_zh']}")
        claim_evidence = [e for e in obj["evidence"] if e["claim_id"] == claim["id"]]
        if claim_evidence:
            lines.append("- 证据：")
            for e in claim_evidence:
                version = next(
                    (v for v in obj["source_versions"] if v["id"] == e["source_version_id"]),
                    {},
                )
                paper = (version.get("paper") or {}).get("title", "?")
                lines.append(
                    f"  - [{e['stance']}/{e['kind']}] 「{e.get('quote') or ''}」"
                    f"——《{paper}》 v{version.get('version_label', '?')}"
                    f" {e.get('locator') or ''}"
                )
        else:
            lines.append("- 证据：无（draft，等待补充坐标）")
        relations = [
            r
            for r in obj["relations"]
            if r["subject_claim_id"] == claim["id"] or r["object_claim_id"] == claim["id"]
        ]
        for r in relations:
            other_id = (
                r["object_claim_id"]
                if r["subject_claim_id"] == claim["id"]
                else r["subject_claim_id"]
            )
            other = claim_by_id.get(other_id, {})
            arrow = "→" if r["subject_claim_id"] == claim["id"] else "←"
            lines.append(
                f"- 关系：{arrow} `{r['predicate']}` {other.get('statement', other_id)[:60]}"
            )
        lines.append("")

    lines.append("## Provenance")
    lines.append("")
    for run in obj["provenance"]["research_runs"]:
        lines.append(
            f"- ResearchRun `{run['id']}` kind={run['kind']} status={run['status']}"
            f" model={run.get('model_policy', {}).get('model', '?')}"
        )
    lines.append(f"- Claim 事件总数：{obj['provenance']['claim_events_count']}")
    lines.append("")
    return "\n".join(lines)
