"""
PaperMind CLI 配置管理
@author Color2333
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path


def _config_dir() -> Path:
    return Path(os.environ.get("PAPERMIND_CONFIG_DIR", Path.home() / ".config" / "papermind"))


def config_file() -> Path:
    return _config_dir() / "config.toml"


@dataclass
class Config:
    server_url: str
    token: str
    client_name: str = "pm-cli"


def load_config() -> Config | None:
    """读取 ~/.config/papermind/config.toml；文件缺失/损坏返回 None"""
    path = config_file()
    if not path.exists():
        return None
    try:
        values: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, raw = line.partition("=")
            values[key.strip()] = raw.strip().strip('"')
        if not values.get("server_url") or not values.get("token"):
            return None
        return Config(
            server_url=values["server_url"].rstrip("/"),
            token=values["token"],
            client_name=values.get("client_name", "pm-cli"),
        )
    except OSError:
        return None


def save_config(config: Config) -> Path:
    """写入配置文件，权限 0600（令牌是敏感凭证）"""
    directory = _config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = config_file()
    content = (
        "# PaperMind CLI 配置（pm login 生成）\n"
        f'server_url = "{config.server_url.rstrip("/")}"\n'
        f'token = "{config.token}"\n'
        f'client_name = "{config.client_name}"\n'
    )
    path.write_text(content, encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    return path


def clear_config() -> bool:
    path = config_file()
    if path.exists():
        path.unlink()
        return True
    return False


def resolve_server_url(explicit: str | None = None) -> str | None:
    """优先级：命令行参数 > 环境变量 > 配置文件"""
    if explicit:
        return explicit.rstrip("/")
    env = os.environ.get("PAPERMIND_SERVER_URL")
    if env:
        return env.rstrip("/")
    cfg = load_config()
    return cfg.server_url if cfg else None


def resolve_token() -> str | None:
    """优先级：环境变量 > 配置文件"""
    env = os.environ.get("PAPERMIND_TOKEN")
    if env:
        return env
    cfg = load_config()
    return cfg.token if cfg else None
