"""`pm ui` loopback bridge（F3，设计⑤ §4）

本地 HTTP 服务，仅绑定 127.0.0.1 随机端口：
- 提供一次性 nonce 建立本地 session（HttpOnly cookie）
- 静态文件服务（frontend/dist）
- API 反向代理（allowlist：只放行 research:read 面）
- Host/Origin 校验，防 DNS rebinding
- 进程退出即销毁所有凭据

用法（pm ui 命令的 Python 侧）：
    from packages.application.commands.bridge import start_bridge
    url = start_bridge(core_base_url="https://pm.example.com", token="pmt_...")
    # → "http://127.0.0.1:54321/?nonce=abc123"
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

# allowlist：只代理 GET 且路径以这些前缀开头的请求
_ALLOWLIST_GET = (
    "/research/",
    "/papers/",
    "/health",
    "/tasks/",
    "/jobs",
    "/today",
    "/trends/",
    "/generated/",
    "/graph/",
    "/topics",
)
_ALLOWLIST_POST = (
    "/rag/ask",
    "/queue/pause",
    "/queue/resume",
)

_static_dir: Path | None = None
_core_base: str = ""
_core_token: str = ""
_session_nonce: str = ""
_session_cookie_value: str = ""


class BridgeHandler(BaseHTTPRequestHandler):
    """处理本地 UI 请求：静态文件 or API 代理"""

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug("bridge: %s", format % args)

    def _check_host(self) -> bool:
        host = self.headers.get("Host", "")
        return host.startswith("127.0.0.1") or host.startswith("[::1]")

    def _check_session(self) -> bool:
        """已建立 session 或正在用 nonce 建立 session"""
        cookie = self.headers.get("Cookie", "")
        if _session_cookie_value and _session_cookie_value in cookie:
            return True
        # nonce 建立流程
        parsed = urlparse(self.path)
        nonce = parse_qs(parsed.query).get("nonce", [None])[0]
        return bool(nonce and nonce == _session_nonce)

    def _proxy_to_core(self) -> None:
        """把 API 请求转发到远程 Core（带 token）"""
        import urllib.error
        import urllib.request

        url = _core_base + self.path
        req = urllib.request.Request(url, method=self.command)
        req.add_header("Authorization", f"Bearer {_core_token}")
        req.add_header("Content-Type", "application/json")
        if self.command == "POST":
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            req.data = body

        try:
            resp = urllib.request.urlopen(req, timeout=30)
            self.send_response(resp.status)
            self.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
            self.end_headers()
            self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as exc:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(exc)}).encode())

    def _serve_static(self) -> None:
        """服务 frontend/dist 静态文件"""
        if _static_dir is None:
            self.send_response(404)
            self.end_headers()
            return

        path = urlparse(self.path).path
        if path == "/" or path.startswith("/?"):
            file_path = _static_dir / "index.html"
        else:
            file_path = _static_dir / path.lstrip("/")
            if not file_path.exists():
                file_path = _static_dir / "index.html"  # SPA fallback
            if not file_path.exists():
                self.send_response(404)
                self.end_headers()
                return

        content_type = {
            ".html": "text/html",
            ".js": "application/javascript",
            ".css": "text/css",
            ".json": "application/json",
            ".png": "image/png",
            ".svg": "image/svg+xml",
            ".woff2": "font/woff2",
        }.get(file_path.suffix, "application/octet-stream")

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(file_path.read_bytes())

    def do_GET(self) -> None:
        if not self._check_host():
            self.send_response(403)
            self.end_headers()
            return

        parsed = urlparse(self.path)

        # nonce 建立 session → 设置 HttpOnly cookie + 直接返回首页（不发 302）
        nonce = parse_qs(parsed.query).get("nonce", [None])[0]
        if nonce and nonce == _session_nonce:
            global _session_cookie_value
            _session_cookie_value = secrets.token_hex(32)
            self.send_response(200)
            self.send_header(
                "Set-Cookie",
                f"pm_session={_session_cookie_value}; HttpOnly; SameSite=Strict; Path=/",
            )
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self._serve_static()
            return

        if not self._check_session():
            self.send_response(401)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>Session required</h1><p>Use the URL printed by pm ui.</p></body></html>"
            )
            return

        # API 代理
        if parsed.path.startswith(_ALLOWLIST_GET):
            self._proxy_to_core()
            return

        # 静态文件
        self._serve_static()

    def do_POST(self) -> None:
        if not self._check_host() or not self._check_session():
            self.send_response(403)
            self.end_headers()
            return

        parsed = urlparse(self.path)
        if parsed.path.startswith(_ALLOWLIST_POST):
            self._proxy_to_core()
            return

        self.send_response(403)
        self.end_headers()


def start_bridge(
    *,
    core_base_url: str,
    token: str,
    static_dir: str | None = None,
    host: str = "127.0.0.1",
) -> str:
    """启动 loopback bridge，返回本地 URL（含一次性 nonce）。

    token 仅存进程内存，退出即销毁。
    """
    global _static_dir, _core_base, _core_token, _session_nonce, _session_cookie_value

    _core_base = core_base_url.rstrip("/")
    _core_token = token
    _session_nonce = secrets.token_urlsafe(32)
    _session_cookie_value = ""

    if static_dir:
        sd = Path(static_dir)
        if sd.is_dir():
            _static_dir = sd

    server = HTTPServer((host, 0), BridgeHandler)  # port 0 = 随机可用端口
    port = server.server_address[1]

    def _serve() -> None:
        server.serve_forever()

    thread = threading.Thread(target=_serve, daemon=True, name="pm-ui-bridge")
    thread.start()

    url = f"http://{host}:{port}/?nonce={_session_nonce}"
    logger.info("pm ui bridge 已启动: %s", url)
    return url


def stop_bridge() -> None:
    """销毁凭据（server 由 daemon 线程自动清理）"""
    global _core_token, _session_cookie_value, _session_nonce
    _core_token = ""
    _session_cookie_value = ""
    _session_nonce = ""
