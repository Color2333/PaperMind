"""add tags table

Revision ID: 20260415_0001
Revises: b1d72ad8a6ed
Create Date: 2026-04-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260415_0001"
down_revision = "b1d72ad8a6ed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False, unique=True),
        sa.Column("color", sa.String(length=32), nullable=False, server_default="#3b82f6"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_tags_name", "tags", ["name"], unique=True)

    op.create_table(
        "paper_tags",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("paper_id", sa.String(length=36), nullable=False),
        sa.Column("tag_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("paper_id", "tag_id", name="uq_paper_tag"),
    )
    op.create_index("ix_paper_tags_paper_id", "paper_tags", ["paper_id"], unique=False)
    op.create_index("ix_paper_tags_tag_id", "paper_tags", ["tag_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_paper_tags_tag_id", table_name="paper_tags")
    op.drop_index("ix_paper_tags_paper_id", table_name="paper_tags")
    op.drop_table("paper_tags")
    op.drop_index("ix_tags_name", table_name="tags")
    op.drop_table("tags")
