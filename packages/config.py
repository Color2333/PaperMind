"""
应用配置 - Pydantic Settings
支持桌面模式通过 PAPERMIND_ENV_FILE / PAPERMIND_DATA_DIR 环境变量注入路径。
@author Bamzc
"""

from functools import lru_cache
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_env_file() -> str:
    """优先使用 PAPERMIND_ENV_FILE 环境变量指定的路径"""
    return os.environ.get("PAPERMIND_ENV_FILE", ".env")


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
        "http://localhost:5173,http://127.0.0.1:5173,"  # 开发环境
        "http://localhost:3002,http://127.0.0.1:3002"  # Docker 生产环境
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
    openalex_email: str | None = None

    # Worker 调度
    worker_retry_max: int = 2
    worker_retry_base_delay: float = 5.0

    # 并发与缓存
    paper_concurrency: int = 5
    brief_cache_ttl: int = 300

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
        env_file=_resolve_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.pdf_storage_root.mkdir(parents=True, exist_ok=True)
    settings.brief_output_root.mkdir(parents=True, exist_ok=True)
    db_parent = Path(settings.database_url.replace("sqlite:///", "")).parent
    db_parent.mkdir(parents=True, exist_ok=True)
    return settings
