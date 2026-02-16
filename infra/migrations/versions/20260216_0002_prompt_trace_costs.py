"""add prompt trace cost columns

Revision ID: 20260216_0002
Revises: 20260216_0001
Create Date: 2026-02-16 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260216_0002"
down_revision = "20260216_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("prompt_traces", sa.Column("input_cost_usd", sa.Float(), nullable=True))
    op.add_column("prompt_traces", sa.Column("output_cost_usd", sa.Float(), nullable=True))
    op.add_column("prompt_traces", sa.Column("total_cost_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("prompt_traces", "total_cost_usd")
    op.drop_column("prompt_traces", "output_cost_usd")
    op.drop_column("prompt_traces", "input_cost_usd")
