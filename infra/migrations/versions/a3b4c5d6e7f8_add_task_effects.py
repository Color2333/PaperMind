"""add task_effects (副作用账本, C9)

Revision ID: a3b4c5d6e7f8
Revises: f3a4b5c6d7e8
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from alembic import op

from packages.domain.enums import EffectKind

revision = "a3b4c5d6e7f8"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_effects",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(32),
            sa.ForeignKey("tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("effect_key", sa.String(256), nullable=False),
        sa.Column(
            "kind", sa.Enum(*[m.name for m in EffectKind], name="effect_kind"), nullable=False
        ),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("committed_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("effect_key", name="uq_task_effects_key"),
    )
    op.create_index("ix_task_effects_task", "task_effects", ["task_id"])


def downgrade() -> None:
    op.drop_table("task_effects")
