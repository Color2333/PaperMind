"""
API 令牌 / 设备码授权 / 中间件 scope 强制 测试
@author Color2333
"""

from __future__ import annotations

import os

# 必须在导入 apps.api.main 之前强制开启认证并清 settings 缓存，
# 否则中间件读到"未启用认证"的缓存实例，401/403 行为测不了。
os.environ["AUTH_PASSWORD"] = "pm-test-password"
os.environ["AUTH_SECRET_KEY"] = "0" * 64  # 强随机占位，避开启动弱密钥守卫

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import packages.config as _config  # noqa: E402

_config.get_settings.cache_clear()

from apps.api.main import AuthMiddleware  # noqa: E402
from apps.api.routers import auth as auth_router_module  # noqa: E402
from packages.auth import (  # noqa: E402
    API_TOKEN_PREFIX,
    generate_api_token,
    generate_user_code,
    hash_token,
)
from packages.storage.db import session_scope  # noqa: E402
from packages.storage.repositories import (  # noqa: E402
    ApiTokenRepository,
    DeviceAuthRequestRepository,
)


@pytest.fixture(scope="module", autouse=True)
def _restore_auth_env():
    """模块结束后恢复环境变量并清缓存，避免影响其他测试文件"""
    yield
    os.environ.pop("AUTH_PASSWORD", None)
    os.environ.pop("AUTH_SECRET_KEY", None)
    _config.get_settings.cache_clear()


@pytest.fixture
def client(isolated_db):
    """挂了 AuthMiddleware + auth 路由的最小应用（不触发 lifespan/migrations）"""
    app = FastAPI()
    app.include_router(auth_router_module.router)
    app.add_middleware(AuthMiddleware)
    return TestClient(app)


@pytest.fixture
def jwt_headers(client):
    resp = client.post("/auth/login", json={"password": "pm-test-password"})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _create_token(scopes: list[str], name: str = "test-token") -> tuple[str, str]:
    """直接经仓库建令牌，返回 (raw, id)"""
    with session_scope() as session:
        token, raw = ApiTokenRepository(session).create(name=name, scopes=scopes)
        return raw, token.id


# ---------- 令牌工具 ----------


def test_generate_api_token_format():
    raw, prefix, token_hash = generate_api_token()
    assert raw.startswith(API_TOKEN_PREFIX)
    assert prefix == raw[:12]
    assert token_hash == hash_token(raw)
    assert token_hash != raw
    assert len(token_hash) == 64
    raw2, _, hash2 = generate_api_token()
    assert raw2 != raw and hash2 != token_hash


def test_generate_user_code_format():
    code = generate_user_code()
    assert len(code) == 9
    assert code[4] == "-"
    allowed = set("23456789ABCDEFGHJKMNPQRSTUVWXYZ")
    assert set(code.replace("-", "")) <= allowed


# ---------- 令牌仓库 ----------


def test_token_lifecycle_and_revocation(isolated_db):
    raw, token_id = _create_token(["read", "write"])
    with session_scope() as session:
        repo = ApiTokenRepository(session)
        token = repo.get_by_hash(hash_token(raw))
        assert token is not None and token.is_active()
        assert token.last_used_at is None
        repo.touch_last_used(token_id)
        assert repo.get_by_hash(hash_token(raw)).last_used_at is not None
        assert repo.revoke(token_id) is True
        assert repo.revoke(token_id) is False  # 幂等
        assert repo.get_by_hash(hash_token(raw)).is_active() is False
    assert lookup_api_token_helper(raw) is None  # 吊销后拒绝


def test_token_expiry(isolated_db):
    from datetime import UTC, datetime, timedelta

    past = datetime.now(UTC) - timedelta(days=1)
    with session_scope() as session:
        token, _ = ApiTokenRepository(session).create(
            name="expired", scopes=["read"], expires_at=past
        )
        assert token.is_active() is False


def test_lookup_api_token(isolated_db):
    raw, _ = _create_token(["read"], name="ro-token")
    info = lookup_api_token_helper(raw)
    assert info is not None
    assert info.name == "ro-token"
    assert info.scopes == ["read"]
    assert lookup_api_token_helper("not-a-pmt-token") is None
    assert lookup_api_token_helper(raw + "tampered") is None


def lookup_api_token_helper(raw: str):
    from apps.api.token_auth import lookup_api_token

    return lookup_api_token(raw)


# ---------- 设备码授权流程（仓库层） ----------


def test_device_flow_repository_lifecycle(isolated_db):
    with session_scope() as session:
        repo = DeviceAuthRequestRepository(session)
        req, device_code = repo.create("my-macbook")
        assert req.status == "pending"
        assert "-" in req.user_code
        found = repo.get_by_device_code(device_code)
        assert found is not None and found.id == req.id
        assert repo.get_by_user_code(req.user_code.lower()).id == req.id  # 大小写归一
        assert repo.approve(req.id) is not None
        assert repo.approve(req.id) is None  # 非 pending 再批准失败
        assert repo.get_by_device_code(device_code).status == "approved"

    with session_scope() as session:
        repo = DeviceAuthRequestRepository(session)
        req2, _ = repo.create("denied-cli")
        assert repo.deny(req2.id) is not None
        assert repo.deny(req2.id) is None


# ---------- 中间件 + 路由（HTTP 层） ----------


def test_login_and_me(client):
    resp = client.post("/auth/login", json={"password": "wrong"})
    assert resp.status_code == 401

    resp = client.get("/auth/me")
    assert resp.status_code == 401  # 无凭证

    resp = client.post("/auth/login", json={"password": "pm-test-password"})
    assert resp.status_code == 200
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    resp = client.get("/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["auth_method"] == "jwt"


def test_middleware_api_token_read_write_scope(client, isolated_db):
    read_raw, _ = _create_token(["read"])
    write_raw, _ = _create_token(["write"])

    # GET 需要 read：read 令牌可访问，write 令牌 403
    assert (
        client.get("/auth/me", headers={"Authorization": f"Bearer {read_raw}"}).status_code == 200
    )
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {write_raw}"})
    assert resp.status_code == 403

    # POST 需要 write
    resp = client.post(
        "/auth/tokens",
        json={"name": "x"},
        headers={"Authorization": f"Bearer {write_raw}"},
    )
    # 通过中间件 scope 检查，但被 require_web_session 拦截（API 令牌不能管理令牌）
    assert resp.status_code == 403
    assert "网页登录会话" in resp.json()["detail"]
    resp = client.post(
        "/auth/tokens", json={"name": "x"}, headers={"Authorization": f"Bearer {read_raw}"}
    )
    assert resp.status_code == 403  # 连 scope 检查都不过

    # 无效令牌 401
    assert (
        client.get("/auth/me", headers={"Authorization": "Bearer pmt_invalid"}).status_code == 401
    )


def test_token_management_endpoints(client, jwt_headers):
    # 创建
    resp = client.post(
        "/auth/tokens",
        json={"name": "cli-macbook", "scopes": ["read"], "expires_in_days": 30},
        headers=jwt_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"].startswith(API_TOKEN_PREFIX)
    raw = body["token"]

    # 新令牌立即可用，且 me 显示 api_token
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {raw}"})
    assert me.json()["auth_method"] == "api_token"
    assert me.json()["scopes"] == ["read"]
    assert me.json()["token_name"] == "cli-macbook"

    # 列表脱敏（不含明文）
    resp = client.get("/auth/tokens", headers=jwt_headers)
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["token_prefix"] == body["token_prefix"]
    assert "token" not in items[0]

    # 明文 token 不能调管理接口
    assert client.get("/auth/tokens", headers={"Authorization": f"Bearer {raw}"}).status_code == 403

    # 吊销后立即失效
    resp = client.delete(f"/auth/tokens/{body['id']}", headers=jwt_headers)
    assert resp.status_code == 200
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {raw}"}).status_code == 401
    assert client.get("/auth/tokens", headers=jwt_headers).json() == []


def test_device_flow_end_to_end(client, jwt_headers):
    # 1. CLI 发起
    resp = client.post("/auth/device/start", json={"client_name": "my-macbook"})
    assert resp.status_code == 200
    start = resp.json()
    assert start["user_code"].count("-") == 1
    assert start["verification_url"].endswith(f"/device?user_code={start['user_code']}")
    device_code = start["device_code"]

    def poll():
        auth_router_module._poll_last.clear()  # 测试中绕过轮询节流
        return client.post("/auth/device/poll", json={"device_code": device_code})

    # 2. 批准前轮询 → pending
    assert poll().json()["status"] == "pending"

    # 3. 未登录不能查授权信息/批准
    assert client.get(f"/auth/device/{start['user_code']}").status_code == 401

    # 4. 网页会话查看 + 批准
    info = client.get(f"/auth/device/{start['user_code']}", headers=jwt_headers)
    assert info.status_code == 200
    assert info.json()["client_name"] == "my-macbook"
    assert client.post(f"/auth/device/{start['user_code']}/deny").status_code == 401

    resp = client.post(f"/auth/device/{start['user_code']}/authorize", headers=jwt_headers)
    assert resp.json()["status"] == "approved"

    # 5. 首次轮询拿到令牌（明文仅一次），之后 delivered
    first = poll().json()
    assert first["status"] == "approved" and first["access_token"]
    raw = first["access_token"]
    assert poll().json()["status"] == "delivered"

    # 6. 设备签发的令牌可用，出现在令牌列表
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {raw}"})
    assert me.json()["auth_method"] == "api_token"
    assert "my-macbook" in me.json()["token_name"]
    assert len(client.get("/auth/tokens", headers=jwt_headers).json()) == 1


def test_device_flow_deny_and_invalid(client, jwt_headers):
    resp = client.post("/auth/device/start", json={})
    start = resp.json()

    def poll():
        auth_router_module._poll_last.clear()
        return client.post("/auth/device/poll", json={"device_code": start["device_code"]})

    assert (
        client.post(f"/auth/device/{start['user_code']}/deny", headers=jwt_headers).json()["status"]
        == "denied"
    )
    assert poll().json()["status"] == "denied"

    assert client.post("/auth/device/poll", json={"device_code": "bogus"}).status_code == 404
    assert client.get("/auth/device/ZZZZ-ZZZZ", headers=jwt_headers).status_code == 404


def test_token_can_revoke_itself(client, isolated_db):
    """pm logout 场景：令牌可以吊销自己，但不能吊销别人/管理列表"""
    raw_a, id_a = _create_token(["read", "write"], name="self-revoke")
    _, id_b = _create_token(["read", "write"], name="other")
    headers = {"Authorization": f"Bearer {raw_a}"}

    resp = client.delete(f"/auth/tokens/{id_b}", headers=headers)
    assert resp.status_code == 403  # 不能吊销别的令牌

    resp = client.delete(f"/auth/tokens/{id_a}", headers=headers)
    assert resp.status_code == 200  # 可以吊销自己
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_device_start_poll_whitelisted_no_auth_required(client):
    """start/poll 在认证中间件白名单内（无凭证也能访问）"""
    resp = client.post("/auth/device/start", json={"client_name": "wh"})
    assert resp.status_code == 200
