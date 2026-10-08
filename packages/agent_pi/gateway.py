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
# 远程网关（sidecar 部署形态）：设置后本进程不再 spawn pm，直接用该 URL
# （容器编排里 gateway 是独立服务，backend/worker 经共享卷物化其配置）
_EXTERNAL_URL = os.environ.get("PAPERMIND_GATEWAY_URL", "").rstrip("/")

_proc: subprocess.Popen | None = None  # noqa: T105


def gateway_base_url() -> str:
    return _EXTERNAL_URL or f"http://127.0.0.1:{_GATEWAY_PORT}"


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
    """确保 Pi 网关就绪，返回 base_url；不可用返回 None（调用方回退直连）。

    PAPERMIND_GATEWAY_URL 已设置（sidecar 形态）时：只物化配置 + 健康检查，
    绝不本地 spawn（生产镜像无 pm；sidecar 由容器编排保证存活）。"""
    global _proc  # noqa: PLW0603
    # 物化模型配置（DB 单一事实源 → models.json/settings.json）——网关按请求
    # 读 agentDir 下的文件，未物化时进程照常启动但每请求 502（且不触发调用方
    # 回退直连）。此前只靠 webchat spawn 物化，纯任务链部署（worker/executor）
    # 从不跑 webchat → 全部 LLM 任务卡死（真机实证）。入口无条件物化（一次
    # DB 读 + 两个小文件写），同时自愈"网关已在跑但缺配置"的状态；DB 配置
    # 改动亦即时生效（与 webchat 每次物化的语义一致）。
    try:
        if host.materialize_model_config() is None:
            logger.warning("[pi-gateway] DB 无 active LLM 配置，网关缺 models.json")
    except Exception:  # noqa: BLE001 — 物化失败不影响网关复用/启动（保持回退语义）
        logger.exception("[pi-gateway] models.json 物化失败")
    if _EXTERNAL_URL:
        if _healthy():
            return gateway_base_url()
        logger.warning("[pi-gateway] 远程网关 %s 不可达，LLM 管线回退直连", _EXTERNAL_URL)
        return None
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
