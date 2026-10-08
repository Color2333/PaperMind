"""设置管理命令（B8 后期，设计② ManageLlmConfig / ManageEmailConfig / ManageReportConfig）"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from packages.domain.exceptions import NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from packages.domain.schemas import LLMProviderCreate, LLMProviderUpdate


def _mask_key(key: str) -> str:
    if len(key) <= 12:
        return key[:2] + "****" + key[-2:]
    return key[:4] + "****" + key[-4:]


def _cfg_to_out(cfg: Any) -> dict[str, Any]:
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


# ---------- LLM 配置 ----------


def list_llm_providers(session: Session) -> dict[str, Any]:
    from packages.storage.repositories import LLMConfigRepository

    return {"items": [_cfg_to_out(c) for c in LLMConfigRepository(session).list_all()]}


def get_active_llm_provider(session: Session, settings: Any) -> dict[str, Any]:
    from packages.storage.repositories import LLMConfigRepository

    active = LLMConfigRepository(session).get_active()
    if active:
        return {"source": "database", "config": _cfg_to_out(active)}
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


def deactivate_llm_providers(session: Session) -> dict[str, Any]:
    from packages.integrations.llm_client import invalidate_llm_config_cache
    from packages.storage.repositories import LLMConfigRepository

    LLMConfigRepository(session).deactivate_all()
    invalidate_llm_config_cache()
    return {"status": "ok", "message": "All deactivated, using .env defaults"}


def create_llm_provider(session: Session, req: LLMProviderCreate) -> dict[str, Any]:
    from packages.storage.repositories import LLMConfigRepository

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


def update_llm_provider(session: Session, config_id: str, req: LLMProviderUpdate) -> dict[str, Any]:
    from packages.storage.repositories import LLMConfigRepository

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
        raise NotFoundError(str(exc)) from exc
    return _cfg_to_out(cfg)


def delete_llm_provider(session: Session, config_id: str) -> dict[str, Any]:
    from packages.storage.repositories import LLMConfigRepository

    LLMConfigRepository(session).delete(config_id)
    return {"deleted": config_id}


def activate_llm_provider(session: Session, config_id: str) -> dict[str, Any]:
    from packages.integrations.llm_client import invalidate_llm_config_cache
    from packages.storage.repositories import LLMConfigRepository

    try:
        cfg = LLMConfigRepository(session).activate(config_id)
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc
    invalidate_llm_config_cache()
    return _cfg_to_out(cfg)


# ---------- 邮箱配置 ----------


def list_email_configs(session: Session) -> list[dict[str, Any]]:
    from packages.storage.repositories import EmailConfigRepository

    def _iso_dt(dt):
        from datetime import UTC

        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.isoformat()

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
            "created_at": _iso_dt(c.created_at),
        }
        for c in EmailConfigRepository(session).list_all()
    ]


def create_email_config(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    from packages.storage.repositories import EmailConfigRepository

    config = EmailConfigRepository(session).create(**body)
    return {"id": config.id, "message": "邮箱配置创建成功"}


def update_email_config(session: Session, config_id: str, body: dict[str, Any]) -> dict[str, Any]:
    from packages.storage.repositories import EmailConfigRepository

    update_data = {k: v for k, v in body.items() if v is not None}
    config = EmailConfigRepository(session).update(config_id, **update_data)
    if not config:
        raise NotFoundError("邮箱配置不存在")
    return {"message": "邮箱配置更新成功"}


def delete_email_config(session: Session, config_id: str) -> dict[str, Any]:
    from packages.storage.repositories import EmailConfigRepository

    if not EmailConfigRepository(session).delete(config_id):
        raise NotFoundError("邮箱配置不存在")
    return {"message": "邮箱配置删除成功"}


def activate_email_config(session: Session, config_id: str) -> dict[str, Any]:
    from packages.storage.repositories import EmailConfigRepository

    if not EmailConfigRepository(session).set_active(config_id):
        raise NotFoundError("邮箱配置不存在")
    return {"message": "邮箱配置已激活"}


def test_email_config(session: Session, config_id: str) -> dict[str, Any]:
    from packages.integrations.email_service import create_test_email
    from packages.storage.repositories import EmailConfigRepository

    config = EmailConfigRepository(session).get_by_id(config_id)
    if not config:
        raise NotFoundError("邮箱配置不存在")
    if not create_test_email(config):
        raise RuntimeError("测试邮件发送失败")
    return {"message": "测试邮件发送成功"}


# ---------- 每日报告配置 ----------


def get_daily_report_config() -> dict[str, Any]:
    from packages.ai.auto_read_service import AutoReadService

    return AutoReadService().get_config()


def update_daily_report_config(**update_data: Any) -> dict[str, Any]:
    from packages.ai.auto_read_service import AutoReadService

    config = AutoReadService().update_config(**update_data)
    return {"message": "每日报告配置已更新", "config": config}


def get_smtp_presets() -> dict[str, Any]:
    from packages.integrations.email_service import get_default_smtp_config

    providers = ["gmail", "qq", "163", "outlook"]
    return {provider: get_default_smtp_config(provider) for provider in providers}
