"""Pi 引擎桥：Web 聊天 → pm（Pi agent core）子进程 → PaperMind SSE 事件流。

架构定位（设计④：Pi 是 LLM 网关 + agent 循环的唯一实现）：
- 每个会话一个 Pi session 文件（web-sessions/<conversation_id>.jsonl），
  多轮上下文由 Pi 会话原生承载——Python 不再拼 OpenAI 消息历史；
- `pm -p --json` 输出 Pi agent 事件流（每行一个 JSON 事件），桥翻译为
  PaperMind SSE 契约（text_delta/tool_start/tool_result/done）——
  前端渲染与会话持久化逻辑零改动；
- LLM provider/model 单一事实源是 DB（前端 Settings → llm_provider_configs），
  每次 spawn 前物化为 Pi 的 models.json/settings.json——配置改动即时生效，
  Pi 侧不复刻 provider 配置管理。

@author Color2333
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from packages.agent_core.sse import make_sse

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

# pm 二进制定位：显式 env > PATH（服务端需安装 PaperMind-Terminal 的 pm）
PM_BIN = os.environ.get("PAPERMIND_PM_BIN")
# Web 聊天专用 agentDir（与终端 ~/.config/papermind/agent 隔离：
# 会话文件、模型物化配置互不可见）
AGENT_DIR = os.environ.get("PAPERMIND_WEB_AGENT_DIR")
# pm 工具回访 PaperMind API 的基址（容器内默认本进程端口，可被 env 覆盖）
SELF_URL = os.environ.get("PAPERMIND_SELF_URL")


class PiEngineUnavailable(RuntimeError):
    """pm 不可用（未安装/不在 PATH）——路由层应回退 Python 引擎。"""


def pm_binary() -> str | None:
    candidate = PM_BIN or shutil.which("pm")
    if candidate and Path(candidate).exists():
        return candidate
    return None


def web_agent_dir() -> Path:
    if AGENT_DIR:
        return Path(AGENT_DIR)
    return Path.home() / ".config" / "papermind" / "web-agent"


def session_file_for(conversation_id: str) -> Path:
    return web_agent_dir() / "web-sessions" / f"{conversation_id}.jsonl"


def workspace_dir_for(conversation_id: str) -> Path:
    """每会话独立工作区（E7：工作区文件工具的 cwd 隔离）。

    webchat 由服务端 spawn——若 cwd 是后端进程目录，AI 的 edit/write 会
    改到服务器文件。research profile 允许查看/修改，但只允许在会话自己的
    scratch 工作区内（写论文草稿场景），永不触及服务器文件系统。
    """
    return web_agent_dir() / "workspaces" / conversation_id


def self_base_url() -> str:
    if SELF_URL:
        return SELF_URL.rstrip("/")
    from packages.config import get_settings

    return f"http://127.0.0.1:{get_settings().api_port}"


def pi_engine_available() -> bool:
    return pm_binary() is not None


# ---------- LLM 配置物化（DB → Pi models.json / settings.json） ----------

# DB provider 名 → Pi API 协议名（其余一律按 OpenAI 兼容处理）
_API_MAP = {
    "anthropic": "anthropic-messages",
    "google": "google-generative-ai",
}


def _provider_key(provider: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", provider.strip().lower()).strip("-") or "custom"


def _get_active_llm_config():
    """DB active LLM 配置（测试注入点）。"""
    from packages.storage.db import session_scope
    from packages.storage.repositories import LLMConfigRepository

    with session_scope() as session:
        return LLMConfigRepository(session).get_active()


def materialize_model_config() -> dict | None:
    """把 DB active LLM 配置写成 Pi 的 models.json/settings.json。

    返回 {"provider": <key>, "model": <chat 模型>} 供 engine 事件展示；
    DB 无 active 配置时返回 None（由调用方报错，不让 Pi 兜底报含糊错误）。
    """
    cfg = _get_active_llm_config()
    if cfg is None:
        return None

    agent_dir = web_agent_dir()
    agent_dir.mkdir(parents=True, exist_ok=True)
    key = _provider_key(cfg.provider)
    models = [{"id": mid, "name": mid} for mid in (cfg.model_skim, cfg.model_deep) if mid]
    if cfg.model_vision:
        models.append({"id": cfg.model_vision, "name": cfg.model_vision})
    entry: dict = {
        "name": cfg.name,
        "apiKey": cfg.api_key,
        "api": _API_MAP.get(cfg.provider, "openai-completions"),
        "models": models,
    }
    if cfg.api_base_url:
        entry["baseUrl"] = cfg.api_base_url.rstrip("/")
    (agent_dir / "models.json").write_text(
        json.dumps({"providers": {key: entry}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (agent_dir / "settings.json").write_text(
        json.dumps(
            {"defaultProvider": key, "defaultModel": cfg.model_skim},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {"provider": key, "model": cfg.model_skim}


# ---------- Pi 事件 → PaperMind SSE 翻译 ----------

# 会话头/元数据行不含这些 type——按白名单过滤
_KNOWN_EVENTS = {
    "agent_start",
    "agent_end",
    "turn_start",
    "turn_end",
    "message_start",
    "message_update",
    "message_end",
    "tool_execution_start",
    "tool_execution_update",
    "tool_execution_end",
}


def _summary_of(result: dict) -> str | None:
    content = result.get("content")
    if isinstance(content, list):
        for piece in content:
            if isinstance(piece, dict) and piece.get("type") == "text" and piece.get("text"):
                return str(piece["text"])[:200]
    return None


def _translate(event: dict) -> str | None:
    """单个 Pi 事件 → SSE chunk（不认识的返回 None）。"""
    etype = event.get("type")
    if etype == "message_update":
        sub = event.get("assistantMessageEvent") or {}
        if sub.get("type") == "text_delta" and sub.get("delta"):
            return make_sse("text_delta", {"content": sub["delta"]})
        return None
    if etype == "tool_execution_start":
        return make_sse(
            "tool_start",
            {
                "id": event.get("toolCallId"),
                "name": event.get("toolName"),
                "args": event.get("args") or {},
            },
        )
    if etype == "tool_execution_update":
        # E7：破坏性工具的确认请求（onUpdate 透传）→ 前端确认卡。
        # 主流不关闭——批准后 tool_result 经同一 SSE 到达（与 Python 引擎的
        # "流暂停-续播"不同，Pi 工具阻塞等待决定）。
        partial = event.get("partialResult")
        request = partial.get("action_request") if isinstance(partial, dict) else None
        if isinstance(request, dict) and request.get("id"):
            return make_sse(
                "action_confirm",
                {
                    "id": request.get("id"),
                    "description": request.get("description") or "",
                    "tool": request.get("tool") or event.get("toolName"),
                    "args": request.get("args") or {},
                    "engine": "pi",
                },
            )
        return None
    if etype == "tool_execution_end":
        result = event.get("result") or {}
        return make_sse(
            "tool_result",
            {
                "id": event.get("toolCallId"),
                "name": event.get("toolName"),
                "success": not bool(event.get("isError")),
                "summary": _summary_of(result),
                "data": result.get("details"),
            },
        )
    if etype == "message_end":
        message = event.get("message") or {}
        if message.get("role") == "assistant" and message.get("stopReason") in ("error", "aborted"):
            return make_sse(
                "error",
                {"message": message.get("errorMessage") or f"模型请求{message.get('stopReason')}"},
            )
        return None
    if etype == "agent_end":
        return make_sse("done", {})
    return None


def pi_chat_stream(
    conversation_id: str,
    prompt: str,
    *,
    auth_header: str | None = None,
) -> Iterator[str]:
    """运行 pm -p --json（续接会话文件），yield PaperMind SSE chunk。

    - 上下文：Pi session 文件（多轮），Python 不传历史；
    - 凭据：透传请求方 Authorization（pm 工具以此回访 PaperMind API）；
    - 生命周期：客户端断开（GeneratorExit）即终止子进程。
    """
    pm = pm_binary()
    if pm is None:
        raise PiEngineUnavailable("pm 未安装或不在 PATH（PAPERMIND_PM_BIN）")

    model_info = materialize_model_config()
    if model_info is None:
        yield make_sse(
            "error", {"message": "未配置 LLM 提供者：请在 Settings → LLM Gateway 添加并激活配置"}
        )
        yield make_sse("done", {})
        return

    sfile = session_file_for(conversation_id)
    sfile.parent.mkdir(parents=True, exist_ok=True)
    workspace = workspace_dir_for(conversation_id)
    workspace.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["PAPERMIND_SERVER_URL"] = self_base_url()
    if auth_header:
        env["PAPERMIND_TOKEN"] = auth_header.removeprefix("Bearer ").strip()
    env["PAPERMIND_AGENT_DIR"] = str(web_agent_dir())
    # E7：headless 确认档——破坏性工具走 pending-action 轮询（前端确认卡）
    env["PAPERMIND_WEBCHAT"] = "1"
    env["PAPERMIND_CONVERSATION_ID"] = conversation_id

    cmd = [pm, "-p", "--json", "--session", str(sfile), prompt]
    logger.info(
        "[pi-bridge] spawn pm (session=%s, workspace=%s, model=%s/%s)",
        sfile.name,
        workspace.name,
        model_info["provider"],
        model_info["model"],
    )
    proc = subprocess.Popen(  # noqa: S603 — pm 路径来自 env/PATH，非用户输入
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
        cwd=str(workspace),
    )
    stderr_tail: list[str] = []
    emitted_error = False
    emitted_done = False
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") not in _KNOWN_EVENTS:
                continue  # 会话头/元数据行
            chunk = _translate(event)
            if chunk is None:
                continue
            # 去重：Pi 自动重试会产出多组 error/done——前端只认一组
            etype = event.get("type")
            if etype == "message_end":
                if emitted_error:
                    continue
                emitted_error = True
            elif etype == "agent_end":
                if emitted_done:
                    continue
                emitted_done = True
            yield chunk
        proc.wait()
        if proc.returncode != 0 and proc.stderr is not None:
            stderr_tail = proc.stderr.read().splitlines()[-5:]
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    if proc.returncode not in (0, None):
        detail = " | ".join(stderr_tail) or f"退出码 {proc.returncode}"
        logger.warning("[pi-bridge] pm exit=%s stderr=%s", proc.returncode, detail)
        if not emitted_error:
            yield make_sse("error", {"message": f"Pi agent 异常退出：{detail[:300]}"})
        if not emitted_done:
            yield make_sse("done", {})
