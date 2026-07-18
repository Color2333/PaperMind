"""add unique constraint on analysis_reports.paper_id

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-17 17:00:00.000000

目的：给 analysis_reports.paper_id 加 unique 约束，防止重复 skim/deep 产生
重复行。此前无约束，并发处理同一论文会插入多行 AnalysisReport，下游读 summary
时取到任意一行（行为不确定）。

迁移顺序：
1. 先删除重复行（同一 paper_id 多行的，保留 created_at 最早的一行）
2. 再加 unique 约束

PG 用窗口函数删重复 + CREATE UNIQUE INDEX IF NOT EXISTS；
SQLite 用 rowid 删重复（保留 MIN(rowid)）+ CREATE UNIQUE INDEX IF NOT EXISTS。
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # 删除重复行：同一 paper_id 保留 created_at 最早的一行
        op.execute(
            """
            DELETE FROM analysis_reports a USING analysis_reports b
            WHERE a.paper_id = b.paper_id
              AND a.id <> b.id
              AND a.created_at > b.created_at
            """
        )
        # 兜底：若仍有同 paper_id 同 created_at 的重复（极端竞态），保留 id 最小者
        op.execute(
            """
            DELETE FROM analysis_reports a USING analysis_reports b
            WHERE a.paper_id = b.paper_id
              AND a.id > b.id
              AND a.created_at = b.created_at
            """
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_reports_paper_id "
            "ON analysis_reports (paper_id)"
        )
    else:
        # SQLite：用 rowid 删重复，保留 MIN(rowid)
        op.execute(
            """
            DELETE FROM analysis_reports
            WHERE rowid NOT IN (
                SELECT MIN(rowid) FROM analysis_reports GROUP BY paper_id
            )
            """
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_reports_paper_id "
            "ON analysis_reports (paper_id)"
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_analysis_reports_paper_id")
