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
