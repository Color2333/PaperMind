"""
API 令牌仓储
@author Color2333
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from packages.auth import generate_api_token
from packages.storage.models import ApiToken

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class ApiTokenRepository:
    """API 令牌数据仓储"""

    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        name: str,
        scopes: list[str],
        created_by: str = "web",
        expires_at: datetime | None = None,
        device_request_id: str | None = None,
    ) -> tuple[ApiToken, str]:
        """创建令牌。

        Returns:
            (token, raw) —— raw 明文仅此处返回一次，DB 存哈希。
        """
        raw, prefix, token_hash = generate_api_token()
        token = ApiToken(
            name=name,
            token_prefix=prefix,
            token_hash=token_hash,
            scopes=scopes,
            created_by=created_by,
            expires_at=expires_at,
            device_request_id=device_request_id,
        )
        self.session.add(token)
        self.session.flush()
        return token, raw

    def get_by_hash(self, token_hash: str) -> ApiToken | None:
        """按哈希查令牌（中间件 / MCP verifier 用）"""
        q = select(ApiToken).where(ApiToken.token_hash == token_hash)
        return self.session.execute(q).scalar_one_or_none()

    def get_by_id(self, token_id: str) -> ApiToken | None:
        return self.session.get(ApiToken, token_id)

    def list_all(self, include_revoked: bool = False) -> list[ApiToken]:
        """列出令牌，创建时间倒序"""
        q = select(ApiToken).order_by(ApiToken.created_at.desc())
        if not include_revoked:
            q = q.where(ApiToken.revoked_at.is_(None))
        return list(self.session.execute(q).scalars().all())

    def revoke(self, token_id: str) -> bool:
        """吊销令牌（软删除，保留审计记录）"""
        token = self.get_by_id(token_id)
        if token is None or token.revoked_at is not None:
            return False
        token.revoked_at = datetime.now(UTC)
        self.session.flush()
        return True

    def touch_last_used(self, token_id: str) -> None:
        """更新最近使用时间（调用方负责节流）"""
        token = self.get_by_id(token_id)
        if token is not None:
            token.last_used_at = datetime.now(UTC)
            self.session.flush()
