"""LLM 配置 / 邮箱配置 / 每日报告配置路由
@author Color2333
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from apps.api.deps import iso_dt, settings
from packages.domain.schemas import LLMProviderCreate, LLMProviderUpdate
from packages.storage.db import session_scope
from packages.storage.repositories import EmailConfigRepository, LLMConfigRepository

router = APIRouter()


# ---------- Pydantic 模型 ----------


class EmailConfigCreate(BaseModel):
    """创建邮箱配置请求"""

    name: str
    smtp_server: str
    smtp_port: int = 587
    smtp_use_tls: bool = True
    sender_email: str
    sender_name: str = "PaperMind"
    username: str
    password: str


class EmailConfigUpdate(BaseModel):
    """更新邮箱配置请求"""

    name: str | None = None
    smtp_server: str | None = None
    smtp_port: int | None = None
    smtp_use_tls: bool | None = None
    sender_email: str | None = None
    sender_name: str | None = None
    username: str | None = None
    password: str | None = None


class DailyReportConfigUpdate(BaseModel):
    """更新每日报告配置请求"""

    enabled: bool | None = None
    auto_deep_read: bool | None = None
    deep_read_limit: int | None = None
    send_email_report: bool | None = None
    recipient_emails: str | None = None
    report_time_utc: int | None = None
    include_paper_details: bool | None = None
    include_graph_insights: bool | None = None


# ---------- 辅助函数 ----------


def _mask_key(key: str) -> str:
    """API Key 脱敏：只显示前4和后4"""
    if len(key) <= 12:
        return key[:2] + "****" + key[-2:]
    return key[:4] + "****" + key[-4:]


def _cfg_to_out(cfg) -> dict:
    return {
        "id": cfg.id,
        "name": cfg.name,
        "provider": cfg.provider,
        "api_key_masked": _mask_key(cfg.api_key),
        "api_base_url": cfg.api_base_url,
        "model_skim": cfg.model_skim,
        "model_deep": cfg.model_deep,
        "model_vision": cfg.model_vision,
        "model_embedding": cfg.model_embedding,
        "model_fallback": cfg.model_fallback,
        "is_active": cfg.is_active,
    }


# ---------- LLM 配置管理 ----------


@router.get("/settings/llm-providers")
def list_llm_providers() -> dict:
    with session_scope() as session:
        cfgs = LLMConfigRepository(session).list_all()
        return {"items": [_cfg_to_out(c) for c in cfgs]}


@router.get("/settings/llm-providers/active")
def get_active_llm_config() -> dict:
    """获取当前生效的 LLM 配置信息（固定路径，必须在动态路径之前）"""
    with session_scope() as session:
        active = LLMConfigRepository(session).get_active()
        if active:
            return {
                "source": "database",
                "config": _cfg_to_out(active),
            }
    return {
        "source": "env",
        "config": {
            "provider": settings.llm_provider,
            "model_skim": settings.llm_model_skim,
            "model_deep": settings.llm_model_deep,
            "model_vision": getattr(settings, "llm_model_vision", None),
            "model_embedding": settings.embedding_model,
            "model_fallback": settings.llm_model_fallback,
            "is_active": True,
        },
    }


@router.post("/settings/llm-providers/deactivate")
def deactivate_llm_providers() -> dict:
    """取消所有配置激活，回退到 .env 默认配置"""
    from packages.integrations.llm_client import invalidate_llm_config_cache

    with session_scope() as session:
        LLMConfigRepository(session).deactivate_all()
        invalidate_llm_config_cache()
        return {
            "status": "ok",
            "message": "All deactivated, using .env defaults",
        }


@router.post("/settings/llm-providers")
def create_llm_provider(req: LLMProviderCreate) -> dict:
    with session_scope() as session:
        cfg = LLMConfigRepository(session).create(
            name=req.name,
            provider=req.provider,
            api_key=req.api_key,
            api_base_url=req.api_base_url,
            model_skim=req.model_skim,
            model_deep=req.model_deep,
            model_vision=req.model_vision,
            model_embedding=req.model_embedding,
            model_fallback=req.model_fallback,
        )
        return _cfg_to_out(cfg)


@router.patch("/settings/llm-providers/{config_id}")
def update_llm_provider(config_id: str, req: LLMProviderUpdate) -> dict:
    with session_scope() as session:
        try:
            cfg = LLMConfigRepository(session).update(
                config_id,
                name=req.name,
                provider=req.provider,
                api_key=req.api_key,
                api_base_url=req.api_base_url,
                model_skim=req.model_skim,
                model_deep=req.model_deep,
                model_vision=req.model_vision,
                model_embedding=req.model_embedding,
                model_fallback=req.model_fallback,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _cfg_to_out(cfg)


@router.delete("/settings/llm-providers/{config_id}")
def delete_llm_provider(config_id: str) -> dict:
    with session_scope() as session:
        LLMConfigRepository(session).delete(config_id)
        return {"deleted": config_id}


@router.post("/settings/llm-providers/{config_id}/activate")
def activate_llm_provider(config_id: str) -> dict:
    from packages.integrations.llm_client import invalidate_llm_config_cache

    with session_scope() as session:
        try:
            cfg = LLMConfigRepository(session).activate(config_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        invalidate_llm_config_cache()
        return _cfg_to_out(cfg)


# ---------- 邮箱配置 ----------


@router.get("/settings/email-configs")
def list_email_configs():
    """获取所有邮箱配置"""
    with session_scope() as session:
        repo = EmailConfigRepository(session)
        configs = repo.list_all()
        return [
            {
                "id": c.id,
                "name": c.name,
                "smtp_server": c.smtp_server,
                "smtp_port": c.smtp_port,
                "smtp_use_tls": c.smtp_use_tls,
                "sender_email": c.sender_email,
                "sender_name": c.sender_name,
                "username": c.username,
                "is_active": c.is_active,
                "created_at": iso_dt(c.created_at),
            }
            for c in configs
        ]


@router.post("/settings/email-configs")
def create_email_config(body: EmailConfigCreate):
    """创建邮箱配置"""
    with session_scope() as session:
        repo = EmailConfigRepository(session)
        config = repo.create(
            name=body.name,
            smtp_server=body.smtp_server,
            smtp_port=body.smtp_port,
            smtp_use_tls=body.smtp_use_tls,
            sender_email=body.sender_email,
            sender_name=body.sender_name,
            username=body.username,
            password=body.password,
        )
        return {"id": config.id, "message": "邮箱配置创建成功"}


@router.patch("/settings/email-configs/{config_id}")
def update_email_config(config_id: str, body: EmailConfigUpdate):
    """更新邮箱配置"""
    with session_scope() as session:
        repo = EmailConfigRepository(session)
        update_data = {k: v for k, v in body.model_dump().items() if v is not None}
        config = repo.update(config_id, **update_data)
        if not config:
            raise HTTPException(status_code=404, detail="邮箱配置不存在")
        return {"message": "邮箱配置更新成功"}


@router.delete("/settings/email-configs/{config_id}")
def delete_email_config(config_id: str):
    """删除邮箱配置"""
    with session_scope() as session:
        repo = EmailConfigRepository(session)
        success = repo.delete(config_id)
        if not success:
            raise HTTPException(status_code=404, detail="邮箱配置不存在")
        return {"message": "邮箱配置删除成功"}


@router.post("/settings/email-configs/{config_id}/activate")
def activate_email_config(config_id: str):
    """激活邮箱配置"""
    with session_scope() as session:
        repo = EmailConfigRepository(session)
        config = repo.set_active(config_id)
        if not config:
            raise HTTPException(status_code=404, detail="邮箱配置不存在")
        return {"message": "邮箱配置已激活"}


@router.post("/settings/email-configs/{config_id}/test")
async def test_email_config(config_id: str):
    """测试邮箱配置（发送测试邮件）"""
    from packages.integrations.email_service import create_test_email

    with session_scope() as session:
        repo = EmailConfigRepository(session)
        config = repo.get_by_id(config_id)
        if not config:
            raise HTTPException(status_code=404, detail="邮箱配置不存在")

        # 在session内发送测试邮件
        try:
            success = create_test_email(config)
            if success:
                return {"message": "测试邮件发送成功"}
            else:
                raise HTTPException(status_code=500, detail="测试邮件发送失败")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"测试邮件发送失败: {str(e)}")


# ---------- 每日报告配置 ----------


@router.get("/settings/daily-report-config")
def get_daily_report_config():
    """获取每日报告配置"""
    from packages.ai.auto_read_service import AutoReadService

    return AutoReadService().get_config()


@router.put("/settings/daily-report-config")
def update_daily_report_config(body: DailyReportConfigUpdate):
    """更新每日报告配置"""
    from packages.ai.auto_read_service import AutoReadService

    update_data = {k: v for k, v in body.model_dump().items() if v is not None}
    config = AutoReadService().update_config(**update_data)
    return {"message": "每日报告配置已更新", "config": config}


# ---------- SMTP 配置预设 ----------


@router.get("/settings/smtp-presets")
def get_smtp_presets():
    """获取常见邮箱服务商的 SMTP 配置预设"""
    from packages.integrations.email_service import get_default_smtp_config

    providers: list[Literal["gmail", "qq", "163", "outlook"]] = ["gmail", "qq", "163", "outlook"]
    return {provider: get_default_smtp_config(provider) for provider in providers}
