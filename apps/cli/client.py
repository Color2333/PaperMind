"""
PaperMind CLI - HTTP 客户端（服务端 REST API 封装）
@author Color2333
"""

from __future__ import annotations

import httpx

DEFAULT_TIMEOUT = 30.0


class ApiError(Exception):
    """非 2xx 响应"""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class ApiClient:
    """轻量 REST 客户端；token 为空时也可调用无鉴权端点（/health、设备码流程）"""

    def __init__(self, server_url: str, token: str | None = None, timeout: float = DEFAULT_TIMEOUT):
        self.base_url = server_url.rstrip("/")
        self.token = token
        self._timeout = timeout

    def request(self, method: str, path: str, json_body: dict | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            resp = httpx.request(
                method,
                f"{self.base_url}{path}",
                json=json_body,
                headers=headers,
                timeout=self._timeout,
            )
        except httpx.HTTPError as e:
            raise ApiError(0, f"无法连接 {self.base_url}（{e.__class__.__name__}）") from e
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, _extract_error(resp))
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    # ---- 便捷封装 ----

    def health(self) -> dict:
        return self.request("GET", "/health")

    def me(self) -> dict:
        return self.request("GET", "/auth/me")

    def device_start(self, client_name: str) -> dict:
        return self.request("POST", "/auth/device/start", {"client_name": client_name})

    def device_poll(self, device_code: str) -> dict:
        return self.request("POST", "/auth/device/poll", {"device_code": device_code})

    def revoke_token(self, token_id: str) -> dict:
        return self.request("DELETE", f"/auth/tokens/{token_id}")


def _extract_error(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        detail = body.get("detail") if isinstance(body, dict) else None
        if detail:
            return str(detail)
    except Exception:
        pass
    return f"HTTP {resp.status_code}"
