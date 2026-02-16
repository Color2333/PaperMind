"""add pipeline decision note

Revision ID: 20260216_0003
Revises: 20260216_0002
Create Date: 2026-02-16 01:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260216_0003"
down_revision = "20260216_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pipeline_runs", sa.Column("decision_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("pipeline_runs", "decision_note")
