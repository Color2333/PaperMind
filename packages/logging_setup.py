"""
统一日志配置 — API / Worker / 脚本共享同一格式
@author Color2333
"""
from __future__ import annotations

import logging
import sys


_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = "INFO") -> None:
    """初始化全局日志格式（幂等，多次调用安全）"""
    root = logging.getLogger()
    if root.handlers:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 降低第三方库日志噪音
    for noisy in ("httpx", "httpcore", "urllib3", "openai", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
