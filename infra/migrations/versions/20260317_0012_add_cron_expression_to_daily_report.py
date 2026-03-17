"""add cron_expression to daily_report_configs

Revision ID: 20260317_0012
Revises: 5ae0d73c1013
Create Date: 2026-03-17

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260317_0012"
down_revision = "5ae0d73c1013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加 cron_expression 字段
    op.add_column(
        "daily_report_configs",
        sa.Column("cron_expression", sa.String(64), nullable=False, server_default="0 4 * * *"),
    )

    # 标记 report_time_utc 为废弃（保留字段兼容性）
    # 不删除，保持向后兼容


def downgrade() -> None:
    op.drop_column("daily_report_configs", "cron_expression")
