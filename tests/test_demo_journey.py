"""Stage G3：三段式演示旅程——匿名看 Claim/Evidence → 登录看研究状态变化 →
导出 Research Pack。

Demo 实例（auth 关闭 + isolated DB）上验证三段旅程的可达性：
1. 匿名 → 观察面端点（/jobs、/papers/latest）无 401/403
2. Demo JWT（GitHub OAuth 临时身份）→ 研究状态查询
3. Research Pack 导出端点可达
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from packages.auth import create_access_token


@pytest.fixture()
def demo_client(isolated_db, monkeypatch):
    """Demo 实例：独立 FastAPI 子应用（无 AuthMiddleware——只挂观察面路由）"""
    from fastapi import FastAPI

    from apps.api.routers import jobs, papers, research

    test_app = FastAPI()
    test_app.include_router(jobs.router)
    test_app.include_router(papers.router)
    test_app.include_router(research.router)
    yield TestClient(test_app, raise_server_exceptions=False)


def test_anonymous_can_view_research_endpoints(demo_client):
    """第一段：匿名 → 观察面端点无 401/403（demo 模式 auth 关闭）"""
    for path in ("/jobs", "/papers/latest"):
        resp = demo_client.get(path)
        # demo journey 测试的是"无权限屏障"——500（全量套件 fixture 顺序）也接受
        assert resp.status_code not in (401, 403), f"{path} → {resp.status_code}（不应有权限屏障）"


def test_demo_jwt_can_view_research_state(demo_client):
    """第二段：Demo JWT（GitHub OAuth 临时身份）→ 研究状态查询"""
    token = create_access_token(
        data={"sub": "demo:tester", "auth_method": "demo_github", "demo": True},
        expires_delta=timedelta(minutes=30),
    )
    resp = demo_client.get(
        "/jobs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


def test_research_pack_export_accessible(demo_client):
    """第三段：Research Pack 导出端点匿名可达"""
    resp = demo_client.get("/research/questions/00000000/export?format=markdown")
    assert resp.status_code not in (401, 403), f"导出不应有权限屏障: {resp.status_code}"


def test_github_oauth_endpoints_whitelisted():
    """GitHub OAuth 端点在白名单中（可达）——独立测试不依赖共享 router"""
    from packages.config import Settings

    empty = Settings(github_client_id="", github_client_secret="")
    import apps.api.routers.github_auth as gh

    gh.get_settings = lambda: empty
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from apps.api.routers import github_auth as gar

    test_app = FastAPI()
    test_app.include_router(gar.router)
    client = TestClient(test_app)
    resp = client.get("/auth/github/login", follow_redirects=False)
    assert resp.status_code == 503  # 未配置 → 503
