"""initial schema

Revision ID: 20260216_0001
Revises:
Create Date: 2026-02-16 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260216_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    read_status = sa.Enum("Unread", "Skimmed", "DeepRead", name="read_status")
    pipeline_status = sa.Enum("pending", "running", "succeeded", "failed", name="pipeline_status")
    read_status.create(op.get_bind(), checkfirst=True)
    pipeline_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "papers",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("arxiv_id", sa.String(length=64), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=False),
        sa.Column("pdf_path", sa.String(length=1024), nullable=True),
        sa.Column("publication_date", sa.Date(), nullable=True),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("read_status", read_status, nullable=False, server_default="Unread"),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("arxiv_id"),
    )
    op.create_index("ix_papers_arxiv_id", "papers", ["arxiv_id"], unique=True)

    op.create_table(
        "analysis_reports",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("paper_id", sa.String(length=36), nullable=False),
        sa.Column("summary_md", sa.Text(), nullable=True),
        sa.Column("deep_dive_md", sa.Text(), nullable=True),
        sa.Column("key_insights", sa.JSON(), nullable=False),
        sa.Column("skim_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_analysis_reports_paper_id", "analysis_reports", ["paper_id"], unique=False)

    op.create_table(
        "citations",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("source_paper_id", sa.String(length=36), nullable=False),
        sa.Column("target_paper_id", sa.String(length=36), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["source_paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_paper_id", "target_paper_id", name="uq_citation_edge"),
    )
    op.create_index("ix_citations_source_paper_id", "citations", ["source_paper_id"], unique=False)
    op.create_index("ix_citations_target_paper_id", "citations", ["target_paper_id"], unique=False)

    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("paper_id", sa.String(length=36), nullable=True),
        sa.Column("pipeline_name", sa.String(length=100), nullable=False),
        sa.Column("status", pipeline_status, nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_pipeline_runs_paper_id", "pipeline_runs", ["paper_id"], unique=False)
    op.create_index("ix_pipeline_runs_pipeline_name", "pipeline_runs", ["pipeline_name"], unique=False)

    op.create_table(
        "prompt_traces",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("paper_id", sa.String(length=36), nullable=True),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_digest", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_prompt_traces_paper_id", "prompt_traces", ["paper_id"], unique=False)
    op.create_index("ix_prompt_traces_stage", "prompt_traces", ["stage"], unique=False)

    op.create_table(
        "source_checkpoints",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("last_fetch_at", sa.DateTime(), nullable=True),
        sa.Column("last_published_date", sa.Date(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("source"),
    )


def downgrade() -> None:
    op.drop_table("source_checkpoints")

    op.drop_index("ix_prompt_traces_stage", table_name="prompt_traces")
    op.drop_index("ix_prompt_traces_paper_id", table_name="prompt_traces")
    op.drop_table("prompt_traces")

    op.drop_index("ix_pipeline_runs_pipeline_name", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_paper_id", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")

    op.drop_index("ix_citations_target_paper_id", table_name="citations")
    op.drop_index("ix_citations_source_paper_id", table_name="citations")
    op.drop_table("citations")

    op.drop_index("ix_analysis_reports_paper_id", table_name="analysis_reports")
    op.drop_table("analysis_reports")

    op.drop_index("ix_papers_arxiv_id", table_name="papers")
    op.drop_table("papers")

    sa.Enum(name="pipeline_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="read_status").drop(op.get_bind(), checkfirst=True)
