"""
设备码授权请求仓储（pm login 设备码流程）
@author Color2333
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from packages.auth import (
    DEVICE_CODE_EXPIRE_SECONDS,
    generate_device_code,
    generate_user_code,
)
from packages.storage.models import DeviceAuthRequest

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def naive_utc() -> datetime:
    """DB 读回的是 naive UTC，写比较值也用 naive 保持一致"""
    return datetime.now(UTC).replace(tzinfo=None)


class DeviceAuthRequestRepository:
    """设备码授权请求数据仓储"""

    def __init__(self, session: Session):
        self.session = session

    def create(self, client_name: str) -> tuple[DeviceAuthRequest, str]:
        """创建授权请求。

        Returns:
            (request, device_code) —— device_code 明文给 CLI 轮询用，DB 存哈希。
        """
        self.cleanup_expired()
        raw_code, code_hash = generate_device_code()
        req = DeviceAuthRequest(
            device_code_hash=code_hash,
            user_code=generate_user_code(),
            client_name=client_name or "pm-cli",
            expires_at=naive_utc() + timedelta(seconds=DEVICE_CODE_EXPIRE_SECONDS),
        )
        self.session.add(req)
        self.session.flush()
        return req, raw_code

    def get_by_device_code(self, device_code: str) -> DeviceAuthRequest | None:
        from packages.auth import hash_token

        q = select(DeviceAuthRequest).where(
            DeviceAuthRequest.device_code_hash == hash_token(device_code)
        )
        return self.session.execute(q).scalar_one_or_none()

    def get_by_user_code(self, user_code: str) -> DeviceAuthRequest | None:
        user_code = user_code.strip().upper()
        q = select(DeviceAuthRequest).where(DeviceAuthRequest.user_code == user_code)
        return self.session.execute(q).scalar_one_or_none()

    def approve(self, request_id: str) -> DeviceAuthRequest | None:
        """批准授权请求（令牌在 CLI 首次轮询时创建并交付）"""
        req = self.session.get(DeviceAuthRequest, request_id)
        if req is None or req.status != "pending" or self.is_expired(req):
            return None
        req.status = "approved"
        req.approved_at = naive_utc()
        self.session.flush()
        return req

    def deny(self, request_id: str) -> DeviceAuthRequest | None:
        req = self.session.get(DeviceAuthRequest, request_id)
        if req is None or req.status != "pending":
            return None
        req.status = "denied"
        self.session.flush()
        return req

    def is_expired(self, req: DeviceAuthRequest) -> bool:
        return req.expires_at.replace(tzinfo=None) < naive_utc()

    def expire_stale(self, req: DeviceAuthRequest) -> DeviceAuthRequest:
        """把已过期的 pending 请求标记为 expired"""
        req.status = "expired"
        self.session.flush()
        return req

    def cleanup_expired(self) -> int:
        """删除已终结（expired/denied）或创建超过 24h 的请求"""
        cutoff = naive_utc() - timedelta(hours=24)
        q = delete(DeviceAuthRequest).where(
            (DeviceAuthRequest.status.in_(["expired", "denied"]))
            | (DeviceAuthRequest.created_at < cutoff)
        )
        result = self.session.execute(q)
        self.session.flush()
        return result.rowcount or 0
