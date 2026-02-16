"""add topic quota and retry controls

Revision ID: 20260216_0005
Revises: 20260216_0004
Create Date: 2026-02-16 03:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260216_0005"
down_revision = "20260216_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "topic_subscriptions",
        sa.Column("max_results_per_run", sa.Integer(), nullable=False, server_default="20"),
    )
    op.add_column(
        "topic_subscriptions",
        sa.Column("retry_limit", sa.Integer(), nullable=False, server_default="2"),
    )


def downgrade() -> None:
    op.drop_column("topic_subscriptions", "retry_limit")
    op.drop_column("topic_subscriptions", "max_results_per_run")
