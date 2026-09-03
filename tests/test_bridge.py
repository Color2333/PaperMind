"""F3：loopback bridge 测试——nonce session/allowlist/host 校验/静态文件/API 代理"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from packages.application.commands.bridge import start_bridge, stop_bridge


@pytest.fixture()
def bridge(tmp_path):
    """启动 bridge 并在测试结束后清理"""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>Fake Frontend</body></html>")
    (dist / "app.js").write_text("console.log('ok')")

    url = start_bridge(
        core_base_url="https://core.test",
        token="test_token_123",
        static_dir=str(dist),
    )
    yield url, dist

    stop_bridge()


def _extract_nonce(url: str) -> str:
    from urllib.parse import urlparse

    return parse_qs(urlparse(url).query)["nonce"][0]


def _make_session(base_url: str) -> dict[str, str]:
    """用 nonce 换 cookie，返回带 cookie 的 headers"""
    import http.client

    parsed = urlparse(base_url)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    nonce = _extract_nonce(base_url)
    conn.request("GET", f"/?nonce={nonce}")
    resp = conn.getresponse()
    set_cookie = resp.getheader("Set-Cookie", "")
    resp.read()
    conn.close()
    cookie_val = set_cookie.split("pm_session=")[1].split(";")[0]
    return {"Cookie": f"pm_session={cookie_val}"}


def test_bridge_serves_frontend_after_session(bridge):
    url, dist = bridge

    # 无 session → 401
    import http.client

    parsed = urlparse(url)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    conn.request("GET", "/")
    resp = conn.getresponse()
    assert resp.status == 401
    resp.read()
    conn.close()

    # nonce 建立 session
    headers = _make_session(url)

    # 有 session → 静态文件
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    conn.request("GET", "/", headers=headers)
    resp = conn.getresponse()
    assert resp.status == 200
    assert b"Fake Frontend" in resp.read()
    conn.close()


def test_bridge_host_validation(bridge):
    """Host 必须是 127.0.0.1 —— 防 DNS rebinding"""

    url, _ = bridge
    base = url.rsplit("?")[0]
    # 用非 loopback Host 访问

    # 直接用 http.client 模拟伪造 Host
    import http.client

    port = urlparse(base).port
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", "/", headers={"Host": "evil.example.com"})
    resp = conn.getresponse()
    conn.close()
    assert resp.status == 403
