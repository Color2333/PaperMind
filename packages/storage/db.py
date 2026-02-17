"""
数据库引擎和会话管理
@author Bamzc
"""
from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from packages.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


settings = get_settings()
_is_sqlite = settings.database_url.startswith("sqlite")
connect_args: dict = {}
if _is_sqlite:
    # timeout=30s 避免并发写入时立即报 database is locked
    connect_args = {"check_same_thread": False, "timeout": 30}
engine = create_engine(
    settings.database_url, pool_pre_ping=True, connect_args=connect_args
)
SessionLocal = sessionmaker(
    bind=engine, autocommit=False, autoflush=False
)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):  # type: ignore[no-redef]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=-64000")  # 64MB 缓存
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """提供事务范围的数据库会话"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_db_connection() -> bool:
    """检查数据库连接是否正常"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("Database connection check failed")
        return False


def _safe_add_column(
    conn, table: str, column: str, col_type: str, default: str,
) -> None:
    """安全添加列（已存在则跳过）"""
    try:
        conn.execute(text(
            f"ALTER TABLE {table} ADD COLUMN {column} "
            f"{col_type} NOT NULL DEFAULT {default}"
        ))
        conn.commit()
        logger.info("Added column %s.%s", table, column)
    except Exception:
        conn.rollback()


def _safe_create_index(conn, idx_name: str, table: str, column: str) -> None:
    """安全创建索引（已存在则跳过）"""
    try:
        conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({column})"
        ))
        conn.commit()
    except Exception:
        conn.rollback()


def run_migrations() -> None:
    """启动时执行轻量级数据库迁移"""
    with engine.connect() as conn:
        _safe_add_column(
            conn, "topic_subscriptions",
            "schedule_frequency", "VARCHAR(20)", "'daily'",
        )
        _safe_add_column(
            conn, "topic_subscriptions",
            "schedule_time_utc", "INTEGER", "21",
        )
        _safe_add_column(conn, "papers", "favorited", "BOOLEAN", "0")
        # 关键列索引加速 ORDER BY / WHERE 查询
        _safe_create_index(conn, "ix_papers_created_at", "papers", "created_at")
        _safe_create_index(conn, "ix_prompt_traces_created_at", "prompt_traces", "created_at")
        _safe_create_index(conn, "ix_pipeline_runs_created_at", "pipeline_runs", "created_at")
        _safe_create_index(conn, "ix_papers_read_status", "papers", "read_status")
