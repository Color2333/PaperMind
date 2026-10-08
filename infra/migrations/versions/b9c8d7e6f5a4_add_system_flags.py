"""add system_flags（P0：跨进程 pause 持久化）

Revision ID: b9c8d7e6f5a4
Revises: a3b4c5d6e7f8
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9c8d7e6f5a4"
down_revision: str | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_flags",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("system_flags")
