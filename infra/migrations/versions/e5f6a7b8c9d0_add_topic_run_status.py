"""add topic_subscriptions.last_run_at / last_error for fetch failure tracking

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-17 16:00:00.000000

目的：给 topic_subscriptions 加 last_run_at / last_error，记录主题抓取的最近运行
时间与错误信息。此前抓取失败静默无痕，无法定位失败主题、无法补抓。
PG 用 ADD COLUMN IF NOT EXISTS，SQLite 用 try/except 兜底，保持幂等（对齐 c3d4e5f6a7b8 写法）。
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # PG 支持 ADD COLUMN IF NOT EXISTS；SQLite 不支持，用 try/except 兜底
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE topic_subscriptions ADD COLUMN IF NOT EXISTS last_run_at TIMESTAMP NULL"
        )
        op.execute(
            "ALTER TABLE topic_subscriptions ADD COLUMN IF NOT EXISTS last_error VARCHAR(500) NULL"
        )
    else:
        for ddl in (
            "last_run_at TIMESTAMP NULL",
            "last_error VARCHAR(500) NULL",
        ):
            try:
                op.execute(f"ALTER TABLE topic_subscriptions ADD COLUMN {ddl}")
            except Exception:
                pass


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE topic_subscriptions DROP COLUMN IF EXISTS last_error")
        op.execute("ALTER TABLE topic_subscriptions DROP COLUMN IF EXISTS last_run_at")
    else:
        # SQLite DROP COLUMN 支持参差，try/except 兜底
        for col in ("last_error", "last_run_at"):
            try:
                op.execute(f"ALTER TABLE topic_subscriptions DROP COLUMN {col}")
            except Exception:
                pass
