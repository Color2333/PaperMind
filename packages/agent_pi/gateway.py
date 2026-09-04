"""Pi LLM 网关生命周期管理（`pm gateway` 子进程）。

定位：skim/deep/claims 等 Python 管线的 LLM 调用统一走 Pi 网关
（OpenAI 兼容 HTTP 面，底层 pi-ai）——Python 不再自建 provider 协议栈。
模型凭据单一事实源是 DB → 桥物化为 models.json → 网关读取。

开关：PAPERMIND_LLM_GATEWAY=1（未设置时 LLMClient 走原直连路径）。

@author Color2333
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

from packages.agent_pi import host  # noqa: E402  —— web_agent_dir 供网关物化目录

_GATEWAY_PORT = int(os.environ.get("PAPERMIND_GATEWAY_PORT", "8765"))
_GATEWAY_TOKEN = os.environ.get("PAPERMIND_GATEWAY_TOKEN", "pm-gateway-internal")
_START_TIMEOUT = 15.0

_proc: subprocess.Popen | None = None  # noqa: T105


def gateway_base_url() -> str:
    return f"http://127.0.0.1:{_GATEWAY_PORT}"


def gateway_token() -> str:
    return _GATEWAY_TOKEN


def _pm_binary() -> str | None:
    candidate = os.environ.get("PAPERMIND_PM_BIN") or shutil.which("pm")
    if candidate and os.path.exists(candidate):
        return candidate
    return None


def _healthy() -> bool:
    try:
        req = Request(f"{gateway_base_url()}/healthz")
        with urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except (URLError, HTTPError, OSError):
        return False


def ensure_gateway() -> str | None:
    """确保 Pi 网关就绪，返回 base_url；不可用返回 None（调用方回退直连）。"""
    global _proc  # noqa: PLW0603
    if not _healthy():
        if _proc is not None and _proc.poll() is None:
            _proc.terminate()
        pm = _pm_binary()
        if pm is None:
            logger.warning("[pi-gateway] pm 未找到，LLM 管线回退直连")
            return None
        env = dict(os.environ)
        env.setdefault("PAPERMIND_GATEWAY_TOKEN", _GATEWAY_TOKEN)
        env.setdefault("PAPERMIND_GATEWAY_PORT", str(_GATEWAY_PORT))
        # 网关读取物化模型配置（models.json/settings.json）——与 webchat 同一 agentDir
        env.setdefault("PAPERMIND_AGENT_DIR", str(host.web_agent_dir()))
        _proc = subprocess.Popen(  # noqa: S603
            [pm, "gateway"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        deadline = time.monotonic() + _START_TIMEOUT
        while time.monotonic() < deadline:
            if _healthy():
                logger.info("[pi-gateway] ready at %s (pid=%s)", gateway_base_url(), _proc.pid)
                return gateway_base_url()
            if _proc.poll() is not None:
                logger.warning("[pi-gateway] pm gateway 提前退出（code=%s）", _proc.returncode)
                return None
            time.sleep(0.3)
        logger.warning("[pi-gateway] 启动超时，LLM 管线回退直连")
        return None
    return gateway_base_url()
