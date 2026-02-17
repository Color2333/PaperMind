"""
应用配置 - Pydantic Settings
@author Bamzc
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    app_name: str = "PaperMind API"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    database_url: str = "sqlite:///./data/papermind.db"
    pdf_storage_root: Path = Path("./data/papers")
    brief_output_root: Path = Path("./data/briefs")
    skim_score_threshold: float = 0.65
    daily_cron: str = "0 21 * * *"
    weekly_cron: str = "0 22 * * 0"
    cors_allow_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173"
    )

    # LLM Provider: openai / anthropic / zhipu
    llm_provider: str = "zhipu"
    llm_model_skim: str = "glm-4.7"
    llm_model_deep: str = "glm-4.7"
    llm_model_vision: str = "glm-4.6v"
    llm_model_fallback: str = "glm-4.7"
    embedding_model: str = "embedding-3"

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    zhipu_api_key: str | None = None
    semantic_scholar_api_key: str | None = None

    cost_guard_enabled: bool = True
    per_call_budget_usd: float = 0.05
    daily_budget_usd: float = 2.0

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    notify_default_to: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    Path("./data").mkdir(parents=True, exist_ok=True)
    settings.pdf_storage_root.mkdir(
        parents=True, exist_ok=True
    )
    settings.brief_output_root.mkdir(
        parents=True, exist_ok=True
    )
    return settings
