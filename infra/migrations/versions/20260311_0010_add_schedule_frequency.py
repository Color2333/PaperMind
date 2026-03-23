"""add schedule_frequency to topic_subscriptions

Revision ID: 20260311_0010_add_schedule_frequency
Revises: 140e104869f9
Create Date: 2026-03-11

@author Color2333
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260311_0010_add_schedule_frequency"
down_revision: Union[str, None] = "140e104869f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "topic_subscriptions",
        sa.Column("schedule_frequency", sa.String(32), nullable=False, server_default="daily"),
    )


def downgrade() -> None:
    op.drop_column("topic_subscriptions", "schedule_frequency")
