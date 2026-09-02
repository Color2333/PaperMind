"""
认证工具模块 - JWT 生成/验证，密码验证，API 令牌生成/哈希
@author Color2333
"""

import hmac
import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from packages.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24 * 7  # 7天有效期

# ---------- API 令牌（CLI / MCP / 外部 harness 用） ----------

API_TOKEN_PREFIX = "pmt_"
# 设备码授权流程参数
DEVICE_CODE_EXPIRE_SECONDS = 15 * 60
DEVICE_POLL_INTERVAL_SECONDS = 5
# user_code 去混淆字母表（无 0/O/1/I）
_USER_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def hash_token(raw_token: str) -> str:
    """令牌 SHA-256 哈希（DB 只存哈希，不存明文）"""
    return sha256(raw_token.encode("utf-8")).hexdigest()


def generate_api_token() -> tuple[str, str, str]:
    """生成 API 令牌。

    Returns:
        (raw, prefix, token_hash) —— raw 仅在创建时返回一次；
        prefix 用于列表展示；token_hash 入库。
    """
    raw = API_TOKEN_PREFIX + secrets.token_urlsafe(32)
    return raw, raw[:12], hash_token(raw)


def generate_user_code() -> str:
    """生成设备授权 user_code，格式 XXXX-XXXX"""
    body = "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(8))
    return f"{body[:4]}-{body[4:]}"


def generate_device_code() -> tuple[str, str]:
    """生成设备码。

    Returns:
        (raw, device_code_hash) —— raw 给 CLI 轮询用，哈希入库。
    """
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def utc_now() -> datetime:
    return datetime.now(UTC)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    return pwd_context.hash(password)


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """创建 JWT token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode.update({"exp": expire})
    settings = get_settings()
    encoded_jwt = jwt.encode(to_encode, settings.auth_secret_key, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> dict[str, Any] | None:
    """解码 JWT token，失败返回 None"""
    try:
        settings = get_settings()
        payload = jwt.decode(token, settings.auth_secret_key, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def authenticate_user(password: str) -> bool:
    """
    验证站点密码
    使用 hmac.compare_digest 防止时序攻击
    """
    settings = get_settings()
    if not settings.auth_password:
        return False
    return hmac.compare_digest(password, settings.auth_password)
