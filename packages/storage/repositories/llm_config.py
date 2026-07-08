"""
LLM 配置数据仓储
@author Color2333
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from packages.storage.models import LLMProviderConfig


class LLMConfigRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[LLMProviderConfig]:
        q = select(LLMProviderConfig).order_by(LLMProviderConfig.created_at.desc())
        return list(self.session.execute(q).scalars())

    def get_active(self) -> LLMProviderConfig | None:
        q = select(LLMProviderConfig).where(LLMProviderConfig.is_active.is_(True))
        return self.session.execute(q).scalar_one_or_none()

    def get_by_id(self, config_id: str) -> LLMProviderConfig:
        cfg = self.session.get(LLMProviderConfig, config_id)
        if cfg is None:
            raise ValueError(f"llm_config {config_id} not found")
        return cfg

    def create(
        self,
        *,
        name: str,
        provider: str,
        api_key: str,
        api_base_url: str | None,
        model_skim: str,
        model_deep: str,
        model_vision: str | None,
        model_embedding: str,
        model_fallback: str,
    ) -> LLMProviderConfig:
        cfg = LLMProviderConfig(
            name=name,
            provider=provider,
            api_key=api_key,
            api_base_url=api_base_url,
            model_skim=model_skim,
            model_deep=model_deep,
            model_vision=model_vision,
            model_embedding=model_embedding,
            model_fallback=model_fallback,
            is_active=False,
        )
        self.session.add(cfg)
        self.session.flush()
        return cfg

    def update(
        self,
        config_id: str,
        *,
        name: str | None = None,
        provider: str | None = None,
        api_key: str | None = None,
        api_base_url: str | None = None,
        model_skim: str | None = None,
        model_deep: str | None = None,
        model_vision: str | None = None,
        model_embedding: str | None = None,
        model_fallback: str | None = None,
    ) -> LLMProviderConfig:
        cfg = self.get_by_id(config_id)
        if name is not None:
            cfg.name = name
        if provider is not None:
            cfg.provider = provider
        if api_key is not None:
            cfg.api_key = api_key
        if api_base_url is not None:
            cfg.api_base_url = api_base_url
        if model_skim is not None:
            cfg.model_skim = model_skim
        if model_deep is not None:
            cfg.model_deep = model_deep
        if model_vision is not None:
            cfg.model_vision = model_vision
        if model_embedding is not None:
            cfg.model_embedding = model_embedding
        if model_fallback is not None:
            cfg.model_fallback = model_fallback
        cfg.updated_at = datetime.now(UTC)
        self.session.flush()
        return cfg

    def delete(self, config_id: str) -> None:
        cfg = self.session.get(LLMProviderConfig, config_id)
        if cfg is not None:
            self.session.delete(cfg)

    def activate(self, config_id: str) -> LLMProviderConfig:
        """激活指定配置，同时取消其他配置的激活状态"""
        all_cfgs = self.list_all()
        for c in all_cfgs:
            c.is_active = c.id == config_id
        self.session.flush()
        return self.get_by_id(config_id)

    def deactivate_all(self) -> None:
        """取消所有配置的激活状态（回退到 .env 默认配置）"""
        all_cfgs = self.list_all()
        for c in all_cfgs:
            c.is_active = False
        self.session.flush()
