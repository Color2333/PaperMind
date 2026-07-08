"""
DemoMode 中间件测试

运行方式:
    pytest tests/test_demo_mode.py -v
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from apps.api.middleware.demo_mode import DemoModeMiddleware


def _create_app() -> FastAPI:
    app = FastAPI()

    @app.get("/papers")
    def list_papers():
        return JSONResponse({"ok": True})

    @app.post("/papers")
    def create_paper():
        return JSONResponse({"ok": True})

    @app.post("/agent/chat")
    def agent_chat():
        return JSONResponse({"ok": True})

    @app.post("/agent/skim/{paper_id}")
    def agent_skim(paper_id: str):
        return JSONResponse({"ok": True})

    @app.post("/papers/search")
    def search_papers():
        return JSONResponse({"ok": True})

    @app.put("/papers/{paper_id}")
    def update_paper(paper_id: str):
        return JSONResponse({"ok": True})

    @app.delete("/papers/{paper_id}")
    def delete_paper(paper_id: str):
        return JSONResponse({"ok": True})

    @app.patch("/settings")
    def patch_settings():
        return JSONResponse({"ok": True})

    return app


def _setup_demo_env(monkeypatch, ip_limit: str = "9999", global_rpm: str = "9999"):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_IP_LIMIT_PER_HOUR", ip_limit)
    monkeypatch.setenv("DEMO_GLOBAL_RPM", global_rpm)


class TestDemoModePassthrough:
    """DEMO_MODE=false 时所有路径透明"""

    def test_demo_off_get_passthrough(self, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "false")
        app = _create_app()
        app.add_middleware(DemoModeMiddleware)
        client = TestClient(app)
        resp = client.get("/papers")
        assert resp.status_code == 200

    def test_demo_off_post_passthrough(self, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "false")
        app = _create_app()
        app.add_middleware(DemoModeMiddleware)
        client = TestClient(app)
        resp = client.post("/papers")
        assert resp.status_code == 200


class TestDemoBlocksWrites:
    """demo 模式下写接口被拦截"""

    def test_post_papers_blocked(self, monkeypatch):
        _setup_demo_env(monkeypatch)
        app = _create_app()
        app.add_middleware(DemoModeMiddleware)
        client = TestClient(app)
        resp = client.post("/papers")
        assert resp.status_code == 403
        assert "Demo" in resp.json()["detail"]

    def test_put_papers_blocked(self, monkeypatch):
        _setup_demo_env(monkeypatch)
        app = _create_app()
        app.add_middleware(DemoModeMiddleware)
        client = TestClient(app)
        resp = client.put("/papers/1")
        assert resp.status_code == 403

    def test_delete_papers_blocked(self, monkeypatch):
        _setup_demo_env(monkeypatch)
        app = _create_app()
        app.add_middleware(DemoModeMiddleware)
        client = TestClient(app)
        resp = client.delete("/papers/1")
        assert resp.status_code == 403

    def test_patch_blocked(self, monkeypatch):
        _setup_demo_env(monkeypatch)
        app = _create_app()
        app.add_middleware(DemoModeMiddleware)
        client = TestClient(app)
        resp = client.patch("/settings")
        assert resp.status_code == 403


class TestDemoAllowsWhitelist:
    """白名单接口放行"""

    def test_agent_chat_allowed(self, monkeypatch):
        _setup_demo_env(monkeypatch)
        app = _create_app()
        app.add_middleware(DemoModeMiddleware)
        client = TestClient(app)
        resp = client.post("/agent/chat")
        assert resp.status_code == 200

    def test_papers_search_allowed(self, monkeypatch):
        _setup_demo_env(monkeypatch)
        app = _create_app()
        app.add_middleware(DemoModeMiddleware)
        client = TestClient(app)
        resp = client.post("/papers/search")
        assert resp.status_code == 200

    def test_get_papers_allowed(self, monkeypatch):
        _setup_demo_env(monkeypatch)
        app = _create_app()
        app.add_middleware(DemoModeMiddleware)
        client = TestClient(app)
        resp = client.get("/papers")
        assert resp.status_code == 200


class TestIPRateLimit:
    """IP 限流"""

    def test_ip_rate_limit_triggered(self, monkeypatch):
        _setup_demo_env(monkeypatch, ip_limit="5")
        app = _create_app()
        app.add_middleware(DemoModeMiddleware, ip_limit_per_hour=5)
        client = TestClient(app)

        for _ in range(5):
            resp = client.get("/papers")
            assert resp.status_code == 200

        # 第 6 次触发 429
        resp = client.get("/papers")
        assert resp.status_code == 429
        assert "每小时" in resp.json()["detail"]


class TestGlobalRPMGate:
    """全局 RPM 闸门"""

    def test_global_rpm_triggered(self, monkeypatch):
        _setup_demo_env(monkeypatch, global_rpm="5")
        app = _create_app()
        app.add_middleware(DemoModeMiddleware, global_rpm=5)
        client = TestClient(app)

        for _ in range(5):
            resp = client.get("/papers")
            assert resp.status_code == 200

        # 第 6 次触发 503
        resp = client.get("/papers")
        assert resp.status_code == 503
        assert "繁忙" in resp.json()["detail"]
