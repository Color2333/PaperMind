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

if TYPE_CHECKING:
    from fastapi import Request

WRITE_WHITELIST_PREFIX = (
    "/agent/chat",
    "/agent/skim",
    "/papers/search",
)


class DemoModeMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, ip_limit_per_hour: int = 30, global_rpm: int = 50):
        super().__init__(app)
        self.enabled = os.getenv("DEMO_MODE", "false").lower() == "true"
        self.ip_limit = int(os.getenv("DEMO_IP_LIMIT_PER_HOUR", str(ip_limit_per_hour)))
        self.global_rpm = int(os.getenv("DEMO_GLOBAL_RPM", str(global_rpm)))
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
