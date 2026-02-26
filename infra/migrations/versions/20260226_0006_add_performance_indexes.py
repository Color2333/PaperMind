"""
添加性能优化索引

Revision ID: 20260226_0006
Revises: 20260216_0005
Create Date: 2026-02-26

@author Color2333
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260226_0006"
down_revision = "20260216_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    添加性能优化索引：
    - papers.read_status（按阅读状态查询）
    - papers.created_at（按时间排序）
    - papers.favorited（按收藏筛选）
    - papers (read_status, created_at) 复合索引（组合查询优化）

    注意：由于 SQLAlchemy 的 index=True 可能已自动创建索引，
    这里会检查索引是否存在，避免重复创建。
    """
    from sqlalchemy import inspect, text

    # 获取数据库连接
    conn = op.get_bind()
    inspector = inspect(conn)

    # 获取已存在的索引
    existing_indexes = [idx['name'] for idx in inspector.get_indexes('papers')]

    # 仅创建不存在的索引
    # read_status 索引
    if 'ix_papers_read_status' not in existing_indexes:
        try:
            op.create_index(
                'ix_papers_read_status',
                'papers',
                ['read_status'],
                unique=False,
            )
        except Exception:
            pass  # 索引可能已存在

    # created_at 索引
    if 'ix_papers_created_at' not in existing_indexes:
        try:
            op.create_index(
                'ix_papers_created_at',
                'papers',
                ['created_at'],
                unique=False,
            )
        except Exception:
            pass

    # favorited 索引
    if 'ix_papers_favorited' not in existing_indexes:
        try:
            op.create_index(
                'ix_papers_favorited',
                'papers',
                ['favorited'],
                unique=False,
            )
        except Exception:
            pass

    # 复合索引 (read_status, created_at)
    if 'ix_papers_read_status_created_at' not in existing_indexes:
        try:
            op.create_index(
                'ix_papers_read_status_created_at',
                'papers',
                ['read_status', 'created_at'],
                unique=False,
            )
        except Exception:
            pass


def downgrade() -> None:
    """
    移除性能优化索引
    """
    op.drop_index("ix_papers_read_status_created_at", table_name="papers")
    op.drop_index("ix_papers_favorited", table_name="papers")
    op.drop_index("ix_papers_created_at", table_name="papers")
    op.drop_index("ix_papers_read_status", table_name="papers")
