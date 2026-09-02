"""
API 令牌校验共享层 —— AuthMiddleware 与 MCP verifier 共用
@author Color2333
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from packages.auth import API_TOKEN_PREFIX, hash_token

logger = logging.getLogger(__name__)

# last_used_at 更新节流：距上次超过该秒数才写库，避免每个请求都写
_LAST_USED_THROTTLE_SECONDS = 60


@dataclass
class TokenInfo:
    """已验证的 API 令牌信息"""

    token_id: str
    name: str
    prefix: str
    scopes: list[str] = field(default_factory=list)


def lookup_api_token(raw_token: str) -> TokenInfo | None:
    """按明文令牌查库校验。无效/吊销/过期返回 None；非 pmt_ 前缀直接返回 None（不查库）。

    同时节流更新 last_used_at。
    """
    if not raw_token.startswith(API_TOKEN_PREFIX):
        return None

    from packages.storage.db import session_scope
    from packages.storage.repositories import ApiTokenRepository

    try:
        with session_scope() as session:
            token = ApiTokenRepository(session).get_by_hash(hash_token(raw_token))
            if token is None or not token.is_active():
                return None
            now = datetime.now(UTC).replace(tzinfo=None)
            last_used = token.last_used_at.replace(tzinfo=None) if token.last_used_at else None
            if last_used is None or (now - last_used).total_seconds() > _LAST_USED_THROTTLE_SECONDS:
                token.last_used_at = now
                session.flush()
            return TokenInfo(
                token_id=token.id,
                name=token.name,
                prefix=token.token_prefix,
                scopes=list(token.scopes),
            )
    except Exception:
        # 表不存在（迁移未跑）等情况下不阻断请求，按无效令牌处理
        logger.debug("API 令牌查询失败", exc_info=True)
        return None


def required_scope_for_method(method: str) -> str:
    """HTTP 方法 → 所需 scope：读方法需 read，写方法需 write"""
    return "read" if method in ("GET", "HEAD", "OPTIONS") else "write"
