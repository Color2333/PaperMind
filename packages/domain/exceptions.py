"""
统一异常体系 — 区分业务错误和系统错误，配合全局中间件使用
@author Color2333
"""
from __future__ import annotations


class AppError(Exception):
    """应用异常基类"""

    status_code: int = 500
    error_type: str = "internal_error"

    def __init__(self, message: str = "", *, detail: str | None = None):
        self.message = message or self.__class__.__doc__ or "未知错误"
        self.detail = detail
        super().__init__(self.message)

    def to_dict(self) -> dict:
        d = {
            "error": self.error_type,
            "message": self.message,
        }
        if self.detail:
            d["detail"] = self.detail
        return d


# ---------- 4xx 客户端错误 ----------


class NotFoundError(AppError):
    """资源不存在"""
    status_code = 404
    error_type = "not_found"


class ValidationError(AppError):
    """参数校验失败"""
    status_code = 422
    error_type = "validation_error"


class ConflictError(AppError):
    """资源冲突"""
    status_code = 409
    error_type = "conflict"


class ConfigError(AppError):
    """配置缺失或不合法"""
    status_code = 400
    error_type = "config_error"


# ---------- 5xx 服务端错误 ----------


class ServiceUnavailableError(AppError):
    """外部服务不可用（LLM / SMTP / arXiv 等）"""
    status_code = 503
    error_type = "service_unavailable"


class PipelineError(AppError):
    """流水线执行失败"""
    status_code = 500
    error_type = "pipeline_error"


class TaskError(AppError):
    """后台任务执行失败"""
    status_code = 500
    error_type = "task_error"
