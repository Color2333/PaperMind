"""GitHub OAuth + Demo 临时身份（Stage G2，设计文档 §Phase 6）

- GET  /auth/github/login    → 重定向 GitHub OAuth 授权页
- GET  /auth/github/callback → GitHub 回调：交换 access_token → 获取用户
  → 签发 PaperMind Demo JWT（TTL 限制）→ 重定向前端
- Demo 身份不入 api_tokens 表——独立 JWT payload（auth_method="demo_github"），
  权限由 DemoModeMiddleware 限流/拦截（写接口 403，读接口限流）

配置：GITHUB_CLIENT_ID + GITHUB_CLIENT_SECRET（settings），无配置时端点返回 503。
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from packages.auth import create_access_token
from packages.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/github", tags=["auth"])


def _github_config() -> tuple[str, str]:
    settings = get_settings()
    if not settings.github_client_id or not settings.github_client_secret:
        raise HTTPException(status_code=503, detail="GitHub OAuth 未配置")
    return settings.github_client_id, settings.github_client_secret


@router.get("/login")
async def github_login(redirect_uri: str = ""):
    """重定向到 GitHub OAuth 授权页"""
    client_id, _ = _github_config()
    settings = get_settings()
    callback = redirect_uri or f"{settings.site_url}/auth/github/callback"
    url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={client_id}&redirect_uri={callback}&scope=read:user"
    )
    return RedirectResponse(url=url, status_code=302)


@router.get("/callback")
async def github_callback(code: str, redirect_uri: str = ""):
    """GitHub 回调：code → access_token → 用户信息 → PaperMind Demo JWT"""
    client_id, client_secret = _github_config()
    settings = get_settings()

    async with httpx.AsyncClient(timeout=15) as client:
        # 交换 access_token
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=401,
                detail=f"GitHub token 交换失败: {token_data.get('error_description', 'unknown')}",
            )

        # 获取用户信息
        user_resp = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_data = user_resp.json()
        github_login_name = user_data.get("login", "")
        if not github_login_name:
            raise HTTPException(status_code=401, detail="GitHub 用户信息获取失败")

    # 签发 Demo JWT（TTL 限制 + demo_github 方法标识）
    now = int(time.time())
    token = create_access_token(
        data={
            "sub": f"demo:{github_login_name}",
            "auth_method": "demo_github",
            "github_login": github_login_name,
            "demo": True,
            "iat": now,
        },
        expires_delta=timedelta(minutes=settings.demo_session_ttl_minutes),
    )

    # 重定向到前端（携带 token fragment）
    frontend = redirect_uri or settings.site_url
    return RedirectResponse(
        url=f"{frontend}/?demo_token={token}",
        status_code=302,
    )
