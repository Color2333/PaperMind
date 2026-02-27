"""
数据库引擎和会话管理
@author Bamzc
"""

from __future__ import annotations

import logging
import uuid as _uuid
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text, StaticPool
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from packages.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


settings = get_settings()
_is_sqlite = settings.database_url.startswith("sqlite")
connect_args: dict = {}
if _is_sqlite:
    # 增加 timeout 到 60s，避免并发写入时立即报 database is locked
    connect_args = {"check_same_thread": False, "timeout": 60}
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args=connect_args,
    # SQLite 特定配置
    poolclass=StaticPool if _is_sqlite else None,
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

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
    conn,
    table: str,
    column: str,
    col_type: str,
    default: str,
) -> None:
    """安全添加列（已存在则跳过）"""
    try:
        conn.execute(
            text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type} NOT NULL DEFAULT {default}")
        )
        conn.commit()
        logger.info("Added column %s.%s", table, column)
    except Exception:
        conn.rollback()


def _safe_create_index(conn, idx_name: str, table: str, column: str) -> None:
    """安全创建索引（已存在则跳过）"""
    try:
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({column})"))
        conn.commit()
    except Exception:
        conn.rollback()


def run_migrations() -> None:
    """启动时执行轻量级数据库迁移"""
    with engine.connect() as conn:
        _safe_add_column(
            conn,
            "topic_subscriptions",
            "schedule_frequency",
            "VARCHAR(20)",
            "'daily'",
        )
        _safe_add_column(
            conn,
            "topic_subscriptions",
            "schedule_time_utc",
            "INTEGER",
            "21",
        )
        _safe_add_column(conn, "papers", "favorited", "BOOLEAN", "0")
        # 关键列索引加速 ORDER BY / WHERE 查询
        _safe_create_index(conn, "ix_papers_created_at", "papers", "created_at")
        _safe_create_index(conn, "ix_prompt_traces_created_at", "prompt_traces", "created_at")
        _safe_create_index(conn, "ix_pipeline_runs_created_at", "pipeline_runs", "created_at")
        _safe_create_index(conn, "ix_papers_read_status", "papers", "read_status")
        _safe_create_index(conn, "ix_papers_favorited", "papers", "favorited")
        _safe_create_index(
            conn, "ix_generated_contents_created_at", "generated_contents", "created_at"
        )

        # image_analyses 表（如果不存在则创建）
        try:
            conn.execute(
                text("""
                CREATE TABLE IF NOT EXISTS image_analyses (
                    id VARCHAR(36) PRIMARY KEY,
                    paper_id VARCHAR(36) NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
                    page_number INTEGER NOT NULL,
                    image_index INTEGER NOT NULL DEFAULT 0,
                    image_type VARCHAR(32) NOT NULL DEFAULT 'figure',
                    caption TEXT,
                    description TEXT NOT NULL DEFAULT '',
                    bbox_json JSON,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_image_analyses_paper_id "
                    "ON image_analyses (paper_id)"
                )
            )
            conn.commit()
        except Exception:
            conn.rollback()

        # collection_actions + action_papers 表
        try:
            conn.execute(
                text("""
                CREATE TABLE IF NOT EXISTS collection_actions (
                    id VARCHAR(36) PRIMARY KEY,
                    action_type VARCHAR(32) NOT NULL,
                    title VARCHAR(512) NOT NULL,
                    query VARCHAR(1024),
                    topic_id VARCHAR(36) REFERENCES topic_subscriptions(id) ON DELETE SET NULL,
                    paper_count INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            )
            conn.execute(
                text("""
                CREATE TABLE IF NOT EXISTS action_papers (
                    id VARCHAR(36) PRIMARY KEY,
                    action_id VARCHAR(36) NOT NULL REFERENCES collection_actions(id) ON DELETE CASCADE,
                    paper_id VARCHAR(36) NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
                    UNIQUE(action_id, paper_id)
                )
            """)
            )
            _safe_create_index(
                conn, "ix_collection_actions_type", "collection_actions", "action_type"
            )
            _safe_create_index(
                conn, "ix_collection_actions_created_at", "collection_actions", "created_at"
            )
            _safe_create_index(
                conn, "ix_collection_actions_topic_id", "collection_actions", "topic_id"
            )
            _safe_create_index(conn, "ix_action_papers_action_id", "action_papers", "action_id")
            _safe_create_index(conn, "ix_action_papers_paper_id", "action_papers", "paper_id")
            conn.commit()
        except Exception:
            conn.rollback()

        # 初始化：给没有 action 的已有论文创建 initial_import 记录
        _init_existing_papers_action(conn)


def _init_existing_papers_action(conn) -> None:
    """为没有行动记录的已有论文创建 initial_import 记录（只执行一次）"""
    try:
        orphan_rows = conn.execute(
            text(
                "SELECT p.id, p.created_at FROM papers p "
                "WHERE p.id NOT IN (SELECT paper_id FROM action_papers)"
            )
        ).fetchall()
        if not orphan_rows:
            return

        action_id = _uuid.uuid4().hex[:36]
        conn.execute(
            text(
                "INSERT INTO collection_actions (id, action_type, title, paper_count, created_at) "
                "VALUES (:id, 'initial_import', :title, :cnt, CURRENT_TIMESTAMP)"
            ),
            {
                "id": action_id,
                "title": f"初始导入（{len(orphan_rows)} 篇）",
                "cnt": len(orphan_rows),
            },
        )

        for row in orphan_rows:
            ap_id = _uuid.uuid4().hex[:36]
            conn.execute(
                text(
                    "INSERT INTO action_papers (id, action_id, paper_id) "
                    "VALUES (:id, :action_id, :paper_id)"
                ),
                {"id": ap_id, "action_id": action_id, "paper_id": row[0]},
            )

        conn.commit()
        logger.info(
            "Initialized %d orphan papers into initial_import action %s",
            len(orphan_rows),
            action_id,
        )
    except Exception:
        conn.rollback()
        logger.debug("init_existing_papers_action skipped (already done or error)")
