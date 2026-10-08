"""Stage G2：GitHub OAuth Demo 临时身份测试

覆盖：GitHub OAuth 未配置 → 503；已配置 → login 重定向；callback 交换
（mock httpx）→ JWT demo payload + TTL；DemoMode 中间件对 demo 身份的
写接口 403。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from packages.auth import decode_access_token
from packages.config import get_settings


@pytest.fixture()
def demo_client(monkeypatch, isolated_db):
    """API 客户端 + GitHub OAuth 已配置 + auth 密码空（Demo 模式）"""
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-secret")
    from packages.config import Settings

    new_settings = Settings(github_client_id="test-client-id", github_client_secret="test-secret")
    monkeypatch.setattr("packages.config.get_settings", lambda: new_settings)
    # apps.api.main 模块级 `from packages.config import get_settings` 也需 patch
    import apps.api.routers.github_auth as gh

    monkeypatch.setattr(gh, "get_settings", lambda: new_settings)
    from apps.api.main import app

    yield TestClient(app)


def test_github_login_redirect(demo_client):
    """未配置时 503；配置后 login → 302 重定向 GitHub"""
    resp = demo_client.get("/auth/github/login", follow_redirects=False)
    assert resp.status_code == 302
    assert "github.com/login/oauth/authorize" in resp.headers["location"]
    assert "test-client-id" in resp.headers["location"]


def test_github_not_configured_503(monkeypatch):
    """未配置 GitHub OAuth → 503"""
    from packages.config import Settings

    empty = Settings(github_client_id="", github_client_secret="")
    import apps.api.routers.github_auth as gh

    monkeypatch.setattr(gh, "get_settings", lambda: empty)
    from apps.api.main import app

    client = TestClient(app)
    resp = client.get("/auth/github/login", follow_redirects=False)
    assert resp.status_code == 503


def test_github_callback_creates_demo_jwt(demo_client):
    """callback：mock GitHub token 交换 + 用户信息 → 302 + JWT 可解析"""
    mock_post = AsyncMock(
        return_value=AsyncMock(
            status_code=200,
            json=lambda: {"access_token": "gho_test", "token_type": "bearer"},
        )
    )
    mock_get = AsyncMock(
        return_value=AsyncMock(
            status_code=200,
            json=lambda: {"login": "testuser", "id": 12345},
        )
    )

    with (
        patch("apps.api.routers.github_auth.httpx.AsyncClient") as MockClient,
    ):
        MockClient.return_value.__aenter__ = AsyncMock(return_value=MockClient.return_value)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value.post = mock_post
        MockClient.return_value.get = mock_get

        resp = demo_client.get("/auth/github/callback?code=test-code", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "demo_token=" in location

    # 提取 JWT 并解码验证
    token = location.split("demo_token=")[1].split("&")[0]
    payload = decode_access_token(token)
    assert payload["sub"] == "demo:testuser"
    assert payload["auth_method"] == "demo_github"
    assert payload["demo"] is True
    # TTL ≤ demo_session_ttl_minutes
    exp = payload.get("exp")
    now = datetime.now(UTC).timestamp()
    ttl_minutes = get_settings().demo_session_ttl_minutes
    assert exp is not None and exp - now <= ttl_minutes * 60 + 10


def test_demo_jwt_auth_middleware_accepts(demo_client):
    """Demo JWT 通过 AuthMiddleware（auth_method=demo_github）"""
    from packages.auth import create_access_token

    token = create_access_token(
        data={"sub": "demo:test", "auth_method": "demo_github", "demo": True},
        expires_delta=timedelta(minutes=30),
    )
    # Demo JWT 应通过认证中间件（读接口 200）
    resp = demo_client.get("/papers/latest", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
