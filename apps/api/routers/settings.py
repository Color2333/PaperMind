"""LLM 配置 / 邮箱配置 / 每日报告配置路由（业务在 application/commands/settings.py）"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from apps.api.deps import settings
from packages.application.commands import settings as settings_commands
from packages.domain.exceptions import NotFoundError
from packages.domain.schemas import (  # noqa: TC001 —— FastAPI 请求体运行期解析
    LLMProviderCreate,
    LLMProviderUpdate,
)
from packages.storage.db import session_scope

router = APIRouter()


class EmailConfigCreate(BaseModel):
    name: str
    smtp_server: str
    smtp_port: int = 587
    smtp_use_tls: bool = True
    sender_email: str
    sender_name: str = "PaperMind"
    username: str
    password: str


class EmailConfigUpdate(BaseModel):
    name: str | None = None
    smtp_server: str | None = None
    smtp_port: int | None = None
    smtp_use_tls: bool | None = None
    sender_email: str | None = None
    sender_name: str | None = None
    username: str | None = None
    password: str | None = None


class DailyReportConfigUpdate(BaseModel):
    enabled: bool | None = None
    auto_deep_read: bool | None = None
    deep_read_limit: int | None = None
    send_email_report: bool | None = None
    recipient_emails: str | None = None
    cron_expression: str | None = None
    include_paper_details: bool | None = None
    include_graph_insights: bool | None = None


def _404(exc: NotFoundError):
    raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------- LLM 配置管理 ----------


@router.get("/settings/llm-providers")
def list_llm_providers() -> dict:
    with session_scope() as session:
        return settings_commands.list_llm_providers(session)


@router.get("/settings/llm-providers/active")
def get_active_llm_config() -> dict:
    with session_scope() as session:
        return settings_commands.get_active_llm_provider(session, settings)


@router.post("/settings/llm-providers/deactivate")
def deactivate_llm_providers() -> dict:
    with session_scope() as session:
        return settings_commands.deactivate_llm_providers(session)


@router.post("/settings/llm-providers")
def create_llm_provider(req: LLMProviderCreate) -> dict:
    with session_scope() as session:
        return settings_commands.create_llm_provider(session, req)


@router.patch("/settings/llm-providers/{config_id}")
def update_llm_provider(config_id: str, req: LLMProviderUpdate) -> dict:
    try:
        with session_scope() as session:
            return settings_commands.update_llm_provider(session, config_id, req)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/settings/llm-providers/{config_id}")
def delete_llm_provider(config_id: str) -> dict:
    with session_scope() as session:
        return settings_commands.delete_llm_provider(session, config_id)


@router.post("/settings/llm-providers/{config_id}/activate")
def activate_llm_provider(config_id: str) -> dict:
    try:
        with session_scope() as session:
            return settings_commands.activate_llm_provider(session, config_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------- 邮箱配置 ----------


@router.get("/settings/email-configs")
def list_email_configs() -> list:
    with session_scope() as session:
        return settings_commands.list_email_configs(session)


@router.post("/settings/email-configs")
def create_email_config(body: EmailConfigCreate) -> dict:
    with session_scope() as session:
        return settings_commands.create_email_config(session, body.model_dump())


@router.patch("/settings/email-configs/{config_id}")
def update_email_config(config_id: str, body: EmailConfigUpdate) -> dict:
    try:
        with session_scope() as session:
            return settings_commands.update_email_config(session, config_id, body.model_dump())
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/settings/email-configs/{config_id}")
def delete_email_config(config_id: str) -> dict:
    try:
        with session_scope() as session:
            return settings_commands.delete_email_config(session, config_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/settings/email-configs/{config_id}/activate")
def activate_email_config(config_id: str) -> dict:
    try:
        with session_scope() as session:
            return settings_commands.activate_email_config(session, config_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/settings/email-configs/{config_id}/test")
def test_email_config(config_id: str) -> dict:
    try:
        with session_scope() as session:
            return settings_commands.test_email_config(session, config_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------- 每日报告配置 ----------


@router.get("/settings/daily-report-config")
def get_daily_report_config() -> dict:
    return settings_commands.get_daily_report_config()


@router.put("/settings/daily-report-config")
def update_daily_report_config(body: DailyReportConfigUpdate) -> dict:
    update_data = {k: v for k, v in body.model_dump().items() if v is not None}
    return settings_commands.update_daily_report_config(**update_data)


# ---------- SMTP 配置预设 ----------


@router.get("/settings/smtp-presets")
def get_smtp_presets() -> dict:
    return settings_commands.get_smtp_presets()
