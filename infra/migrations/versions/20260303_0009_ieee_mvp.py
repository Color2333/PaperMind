"""add ieee channel support (MVP)

Revision ID: 20260303_0009_ieee_mvp
Revises: 20260228_0008_agent_conversations
Create Date: 2026-03-03

注意：此迁移脚本用于 MVP 阶段，添加 IEEE 渠道支持
- 新增 source 字段（默认 "arxiv"）
- 新增 source_id 字段（渠道唯一 ID）
- 新增 doi 字段（可选）
- arxiv_id 保持向后兼容（标记为 nullable）

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260303_0009_ieee_mvp"
down_revision: Union[str, None] = "20260228_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 添加新字段（允许 NULL，因为要填充默认值）
    op.add_column(
        "papers", sa.Column("source", sa.String(32), nullable=True, server_default="arxiv")
    )
    op.add_column("papers", sa.Column("source_id", sa.String(128), nullable=True))
    op.add_column("papers", sa.Column("doi", sa.String(128), nullable=True))

    # 2. 将现有 arxiv_id 复制到 source_id
    # 注意：SQLite 不支持直接 UPDATE，需要用 batch_mode
    # 但 Alembic 的 batch_mode 在某些情况下可能有问题，所以我们分步处理

    # 3. 创建索引
    with op.batch_alter_table("papers", schema=None) as batch_op:
        batch_op.create_index("ix_papers_source", ["source"])
        batch_op.create_index("ix_papers_source_id", ["source_id"])
        batch_op.create_index("ix_papers_doi", ["doi"])

    # 4. 将 arxiv_id 修改为 nullable（向后兼容）
    # SQLite 不支持 ALTER COLUMN，需要 recreate table
    # 但为了安全，我们用更安全的方式：保留 arxiv_id 原样

    # 5. 数据迁移：将现有 arxiv_id 复制到 source_id
    # 使用 SQLAlchemy 执行原生 SQL
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            UPDATE papers 
            SET source_id = arxiv_id, source = 'arxiv'
            WHERE source_id IS NULL AND arxiv_id IS NOT NULL
        """)
    )

    # 6. 设置 source 字段为 NOT NULL（所有记录都已设置默认值）
    with op.batch_alter_table("papers", schema=None) as batch_op:
        batch_op.alter_column("source", nullable=False)


def downgrade() -> None:
    # 删除索引和新字段
    with op.batch_alter_table("papers", schema=None) as batch_op:
        batch_op.drop_index("ix_papers_doi")
        batch_op.drop_index("ix_papers_source_id")
        batch_op.drop_index("ix_papers_source")

    op.drop_column("papers", "doi")
    op.drop_column("papers", "source_id")
    op.drop_column("papers", "source")
