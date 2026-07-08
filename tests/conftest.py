"""
Pytest 全局 fixture —— 内存 SQLite 测试隔离

rebind packages.storage.db.engine / SessionLocal 到内存 SQLite，
Base.metadata.create_all 建全表，使所有 session_scope 调用透明命中测试库。
不导入 apps.api.main，避免 run_migrations() 副作用。
@author Color2333
"""

from __future__ import annotations

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import sessionmaker

import packages.storage.db as db_module

# 导入 models，让所有表注册到 Base.metadata
import packages.storage.models  # noqa: F401
from packages.storage.db import Base


@pytest.fixture(scope="session")
def test_engine():
    """会话级内存引擎 —— 全测试共享同一内存库（StaticPool 保持单连接）"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def isolated_db(monkeypatch, test_engine):
    """函数级隔离：rebind engine + SessionLocal 到内存库，每测试清空表"""
    test_sessionmaker = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)

    # rebind db 模块全局 —— session_scope 调用 SessionLocal() 时透明命中测试库
    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "SessionLocal", test_sessionmaker)

    # 清空所有表（保留 schema，删数据）
    with test_engine.connect() as conn:
        from sqlalchemy import text

        conn.execute(text("PRAGMA foreign_keys=OFF"))
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f"DELETE FROM {table.name}"))
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.commit()

    yield test_engine


@pytest.fixture
def db_session(isolated_db):
    """提供已开启事务的测试 session，自动回滚"""
    session = db_module.SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
