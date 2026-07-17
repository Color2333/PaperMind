"""embedding to pgvector vector column

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-17 11:00:00.000000

目的：把 papers.embedding 从 JSONB 数组升级成 pgvector 原生 vector(1024) 列，
并建 HNSW 索引，使相似度/推荐查询走 DB 侧 ANN 而非 Python 暴力扫描。

- ORM 层 Paper.embedding 属性通过列名映射指向新物理列 embedding_vec
  （见 models.py: mapped_column("embedding_vec", Vector_or_JSON(1024))）
- PostgreSQL：新增 vector(1024) 列、从旧 JSONB 回填、建 HNSW 索引；
  旧 embedding JSONB 列保留作灰度兜底（后续单独迁移删）
- SQLite：旧 embedding JSON 列重命名为 embedding_vec（保持 JSON 类型，
  测试退化为 Python cosine；无 pgvector 扩展，走 _is_sqlite 分支）
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite：重命名 embedding → embedding_vec 保持 JSON 类型，
        # 与 ORM 列名映射对齐（SQLite 无 vector 类型，Vector_or_JSON 退化为 JSON）
        op.execute("ALTER TABLE papers RENAME COLUMN embedding TO embedding_vec")
        return

    # 1. 启用 pgvector 扩展（pgvector/pgvector:pg16 镜像自带，每库需显式 CREATE）
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. 新增 vector(1024) 列（与 bge-m3 原生维度一致）
    op.execute("ALTER TABLE papers ADD COLUMN embedding_vec vector(1024)")

    # 3. 从旧 JSONB 列回填：JSONB::text 产出 "[0.1,0.2,...]"，vector 直接解析
    op.execute(
        "UPDATE papers SET embedding_vec = embedding::text::vector(1024) "
        "WHERE embedding IS NOT NULL"
    )

    # 4. HNSW 索引（余弦距离，与现有 cosine_similarity 语义一致）
    #    1507 篇建索引秒级完成，无需 CONCURRENTLY（大数据量时再改）
    op.execute(
        "CREATE INDEX ix_papers_embedding_vec_hnsw "
        "ON papers USING hnsw (embedding_vec vector_cosine_ops)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        op.execute("ALTER TABLE papers RENAME COLUMN embedding_vec TO embedding")
        return

    op.execute("DROP INDEX IF EXISTS ix_papers_embedding_vec_hnsw")
    op.execute("ALTER TABLE papers DROP COLUMN IF EXISTS embedding_vec")
    # 不 DROP EXTENSION vector —— 其他对象可能依赖它
    # 旧 embedding JSONB 列保留（从未删），可直接用
