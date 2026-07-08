# 数据库迁移说明

本目录使用 Alembic 管理 schema 迁移。ORM 模型（`packages/storage/models.py`）是 schema 的**唯一真相源**。

## 迁移链

当前为单一迁移：

- `4425bcca6b75_initial_schema` — 初始 schema，包含全部 27 张表

## 常用命令

```bash
# 新库初始化（建全部表）
alembic upgrade head

# 修改模型后生成新迁移
alembic revision --autogenerate -m "描述变更"

# 检查模型与 DB 是否有差异
alembic check

# 回滚一个版本
alembic downgrade -1
```

## 现有运行库的处理

PaperMind 运行时通过 `packages/storage/db.py:run_migrations()`（命令式 `CREATE TABLE IF NOT EXISTS` / `_safe_add_column`）做增量兜底，不直接调用 alembic。对于已存在数据的运行库，若要纳入 alembic 管理：

```bash
# 现有库 schema 已与 head 一致，用 stamp 标记，不实际执行迁移
alembic stamp head
```

之后即可用标准 alembic 工作流管理后续变更。

## 生成迁移时的注意事项

- 用临时空库 autogenerate，避免现有数据干扰：`DATABASE_URL="sqlite:///./data/_tmp_gen.db" alembic revision --autogenerate -m "..."`
- 生成后检查迁移文件，确认无多余 `op.drop_table` / `op.drop_column`（autogenerate 对命名变更会误判为删+建）
