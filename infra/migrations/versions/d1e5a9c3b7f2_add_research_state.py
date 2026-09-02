"""add research state tables

设计①数据契约（docs/plans/2026-09-02-design-1-research-state-data-contract.md）：
research_questions / research_runs / claims / source_versions / evidence /
claim_relations / research_events。主键 UUIDv7 hex；枚举列按成员 name 落库
（EventType 的 value 是对外事件词汇表，name 是 DB 稳定标识）。

Revision ID: d1e5a9c3b7f2
Revises: b8c9d0e1f2a3
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa

from packages.domain.enums import (
    ClaimCertainty,
    ClaimOrigin,
    ClaimStatus,
    EventAggregate,
    EventType,
    EvidenceKind,
    EvidenceStance,
    QuestionStatus,
    RelationOrigin,
    RelationPredicate,
    ResearchRunStatus,
    RunTrigger,
    SourceDetectedBy,
)

# revision identifiers, used by Alembic.
revision = 'd1e5a9c3b7f2'
down_revision = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def _enum(cls, name: str) -> sa.Enum:
    # SQLAlchemy Enum 默认存成员 name，与 ORM 模型行为一致
    return sa.Enum(*[m.name for m in cls], name=name)


def upgrade() -> None:
    op.create_table(
        'research_questions',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('title', sa.String(512), nullable=False),
        sa.Column('question', sa.Text, nullable=False),
        sa.Column('status', _enum(QuestionStatus, 'question_status'), nullable=False),
        sa.Column('watch_terms', sa.JSON, nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=False),
    )
    op.create_index('ix_research_questions_status', 'research_questions', ['status'])

    op.create_table(
        'research_runs',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('kind', sa.String(64), nullable=False),
        sa.Column(
            'research_question_id',
            sa.String(32),
            sa.ForeignKey('research_questions.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('trigger', _enum(RunTrigger, 'run_trigger'), nullable=False),
        sa.Column('paper_ids', sa.JSON, nullable=False),
        sa.Column('model_policy', sa.JSON, nullable=False),
        sa.Column('status', _enum(ResearchRunStatus, 'research_run_status'), nullable=False),
        sa.Column('started_at', sa.DateTime, nullable=False),
        sa.Column('finished_at', sa.DateTime, nullable=True),
        sa.Column('cost_refs', sa.JSON, nullable=False),
        sa.Column('artifact_refs', sa.JSON, nullable=False),
        sa.Column('job_ref', sa.String(128), nullable=True),
        sa.Column('attempt_refs', sa.JSON, nullable=True),
        sa.Column('notes', sa.Text, nullable=True),
    )
    op.create_index('ix_research_runs_kind', 'research_runs', ['kind'])

    op.create_table(
        'claims',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column(
            'research_question_id',
            sa.String(32),
            sa.ForeignKey('research_questions.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('statement', sa.Text, nullable=False),
        sa.Column('statement_zh', sa.Text, nullable=True),
        sa.Column('origin', _enum(ClaimOrigin, 'claim_origin'), nullable=False),
        sa.Column('status', _enum(ClaimStatus, 'claim_status'), nullable=False),
        sa.Column('certainty', _enum(ClaimCertainty, 'claim_certainty'), nullable=False),
        sa.Column(
            'superseded_by_id',
            sa.String(32),
            sa.ForeignKey('claims.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'run_id',
            sa.String(32),
            sa.ForeignKey('research_runs.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('user_note', sa.Text, nullable=True),
        sa.Column('confirmed_at', sa.DateTime, nullable=True),
        sa.Column('confirmed_by', sa.String(128), nullable=True),
        sa.Column('invalidated_reason', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=False),
    )
    op.create_index('ix_claims_question_status', 'claims', ['research_question_id', 'status'])
    op.create_index('ix_claims_status', 'claims', ['status'])

    op.create_table(
        'source_versions',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column(
            'paper_id',
            sa.String(36),
            sa.ForeignKey('papers.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('version_label', sa.Integer, nullable=False),
        sa.Column('external_version', sa.String(32), nullable=True),
        sa.Column('doi', sa.String(128), nullable=True),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('file_path', sa.String(1024), nullable=True),
        sa.Column('origin_url', sa.String(1024), nullable=True),
        sa.Column('detected_by', _enum(SourceDetectedBy, 'source_detected_by'), nullable=False),
        sa.Column('fetched_at', sa.DateTime, nullable=False),
        sa.Column('is_current', sa.Boolean, nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.UniqueConstraint('paper_id', 'version_label', name='uq_source_version'),
    )
    op.create_index(
        'ix_source_versions_paper_current', 'source_versions', ['paper_id', 'is_current']
    )

    op.create_table(
        'evidence',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column(
            'claim_id',
            sa.String(32),
            sa.ForeignKey('claims.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'source_version_id',
            sa.String(32),
            sa.ForeignKey('source_versions.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('kind', _enum(EvidenceKind, 'evidence_kind'), nullable=False),
        sa.Column('stance', _enum(EvidenceStance, 'evidence_stance'), nullable=False),
        sa.Column('locator', sa.JSON, nullable=False),
        sa.Column('quote', sa.Text, nullable=True),
        sa.Column('experiment_conditions', sa.JSON, nullable=True),
        sa.Column('extracted_by', _enum(ClaimOrigin, 'evidence_extracted_by'), nullable=False),
        sa.Column(
            'run_id',
            sa.String(32),
            sa.ForeignKey('research_runs.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'image_analysis_id',
            sa.String(36),
            sa.ForeignKey('image_analyses.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.UniqueConstraint('fingerprint', name='uq_evidence_fingerprint'),
    )
    op.create_index('ix_evidence_claim_id', 'evidence', ['claim_id'])
    op.create_index('ix_evidence_source_version', 'evidence', ['source_version_id'])

    op.create_table(
        'claim_relations',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column(
            'subject_claim_id',
            sa.String(32),
            sa.ForeignKey('claims.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'object_claim_id',
            sa.String(32),
            sa.ForeignKey('claims.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('predicate', _enum(RelationPredicate, 'claim_relation_predicate'), nullable=False),
        sa.Column('origin', _enum(RelationOrigin, 'claim_relation_origin'), nullable=False),
        sa.Column(
            'run_id',
            sa.String(32),
            sa.ForeignKey('research_runs.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('note', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.UniqueConstraint(
            'subject_claim_id', 'object_claim_id', 'predicate', name='uq_claim_relation'
        ),
    )
    op.create_index('ix_claim_relations_object', 'claim_relations', ['object_claim_id'])

    op.create_table(
        'research_events',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('type', _enum(EventType, 'research_event_type'), nullable=False),
        sa.Column('aggregate_type', _enum(EventAggregate, 'research_event_aggregate'), nullable=False),
        sa.Column('aggregate_id', sa.String(32), nullable=False),
        sa.Column('actor', sa.String(128), nullable=False),
        sa.Column('run_id', sa.String(32), nullable=True),
        sa.Column('job_ref', sa.String(128), nullable=True),
        sa.Column('attempt_ref', sa.String(128), nullable=True),
        sa.Column('payload', sa.JSON, nullable=False),
        sa.Column('occurred_at', sa.DateTime, nullable=False),
        sa.Column('processed_at', sa.DateTime, nullable=True),
    )
    op.create_index(
        'ix_research_events_aggregate',
        'research_events',
        ['aggregate_type', 'aggregate_id', 'occurred_at'],
    )
    op.create_index('ix_research_events_type_time', 'research_events', ['type', 'occurred_at'])
    op.create_index('ix_research_events_occurred_at', 'research_events', ['occurred_at'])


def downgrade() -> None:
    op.drop_table('research_events')
    op.drop_table('claim_relations')
    op.drop_table('evidence')
    op.drop_table('source_versions')
    op.drop_table('claims')
    op.drop_table('research_runs')
    op.drop_table('research_questions')
