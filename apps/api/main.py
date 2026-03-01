"""
PaperMind API - FastAPI 入口
@author Color2333
"""

import logging
import time
import uuid as _uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware

from packages.config import get_settings
from packages.domain.exceptions import AppError
from packages.auth import decode_access_token
from packages.logging_setup import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# ---------- 请求日志中间件 ----------


api_logger = logging.getLogger("papermind.api")


class RequestLogMiddleware(BaseHTTPMiddleware):
    """记录每个请求的方法、路径、状态码、耗时"""

    async def dispatch(self, request: Request, call_next):
        req_id = _uuid.uuid4().hex[:8]
        request.state.request_id = req_id
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        api_logger.info(
            "[%s] %s %s → %d (%.0fms)",
            req_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        response.headers["X-Request-Id"] = req_id
        return response


class AuthMiddleware(BaseHTTPMiddleware):
    """认证中间件 - 保护所有 API（白名单除外）"""

    # 白名单路径（无需认证）
    WHITELIST = {
        "/health",
        "/auth/login",
        "/auth/status",
    }

    async def dispatch(self, request: Request, call_next):
        # 未配置密码则跳过认证
        if not settings.auth_password:
            return await call_next(request)

        # 白名单路径跳过认证
        if request.url.path in self.WHITELIST:
            return await call_next(request)

        # 静态文件和文档跳过
        if request.url.path.startswith("/docs") or request.url.path.startswith("/openapi"):
            return await call_next(request)

        # 验证 Authorization header 或 query param token
        auth_header = request.headers.get("Authorization")
        token: str | None = None
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")
        else:
            # 支持 query param token（用于 PDF/图片等浏览器直接请求）
            token = request.query_params.get("token")

        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated"},
            )

        payload = decode_access_token(token)
        if not payload:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
            )

        # 将用户信息存入 request.state
        request.state.user = payload
        return await call_next(request)



settings = get_settings()
app = FastAPI(title=settings.app_name)
app.add_middleware(RequestLogMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError):
    """统一处理所有业务异常"""
    api_logger.warning("[%s] %s: %s", exc.error_type, exc.__class__.__name__, exc.message)
    return JSONResponse(status_code=exc.status_code, content=exc.to_dict())


origins = [x.strip() for x in settings.cors_allow_origins.split(",") if x.strip()]
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins if origins != ["*"] else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ---------- 数据库迁移 ----------

from packages.storage.db import run_migrations

run_migrations()


# ---------- 注册路由 ----------

from apps.api.routers import (  # noqa: E402
    agent,
    auth,
    content,
    graph,
    jobs,
    papers,
    pipelines,
    settings as settings_router,
    system,
    topics,
    writing,
)

app.include_router(system.router)
app.include_router(papers.router)
app.include_router(topics.router)
app.include_router(graph.router)
app.include_router(agent.router)
app.include_router(content.router)
app.include_router(pipelines.router)
app.include_router(settings_router.router)
app.include_router(writing.router)
app.include_router(jobs.router)
app.include_router(auth.router)
