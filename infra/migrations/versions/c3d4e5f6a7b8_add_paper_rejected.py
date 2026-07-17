"""add papers.rejected column for negative feedback

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-17 12:00:00.000000

目的：给 papers 加 rejected 布尔列，支持推荐系统的负反馈。
本轮只预留字段 + 查询排除（recommendation_service 统一 where rejected == False），
UI 后续再加。run_migrations() 兜底也加（SQLite 路径）。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # PG 支持 ADD COLUMN IF NOT EXISTS；SQLite 老版本不支持，用 try/except 兜底
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE papers ADD COLUMN IF NOT EXISTS rejected BOOLEAN NOT NULL DEFAULT FALSE"
        )
    else:
        # SQLite：try/except，列已存在则静默跳过
        try:
            op.execute(
                "ALTER TABLE papers ADD COLUMN rejected BOOLEAN NOT NULL DEFAULT FALSE"
            )
        except Exception:
            pass
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_papers_rejected ON papers (rejected)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_papers_rejected")
    op.execute("ALTER TABLE papers DROP COLUMN IF EXISTS rejected")
