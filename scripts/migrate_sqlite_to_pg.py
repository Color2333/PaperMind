#!/usr/bin/env python3
"""
SQLite → PostgreSQL 数据迁移脚本

背景：PaperMind 原本只用 SQLite 单文件库（1507 篇论文 + 向量），现在切到
PostgreSQL（compose 里已有 infra/docker-compose.postgres.yml，pgvector/pgvector:pg16）。
本脚本把 SQLite 库里所有表的数据搬到目标 PG 库。

前置条件：
1. PG 容器已起、空 schema 已通过 `alembic upgrade head` 建好（包括 JSONB 迁移）
2. 环境变量：
   - SOURCE_DATABASE_URL=sqlite:////app/data/papermind.db  （源 SQLite）
   - DATABASE_URL=postgresql+psycopg2://papermind:papermind@postgres:5432/papermind  （目标 PG）
   注：packages.storage.db 在导入时按 DATABASE_URL 创建目标引擎；本脚本另起一个
   源 SQLite 引擎，按表读全量后批量写 PG。

策略：
- 全 ORM：用 Base.metadata 拿到表清单 + 列定义，每表按 select * 全量读，PG 端
  用 session.bulk_insert_mappings 写入（不走 ORM 实例化，快）
- 外键 / 唯一约束：alembic 已建好 schema，直接按表名顺序写入（先父后子）
- 不迁 alembic_version 表（PG 上 alembic 自己维护）
- 1507 篇 + ~27 张表约 15MB，单机一次性跑完

用法：
    # 预览（dry-run，只统计不写）
    python scripts/migrate_sqlite_to_pg.py --dry-run

    # 正式迁移
    python scripts/migrate_sqlite_to_pg.py

    # 指定单表（调试用）
    python scripts/migrate_sqlite_to_pg.py --only papers

@author Color2333
"""

from __future__ import annotations

import argparse
import logging
import os
import pathlib
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, inspect, select

# 让脚本能直接 `python scripts/x.py` 运行（不依赖 PYTHONPATH）
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import packages.storage.models  # noqa: E402, F401  让所有表注册到 Base.metadata
from packages.storage.db import Base  # noqa: E402

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

logger = logging.getLogger("migrate")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# alembic 自己管理的版本表，不参与数据搬运
_SKIP_TABLES = {"alembic_version"}


def _source_engine() -> Engine:
    url = os.environ.get("SOURCE_DATABASE_URL")
    if not url:
        raise SystemExit("环境变量 SOURCE_DATABASE_URL 未设置（源 SQLite URL）")
    if not url.startswith("sqlite:"):
        raise SystemExit(f"SOURCE_DATABASE_URL 必须是 SQLite URL，当前={url}")
    return create_engine(url, pool_pre_ping=True)


def _target_engine() -> Engine:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("环境变量 DATABASE_URL 未设置（目标 PG URL）")
    if not url.startswith("postgresql"):
        raise SystemExit(f"DATABASE_URL 必须是 PostgreSQL URL，当前={url}")
    return create_engine(url, pool_pre_ping=True)


def _table_order(metadata) -> list[str]:
    """按外键依赖排序，父表在前、子表在后。"""
    sorted_tables = metadata.sorted_tables
    return [t.name for t in sorted_tables if t.name not in _SKIP_TABLES]


def _row_count(engine: Engine, table_name: str) -> int:
    with engine.connect() as conn:
        return (
            conn.execute(
                select(__import__("sqlalchemy").text(f"COUNT(*) FROM {table_name}"))
            ).scalar()
            or 0
        )


def _table_exists(engine: Engine, table_name: str) -> bool:
    """检查表在目标库是否存在（源 SQLite 可能缺新表，PG 由 alembic 建全）。"""
    insp = inspect(engine)
    return insp.has_table(table_name)


def migrate(dry_run: bool = False, only: str | None = None) -> None:
    src = _source_engine()
    dst = _target_engine()

    tables = _table_order(Base.metadata)
    if only:
        if only not in tables:
            raise SystemExit(f"--only 指定的表 {only} 不在 Base.metadata 中")
        tables = [only]

    logger.info("源库 = %s", src.url)
    logger.info("目标库 = %s", dst.url)
    logger.info("待迁表（按外键顺序）: %s", tables)

    # 1. 预检：源库各表行数 + 目标库是否为空
    # 源 SQLite 可能缺新表（如 sensemaking 系列），跳过不存在的表
    total_src_rows = 0
    skipped_missing: list[str] = []
    for t in tables:
        if not _table_exists(src, t):
            skipped_missing.append(t)
            logger.info("  %-30s 源库无此表，跳过", t)
            continue
        n = _row_count(src, t)
        total_src_rows += n
        dst_n = _row_count(dst, t)
        logger.info("  %-30s 源=%6d  目标=%6d", t, n, dst_n)
        if dst_n > 0 and not dry_run:
            logger.warning("  ⚠ 目标表 %s 已有 %d 行，将追加（可能撞唯一键冲突）", t, dst_n)
    if skipped_missing:
        logger.info(
            "源库缺失 %d 张表（ newer schema 的新表，PG 侧为空即可）: %s",
            len(skipped_missing),
            skipped_missing,
        )
    logger.info("源库总行数 = %d", total_src_rows)

    if dry_run:
        logger.info("dry-run 模式：不写入，退出")
        return

    if total_src_rows == 0:
        logger.warning("源库无数据，无需迁移")
        return

    # 2. 按表批量搬运
    started = datetime.now(UTC)
    migrated_rows = 0
    for t in tables:
        if not _table_exists(src, t):
            continue
        table_obj = Base.metadata.tables[t]
        cols = [c.name for c in table_obj.columns]

        with src.connect() as src_conn:
            rows = src_conn.execute(select(table_obj)).all()
            mappings = [{c: getattr(row, c) for c in cols} for row in rows]

        if not mappings:
            logger.info("  %-30s 跳过（0 行）", t)
            continue

        with dst.begin() as dst_conn:
            # PG 端按表名直接 bulk insert（不走 ORM 实例化，节省内存/时间）
            dst_conn.execute(table_obj.insert(), mappings)
        migrated_rows += len(mappings)
        logger.info("  %-30s 写入 %6d 行 ✓", t, len(mappings))

    elapsed = (datetime.now(UTC) - started).total_seconds()
    logger.info("迁移完成：%d 行 / %.1fs", migrated_rows, elapsed)

    # 3. 后置校验：目标库行数 vs 源库
    logger.info("=== 后置校验 ===")
    all_match = True
    for t in tables:
        if not _table_exists(src, t):
            continue
        src_n = _row_count(src, t)
        dst_n = _row_count(dst, t)
        match = "✓" if src_n == dst_n else "✗"
        if src_n != dst_n:
            all_match = False
        logger.info("  %-30s 源=%6d  目标=%6d  %s", t, src_n, dst_n, match)

    if all_match:
        logger.info("✓ 所有表行数一致，迁移成功")
    else:
        logger.error("✗ 存在行数不一致，请检查")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="SQLite → PostgreSQL 数据迁移")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    parser.add_argument("--only", type=str, default=None, help="只迁指定表（调试用）")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run, only=args.only)


if __name__ == "__main__":
    main()
