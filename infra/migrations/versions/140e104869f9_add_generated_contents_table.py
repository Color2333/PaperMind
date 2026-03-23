"""add_generated_contents_table

Revision ID: 140e104869f9
Revises: 20260308_0009_add_date_filter_settings
Create Date: 2026-03-10

@author Color2333
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "140e104869f9"
down_revision = "20260308_0009_add_date_filter_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generated_contents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("keyword", sa.String(256), nullable=True),
        sa.Column("paper_id", sa.String(36), nullable=True),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="SET NULL"),
    )

    op.create_index("ix_generated_contents_created_at", "generated_contents", ["created_at"])
    op.create_index("ix_generated_contents_content_type", "generated_contents", ["content_type"])
    op.create_index("ix_generated_contents_paper_id", "generated_contents", ["paper_id"])


def downgrade() -> None:
    op.drop_index("ix_generated_contents_paper_id", "generated_contents")
    op.drop_index("ix_generated_contents_content_type", "generated_contents")
    op.drop_index("ix_generated_contents_created_at", "generated_contents")
    op.drop_table("generated_contents")
