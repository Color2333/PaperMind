"""json columns to jsonb for postgresql

Revision ID: a1b2c3d4e5f6
Revises: f8a1c2e3d4b5
Create Date: 2026-07-17 10:00:00.000000

目的：把所有 JSON 列在 PostgreSQL 上改造成 JSONB（支持 @> 容器算子、
可建 GIN 索引、存储更紧凑）。SQLite 下此迁移为 no-op（SQLite 只有 JSON 函数，
没有独立 JSONB 类型）。

ORM 端（packages/storage/models.py）已改用 JSONB_or_JSON() 工厂按方言
选型；本迁移负责把"已用 sa.JSON 建表"的现存 PG 库 ALTER 到 JSONB。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'f8a1c2e3d4b5'
branch_labels = None
depends_on = None


# (table, column) 列表：所有在 models.py 里改用 JSONB_or_JSON 的列
# 凡是 models.py 里出现 JSONB_or_JSON() 的列，均需在此 ALTER。
_JSON_COLUMNS: list[tuple[str, str]] = [
    ("papers", "embedding"),
    ("papers", "metadata"),  # ORM 字段名 metadata_json 映射到列名 metadata
    ("analysis_reports", "key_insights"),
    ("image_analyses", "bbox_json"),
    ("topic_subscriptions", "sources"),
    ("agent_messages", "meta"),
    ("agent_pending_actions", "tool_args"),
    ("agent_pending_actions", "conversation_state"),
    ("agent_pending_actions", "metadata_json"),
    ("generated_contents", "metadata_json"),
    ("user_schemas", "research_topics"),
    ("user_schemas", "current_challenges"),
    ("user_schemas", "beliefs"),
    ("user_schemas", "knowledge_gaps"),
    ("sensemaking_sessions", "act1_comprehension"),
    ("sensemaking_sessions", "act2_collision"),
    ("sensemaking_sessions", "act3_reconstruction"),
    ("sensemaking_sessions", "conversation_history"),
    ("schema_paper_interactions", "cognitive_delta"),
    ("paper_translations", "segments"),
    ("batch_jobs", "paper_ids"),
    ("batch_jobs", "error_log"),
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite 等其他方言：JSON 即 JSON，无需变更
        return

    for table, column in _JSON_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=postgresql.JSONB(astext_type=sa.Text()),
            postgresql_using=f"{column}::jsonb",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table, column in _JSON_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.JSON(),
            postgresql_using=f"{column}::json",
        )
