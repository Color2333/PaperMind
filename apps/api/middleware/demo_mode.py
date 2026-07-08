"""
PaperMind Demo 模式中间件
@author Color2333

功能：
1. DEMO_MODE=true 时拦截所有写接口（POST/PUT/DELETE/PATCH），返回 403
2. 按 IP 限流（默认 30 req/h）
3. 全局 RPM 闸门（默认 50/min，保护智谱 key）
4. 失败时返回友好降级响应
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict, deque
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from packages.config import get_settings

if TYPE_CHECKING:
    from fastapi import Request

WRITE_WHITELIST_PREFIX = (
    "/agent/chat",
    "/papers/search",
)


class DemoModeMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        enabled: bool | None = None,
        ip_limit_per_hour: int | None = None,
        global_rpm: int | None = None,
    ):
        super().__init__(app)
        settings = get_settings()
        # 构造参数优先；其次环境变量（测试用 monkeypatch.setenv 覆盖）；最后 Settings 默认值
        if enabled is not None:
            self.enabled = enabled
        elif os.getenv("DEMO_MODE", "").lower() == "true":
            self.enabled = True
        else:
            self.enabled = settings.demo_mode

        if ip_limit_per_hour is not None:
            self.ip_limit = ip_limit_per_hour
        else:
            env_ip = int(os.getenv("DEMO_IP_LIMIT_PER_HOUR", "0"))
            self.ip_limit = env_ip if env_ip else settings.demo_ip_limit_per_hour

        if global_rpm is not None:
            self.global_rpm = global_rpm
        else:
            env_rpm = int(os.getenv("DEMO_GLOBAL_RPM", "0"))
            self.global_rpm = env_rpm if env_rpm else settings.demo_global_rpm
        self._ip_buckets: dict[str, deque[float]] = defaultdict(deque)
        self._global_bucket: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)

        method = request.method
        path = request.url.path

        # 1. 写接口白名单外，403
        if method in {"POST", "PUT", "DELETE", "PATCH"} and not any(
            path.startswith(p) for p in WRITE_WHITELIST_PREFIX
        ):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Demo 站只读体验，完整功能请克隆部署: https://github.com/Color2333/PaperMind"
                },
            )

        # 2. IP + 全局限流
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        async with self._lock:
            # IP 桶（1 小时窗口）
            bucket = self._ip_buckets[client_ip]
            while bucket and bucket[0] < now - 3600:
                bucket.popleft()
            if len(bucket) >= self.ip_limit:
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"请求过于频繁，每 IP 每小时上限 {self.ip_limit} 次"},
                )
            bucket.append(now)

            # 全局桶（1 分钟窗口）
            while self._global_bucket and self._global_bucket[0] < now - 60:
                self._global_bucket.popleft()
            if len(self._global_bucket) >= self.global_rpm:
                return JSONResponse(
                    status_code=503,
                    content={"detail": "demo 站当前繁忙，请 1 分钟后重试"},
                )
            self._global_bucket.append(now)

        return await call_next(request)
