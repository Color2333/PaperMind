"""add performance indexes on papers.publication_date and collection_actions.created_at

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-17 14:00:00.000000

目的：为高频排序/过滤字段加索引，消除全表扫描。
- papers.publication_date：用于 list_paginated 排序/过滤、frontier 过滤、年份分组
- collection_actions.created_at：用于 ORDER BY created_at DESC、每主题最近行动查询
用 CREATE INDEX IF NOT EXISTS 保证幂等（PG/SQLite 均支持）。
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_papers_publication_date ON papers (publication_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_collection_actions_created_at "
        "ON collection_actions (created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_collection_actions_created_at")
    op.execute("DROP INDEX IF EXISTS ix_papers_publication_date")
