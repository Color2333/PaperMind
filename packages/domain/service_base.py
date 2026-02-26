"""
服务基类 — 统一 session 管理和依赖注入模式
@author Color2333

使用方式：
    # 方式1: 内部自管理 session（默认）
    svc = MyService()
    svc.do_something()

    # 方式2: 外部注入 session（共享事务）
    with session_scope() as session:
        svc = MyService(session=session)
        svc.do_something()  # 与外部 session 共享事务
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy.orm import Session

from packages.storage.db import session_scope

logger = logging.getLogger(__name__)


class ServiceBase:
    """
    服务层基类 — 提供统一的 session 管理

    核心设计：
    - 支持外部注入 session（多个服务共享事务）
    - 支持内部自创建 session（独立事务）
    - 子类通过 self.get_session() 获取 session
    """

    def __init__(self, session: Session | None = None):
        self._external_session = session

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """
        获取数据库会话

        外部注入 session 时直接使用（不管理生命周期）
        否则创建新 session（自动提交/回滚/关闭）
        """
        if self._external_session is not None:
            yield self._external_session
        else:
            with session_scope() as session:
                yield session
