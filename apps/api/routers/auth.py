"""
认证路由 - 登录接口、API 令牌管理、设备码授权流程
@author Color2333
"""

import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from packages.auth import (
    DEVICE_POLL_INTERVAL_SECONDS,
    authenticate_user,
    create_access_token,
)
from packages.config import get_settings
from packages.storage.db import session_scope
from packages.storage.repositories import ApiTokenRepository, DeviceAuthRequestRepository

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AuthStatusResponse(BaseModel):
    auth_enabled: bool


class MeResponse(BaseModel):
    auth_method: str  # jwt | api_token | disabled
    sub: str | None = None
    scopes: list[str] = []
    token_id: str | None = None
    token_name: str | None = None
    token_prefix: str | None = None


class TokenCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    scopes: list[str] = Field(default=["read", "write"])
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class TokenCreatedResponse(BaseModel):
    id: str
    name: str
    token: str  # 明文仅此一次返回
    token_prefix: str
    scopes: list[str]
    expires_at: str | None = None


class TokenItem(BaseModel):
    id: str
    name: str
    token_prefix: str
    scopes: list[str]
    created_by: str
    created_at: str
    last_used_at: str | None = None
    expires_at: str | None = None


class DeviceStartRequest(BaseModel):
    client_name: str = Field(default="pm-cli", max_length=128)


class DeviceStartResponse(BaseModel):
    device_code: str
    user_code: str
    verification_url: str
    expires_in: int
    interval: int


class DevicePollRequest(BaseModel):
    device_code: str


class DevicePollResponse(BaseModel):
    status: str  # pending | approved | denied | expired | delivered
    access_token: str | None = None
    token_name: str | None = None


class DeviceRequestInfo(BaseModel):
    user_code: str
    client_name: str
    status: str
    expires_in: int


class DeviceDecisionResponse(BaseModel):
    status: str


# ---------- 内部工具 ----------


def require_web_session(request: Request) -> None:
    """令牌管理 / 设备授权页专用：只允许网页 JWT 会话（auth 关闭时放行）。

    防止低权限 API 令牌自我复制/管理令牌。
    """
    if not get_settings().auth_password:
        return
    if getattr(request.state, "auth_method", "") != "jwt":
        raise HTTPException(status_code=403, detail="此操作需要网页登录会话")


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


# 轮询节流（进程内）：同一 device_code 最小间隔，防暴力枚举
_poll_last: dict[str, float] = {}
_POLL_MIN_INTERVAL = 2.0


def _poll_throttled(device_code: str) -> bool:
    now = time.monotonic()
    if len(_poll_last) > 4096:
        _poll_last.clear()
    last = _poll_last.get(device_code)
    _poll_last[device_code] = now
    return last is not None and (now - last) < _POLL_MIN_INTERVAL


# ---------- 基础认证 ----------


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    站点密码登录
    成功返回 JWT token
    """
    settings = get_settings()

    # 如果未配置密码，返回错误
    if not settings.auth_password:
        raise HTTPException(status_code=403, detail="Authentication is disabled")

    # 验证密码
    if not authenticate_user(request.password):
        raise HTTPException(status_code=401, detail="Incorrect password")

    # 生成 token
    access_token = create_access_token(data={"sub": "papermind-user"})
    return LoginResponse(access_token=access_token)


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status():
    """
    检查认证是否启用
    """
    settings = get_settings()
    return AuthStatusResponse(auth_enabled=bool(settings.auth_password))


@router.get("/me", response_model=MeResponse)
async def me(request: Request):
    """当前调用者身份（pm whoami / pm doctor 用）"""
    settings = get_settings()
    if not settings.auth_password:
        return MeResponse(auth_method="disabled")
    method = getattr(request.state, "auth_method", "")
    if method == "api_token":
        return MeResponse(
            auth_method="api_token",
            scopes=getattr(request.state, "auth_scopes", []),
            token_id=getattr(request.state, "token_id", None),
            token_name=getattr(request.state, "token_name", None),
            token_prefix=getattr(request.state, "token_prefix", None),
        )
    if method == "jwt":
        return MeResponse(auth_method="jwt", sub="papermind-user")
    raise HTTPException(status_code=401, detail="Not authenticated")


# ---------- API 令牌管理（仅网页 JWT 会话） ----------


@router.post("/tokens", response_model=TokenCreatedResponse)
async def create_token(body: TokenCreateRequest, request: Request):
    """创建 API 令牌。明文 token 仅在响应中返回一次。"""
    require_web_session(request)
    valid_scopes = [s for s in body.scopes if s in ("read", "write")]
    if not valid_scopes:
        raise HTTPException(status_code=422, detail="scopes 至少包含 read 或 write")
    expires_at = None
    if body.expires_in_days:
        expires_at = datetime.now(UTC) + timedelta(days=body.expires_in_days)

    with session_scope() as session:
        token, raw = ApiTokenRepository(session).create(
            name=body.name, scopes=valid_scopes, created_by="web", expires_at=expires_at
        )
        return TokenCreatedResponse(
            id=token.id,
            name=token.name,
            token=raw,
            token_prefix=token.token_prefix,
            scopes=token.scopes,
            expires_at=_iso(token.expires_at),
        )


@router.get("/tokens", response_model=list[TokenItem])
async def list_tokens(request: Request):
    """列出未吊销的 API 令牌（脱敏，只显示前缀）"""
    require_web_session(request)
    with session_scope() as session:
        tokens = ApiTokenRepository(session).list_all()
        return [
            TokenItem(
                id=t.id,
                name=t.name,
                token_prefix=t.token_prefix,
                scopes=t.scopes,
                created_by=t.created_by,
                created_at=_iso(t.created_at) or "",
                last_used_at=_iso(t.last_used_at),
                expires_at=_iso(t.expires_at),
            )
            for t in tokens
        ]


@router.delete("/tokens/{token_id}", response_model=DeviceDecisionResponse)
async def revoke_token(token_id: str, request: Request):
    """吊销 API 令牌。网页会话可吊销任意令牌；API 令牌仅可吊销自己（pm logout）。"""
    settings = get_settings()
    if settings.auth_password:
        method = getattr(request.state, "auth_method", "")
        is_self = method == "api_token" and getattr(request.state, "token_id", None) == token_id
        if method != "jwt" and not is_self:
            raise HTTPException(status_code=403, detail="此操作需要网页登录会话")
    with session_scope() as session:
        ok = ApiTokenRepository(session).revoke(token_id)
    if not ok:
        raise HTTPException(status_code=404, detail="令牌不存在或已吊销")
    return DeviceDecisionResponse(status="revoked")


# ---------- 设备码授权流程（pm login） ----------


@router.post("/device/start", response_model=DeviceStartResponse)
async def device_start(body: DeviceStartRequest):
    """CLI 发起设备码授权（无需认证，device_code 是后续轮询凭证）"""
    settings = get_settings()
    if not settings.auth_password:
        raise HTTPException(status_code=403, detail="Authentication is disabled")
    with session_scope() as session:
        req, device_code = DeviceAuthRequestRepository(session).create(body.client_name)
        return DeviceStartResponse(
            device_code=device_code,
            user_code=req.user_code,
            verification_url=f"{settings.site_url.rstrip('/')}/device?user_code={req.user_code}",
            expires_in=int(
                (
                    req.expires_at.replace(tzinfo=None) - req.created_at.replace(tzinfo=None)
                ).total_seconds()
            ),
            interval=DEVICE_POLL_INTERVAL_SECONDS,
        )


@router.post("/device/poll", response_model=DevicePollResponse)
async def device_poll(body: DevicePollRequest):
    """CLI 轮询授权结果。批准后的首次轮询创建并返回令牌（明文仅此一次）。"""
    settings = get_settings()
    if not settings.auth_password:
        raise HTTPException(status_code=403, detail="Authentication is disabled")
    if _poll_throttled(body.device_code):
        raise HTTPException(status_code=429, detail="轮询过于频繁，请按 interval 间隔轮询")

    with session_scope() as session:
        repo = DeviceAuthRequestRepository(session)
        req = repo.get_by_device_code(body.device_code)
        if req is None:
            raise HTTPException(status_code=404, detail="无效的 device_code")
        if req.status == "pending" and repo.is_expired(req):
            req = repo.expire_stale(req)
        if req.status == "pending":
            return DevicePollResponse(status="pending")
        if req.status == "denied":
            return DevicePollResponse(status="denied")
        if req.status == "expired":
            return DevicePollResponse(status="expired")
        # approved：首次轮询创建令牌并交付；之后返回 delivered
        if req.api_token_id is None:
            token, raw = ApiTokenRepository(session).create(
                name=f"{req.client_name} ({req.user_code})",
                scopes=["read", "write"],
                created_by="device",
                device_request_id=req.id,
            )
            req.api_token_id = token.id
            session.flush()
            return DevicePollResponse(status="approved", access_token=raw, token_name=token.name)
        return DevicePollResponse(status="delivered", token_name=req.client_name)


@router.get("/device/{user_code}", response_model=DeviceRequestInfo)
async def device_info(user_code: str, request: Request):
    """授权页查询待授权设备信息（仅网页 JWT 会话）"""
    require_web_session(request)
    with session_scope() as session:
        repo = DeviceAuthRequestRepository(session)
        req = repo.get_by_user_code(user_code)
        if req is None:
            raise HTTPException(status_code=404, detail="授权请求不存在")
        if req.status == "pending" and repo.is_expired(req):
            req = repo.expire_stale(req)
        expires_in = max(
            0,
            int(
                (
                    req.expires_at.replace(tzinfo=None) - datetime.now(UTC).replace(tzinfo=None)
                ).total_seconds()
            ),
        )
        return DeviceRequestInfo(
            user_code=req.user_code,
            client_name=req.client_name,
            status=req.status,
            expires_in=expires_in,
        )


@router.post("/device/{user_code}/authorize", response_model=DeviceDecisionResponse)
async def device_authorize(user_code: str, request: Request):
    """网页端批准设备授权（仅网页 JWT 会话）"""
    require_web_session(request)
    with session_scope() as session:
        repo = DeviceAuthRequestRepository(session)
        req = repo.get_by_user_code(user_code)
        if req is None:
            raise HTTPException(status_code=404, detail="授权请求不存在")
        if req.status == "pending" and repo.is_expired(req):
            req = repo.expire_stale(req)
        approved = repo.approve(req.id)
        if approved is None:
            raise HTTPException(status_code=409, detail="请求已过期或已处理")
        return DeviceDecisionResponse(status="approved")


@router.post("/device/{user_code}/deny", response_model=DeviceDecisionResponse)
async def device_deny(user_code: str, request: Request):
    """网页端拒绝设备授权（仅网页 JWT 会话）"""
    require_web_session(request)
    with session_scope() as session:
        repo = DeviceAuthRequestRepository(session)
        req = repo.get_by_user_code(user_code)
        if req is None:
            raise HTTPException(status_code=404, detail="授权请求不存在")
        denied = repo.deny(req.id)
        if denied is None:
            raise HTTPException(status_code=409, detail="请求已处理")
        return DeviceDecisionResponse(status="denied")
