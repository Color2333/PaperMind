"""add ieee api quota tracking

Revision ID: 20260303_0011_ieee_quota
Revises: 20260303_0010_topic_channels
Create Date: 2026-03-03

注意：此迁移脚本用于完整版阶段，创建 IEEE API 配额追踪表
- 新建 ieee_api_quotas 表
- 支持按主题、按日期追踪配额使用

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260303_0011_ieee_quota"
down_revision: Union[str, None] = "20260303_0010_topic_channels"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 创建 ieee_api_quotas 表
    op.create_table(
        "ieee_api_quotas",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("topic_id", sa.String(36), nullable=True),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("api_calls_used", sa.Integer, nullable=False, default=0),
        sa.Column("api_calls_limit", sa.Integer, nullable=False, default=50),
        sa.Column("last_reset_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["topic_id"], ["topic_subscriptions.id"], ondelete="SET NULL"),
    )

    # 创建索引
    with op.batch_alter_table("ieee_api_quotas", schema=None) as batch_op:
        batch_op.create_index("ix_ieee_quotas_topic_id", ["topic_id"])
        batch_op.create_index("ix_ieee_quotas_date", ["date"])
        batch_op.create_unique_constraint("uq_ieee_quota_daily", ["topic_id", "date"])


def downgrade() -> None:
    # 删除表
    op.drop_table("ieee_api_quotas")
