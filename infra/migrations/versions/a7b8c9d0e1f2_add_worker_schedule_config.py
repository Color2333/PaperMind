"""add worker_schedule_configs table

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-20 12:00:00.000000

目的：把 worker 调度 cron 从硬编码/env 提取到 DB 单例表，支持网页端实时控制。
单例表（单行），lazy 创建默认行。worker 启动读一次，运行时轮询 updated_at 热重载。
last_applied_at 由 worker 写回，供前端显示"已生效"状态。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # PG 支持 CREATE TABLE IF NOT EXISTS；SQLite 用 try/except 兜底
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS worker_schedule_configs (
                id VARCHAR(36) NOT NULL,
                topic_dispatch_cron VARCHAR(64) NOT NULL,
                cs_feed_dispatch_cron VARCHAR(64) NOT NULL,
                weekly_graph_cron VARCHAR(64) NOT NULL,
                idle_processor_enabled BOOLEAN NOT NULL,
                last_applied_at DATETIME,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (id)
            )
            """
        )
    else:
        try:
            op.create_table(
                "worker_schedule_configs",
                sa.Column("id", sa.String(length=36), nullable=False),
                sa.Column("topic_dispatch_cron", sa.String(length=64), nullable=False),
                sa.Column("cs_feed_dispatch_cron", sa.String(length=64), nullable=False),
                sa.Column("weekly_graph_cron", sa.String(length=64), nullable=False),
                sa.Column("idle_processor_enabled", sa.Boolean(), nullable=False),
                sa.Column("last_applied_at", sa.DateTime(), nullable=True),
                sa.Column("created_at", sa.DateTime(), nullable=False),
                sa.Column("updated_at", sa.DateTime(), nullable=False),
                sa.PrimaryKeyConstraint("id"),
            )
        except Exception:
            pass


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TABLE IF EXISTS worker_schedule_configs")
    else:
        try:
            op.drop_table("worker_schedule_configs")
        except Exception:
            pass
