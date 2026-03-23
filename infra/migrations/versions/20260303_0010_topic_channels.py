"""add topic multi-channel support

Revision ID: 20260303_0010_topic_channels
Revises: 20260303_0009_ieee_mvp
Create Date: 2026-03-03

注意：此迁移脚本用于完整版阶段，为 TopicSubscription 添加多渠道支持
- 新增 sources 字段（JSON，默认 ["arxiv"]）
- 新增 ieee_daily_quota 字段
- 新增 ieee_api_key_override 字段

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260303_0010_topic_channels"
down_revision: Union[str, None] = "20260303_0009_ieee_mvp"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 添加新字段
    with op.batch_alter_table("topic_subscriptions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("sources", sa.JSON, nullable=False, server_default='["arxiv"]')
        )
        batch_op.add_column(
            sa.Column("ieee_daily_quota", sa.Integer, nullable=False, server_default="10")
        )
        batch_op.add_column(sa.Column("ieee_api_key_override", sa.String(512), nullable=True))


def downgrade() -> None:
    # 删除新字段
    with op.batch_alter_table("topic_subscriptions", schema=None) as batch_op:
        batch_op.drop_column("ieee_api_key_override")
        batch_op.drop_column("ieee_daily_quota")
        batch_op.drop_column("sources")
