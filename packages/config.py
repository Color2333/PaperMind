"""
应用配置 - Pydantic Settings
支持桌面模式通过 PAPERMIND_ENV_FILE / PAPERMIND_DATA_DIR 环境变量注入路径。
@author Color2333
"""

import os
from functools import lru_cache
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

    # 站点配置
    site_url: str = "http://localhost:3002"  # 默认本地，生产环境设为 https://pm.vibingu.cn

    # 认证配置
    auth_password: str = ""  # 站点密码，为空则禁用认证
    auth_secret_key: str = ""  # JWT 密钥，生产环境必须配置，为空时启用认证会报错

    database_url: str = "sqlite:////app/data/papermind.db"
    pdf_storage_root: Path = Path("./data/papers")
    brief_output_root: Path = Path("./data/briefs")
    skim_score_threshold: float = 0.65
    daily_cron: str = "0 21 * * *"
    weekly_cron: str = "0 22 * * 0"
    cors_allow_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"  # 开发环境
        "http://localhost:3002,http://127.0.0.1:3002,"  # Docker 生产环境
        "https://pm.vibingu.cn"  # 自定义域名 HTTPS
    )

    # LLM Provider: openai / anthropic / zhipu / xiaomi
    llm_provider: str = "xiaomi"
    llm_model_skim: str = "mimo-v2.5"
    llm_model_deep: str = "mimo-v2.5-pro"
    llm_model_vision: str = "mimo-v2.5"
    llm_model_fallback: str = "mimo-v2.5-pro"
    # Embedding 独立 provider（小米 MiMo 不提供 embedding，默认走硅基流动 SiliconFlow 免费 bge-m3）
    embedding_model: str = "BAAI/bge-m3"
    embedding_api_key: str | None = None
    embedding_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_dimensions: int | None = None

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    zhipu_api_key: str | None = None
    xiaomi_api_key: str | None = None
    semantic_scholar_api_key: str | None = None
    openalex_email: str | None = None
    ieee_api_key: str | None = None

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
    # 用户时区（影响"今天"判定、日报日期、按日分组等面向用户的日期逻辑）
    user_timezone: str = "Asia/Shanghai"

    # Demo 站配置
    demo_mode: bool = False
    demo_ip_limit_per_hour: int = 30
    demo_global_rpm: int = 50

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
    # SQLite 需要预先创建数据库文件所在目录；PostgreSQL 等远程库无需
    if settings.database_url.startswith("sqlite:"):
        db_parent = Path(settings.database_url.replace("sqlite:///", "")).parent
        db_parent.mkdir(parents=True, exist_ok=True)
    return settings


# ========== IEEE 集成配置（完整版新增） ==========
# 在 .env 中配置:
# IEEE_API_ENABLED=true
# IEEE_API_KEY=your_key
# IEEE_DAILY_QUOTA_DEFAULT=10


def get_ieee_api_key() -> str | None:
    """获取 IEEE API Key（从环境变量或 settings）"""
    import os

    # 优先从环境变量读取
    return os.getenv("IEEE_API_KEY")


def get_ieee_enabled() -> bool:
    """检查 IEEE 是否启用"""
    import os

    return os.getenv("IEEE_API_ENABLED", "false").lower() == "true"
