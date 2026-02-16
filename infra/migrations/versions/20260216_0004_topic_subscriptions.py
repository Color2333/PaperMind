"""add topic subscriptions and paper topic mapping

Revision ID: 20260216_0004
Revises: 20260216_0003
Create Date: 2026-02-16 02:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260216_0004"
down_revision = "20260216_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topic_subscriptions",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("query", sa.String(length=1024), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "paper_topics",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("paper_id", sa.String(length=36), nullable=False),
        sa.Column("topic_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["topic_id"], ["topic_subscriptions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("paper_id", "topic_id", name="uq_paper_topic"),
    )
    op.create_index("ix_paper_topics_paper_id", "paper_topics", ["paper_id"], unique=False)
    op.create_index("ix_paper_topics_topic_id", "paper_topics", ["topic_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_paper_topics_topic_id", table_name="paper_topics")
    op.drop_index("ix_paper_topics_paper_id", table_name="paper_topics")
    op.drop_table("paper_topics")
    op.drop_table("topic_subscriptions")
