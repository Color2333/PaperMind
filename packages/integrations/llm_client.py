"""
LLM 提供者抽象层 - OpenAI / Anthropic / ZhipuAI / Pseudo
支持从数据库动态加载激活的 LLM 配置
@author Bamzc
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass

from packages.config import get_settings

logger = logging.getLogger(__name__)

# 配置缓存（TTL 30 秒，避免每次 LLM 调用都查库）
_config_cache: LLMConfig | None = None
_config_cache_ts: float = 0.0
_CONFIG_TTL = 30.0


@dataclass
class LLMConfig:
    """当前生效的 LLM 配置"""

    provider: str
    api_key: str | None
    api_base_url: str | None
    model_skim: str
    model_deep: str
    model_vision: str | None
    model_embedding: str
    model_fallback: str


@dataclass
class LLMResult:
    content: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    parsed_json: dict | None = None
    input_cost_usd: float | None = None
    output_cost_usd: float | None = None
    total_cost_usd: float | None = None


@dataclass
class StreamEvent:
    """SSE event from streaming chat"""

    type: str  # "text_delta" | "tool_call" | "done" | "usage" | "error"
    content: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    tool_arguments: str = ""  # JSON string of args
    # usage fields (only for type="usage")
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


def _load_active_config() -> LLMConfig:
    """从数据库加载激活的 LLM 配置，带 TTL 缓存"""
    global _config_cache, _config_cache_ts  # noqa: PLW0603
    now = time.monotonic()
    if _config_cache is not None and (now - _config_cache_ts) < _CONFIG_TTL:
        return _config_cache

    settings = get_settings()
    cfg: LLMConfig | None = None
    try:
        from packages.storage.db import session_scope
        from packages.storage.repositories import (
            LLMConfigRepository,
        )

        with session_scope() as session:
            active = LLMConfigRepository(session).get_active()
            if active:
                cfg = LLMConfig(
                    provider=active.provider,
                    api_key=active.api_key,
                    api_base_url=active.api_base_url,
                    model_skim=active.model_skim,
                    model_deep=active.model_deep,
                    model_vision=active.model_vision,
                    model_embedding=active.model_embedding,
                    model_fallback=active.model_fallback,
                )
    except Exception:
        logger.debug("No active DB config, using .env")

    if cfg is None:
        api_key = None
        base_url = None
        if settings.llm_provider == "zhipu":
            api_key = settings.zhipu_api_key
            base_url = "https://open.bigmodel.cn/api/paas/v4/"
        elif settings.llm_provider == "openai":
            api_key = settings.openai_api_key
        elif settings.llm_provider == "anthropic":
            api_key = settings.anthropic_api_key

        cfg = LLMConfig(
            provider=settings.llm_provider,
            api_key=api_key,
            api_base_url=base_url,
            model_skim=settings.llm_model_skim,
            model_deep=settings.llm_model_deep,
            model_vision=getattr(
                settings, "llm_model_vision", None
            ),
            model_embedding=settings.embedding_model,
            model_fallback=settings.llm_model_fallback,
        )

    _config_cache = cfg
    _config_cache_ts = now
    return cfg


def invalidate_llm_config_cache() -> None:
    """配置变更时调用，清除缓存"""
    global _config_cache, _config_cache_ts  # noqa: PLW0603
    _config_cache = None
    _config_cache_ts = 0.0


# 预置的 provider → base_url 映射
PROVIDER_BASE_URLS: dict[str, str] = {
    "zhipu": "https://open.bigmodel.cn/api/paas/v4/",
    "openai": "https://api.openai.com/v1",
    "anthropic": "",
}


_LLM_TIMEOUT = 120  # LLM 请求超时秒数

# OpenAI 客户端复用缓存（按 api_key + base_url 复用）
_openai_clients: dict[str, object] = {}


def _get_openai_client(api_key: str, base_url: str | None):
    """复用 OpenAI 客户端，避免每次调用创建新连接"""
    from openai import OpenAI
    cache_key = f"{api_key[:8]}|{base_url}"
    if cache_key not in _openai_clients:
        _openai_clients[cache_key] = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=_LLM_TIMEOUT,
        )
    return _openai_clients[cache_key]


class LLMClient:
    """
    统一 LLM 调用客户端。
    配置带 TTL 缓存，OpenAI 客户端复用。
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def provider(self) -> str:
        return self._config().provider

    def _config(self) -> LLMConfig:
        return _load_active_config()

    def _resolve_base_url(self, cfg: LLMConfig) -> str | None:
        if cfg.api_base_url:
            return cfg.api_base_url
        return PROVIDER_BASE_URLS.get(cfg.provider)

    def _resolve_model(
        self,
        stage: str,
        model_override: str | None,
        cfg: LLMConfig | None = None,
    ) -> str:
        if model_override:
            return model_override
        if cfg is None:
            cfg = self._config()
        if stage in ("skim", "rag"):
            return cfg.model_skim
        return cfg.model_deep

    # ---------- 便捷追踪 ----------

    def trace_result(
        self,
        result: LLMResult,
        *,
        stage: str,
        model: str | None = None,
        prompt_digest: str = "",
        paper_id: str | None = None,
    ) -> None:
        """将 LLM 调用结果写入 PromptTrace（便捷方法）"""
        try:
            from packages.storage.db import session_scope
            from packages.storage.repositories import PromptTraceRepository

            resolved_model = model or self._resolve_model(stage, None)
            with session_scope() as session:
                PromptTraceRepository(session).create(
                    stage=stage,
                    provider=self.provider,
                    model=resolved_model,
                    prompt_digest=prompt_digest[:500],
                    paper_id=paper_id,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    input_cost_usd=result.input_cost_usd,
                    output_cost_usd=result.output_cost_usd,
                    total_cost_usd=result.total_cost_usd,
                )
        except Exception as exc:
            logger.debug("trace_result failed: %s", exc)

    # ---------- 公开 API ----------

    def summarize_text(
        self,
        prompt: str,
        stage: str,
        model_override: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        cfg = self._config()
        if cfg.provider in ("openai", "zhipu") and cfg.api_key:
            return self._call_openai_compatible(
                prompt, stage, cfg, model_override,
                max_tokens=max_tokens,
            )
        if cfg.provider == "anthropic" and cfg.api_key:
            return self._call_anthropic(
                prompt, stage, cfg, model_override,
                max_tokens=max_tokens,
            )
        return self._pseudo_summary(
            prompt, stage, cfg, model_override
        )

    def complete_json(
        self,
        prompt: str,
        stage: str,
        model_override: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        wrapped = (
            "请只输出单个 JSON 对象，"
            "不要输出 markdown，不要输出额外解释。\n"
            "如果信息不足，请根据上下文给出最合理的保守估计，"
            "并保持 JSON 结构完整。\n\n"
            f"{prompt}"
        )
        result = self.summarize_text(
            wrapped, stage=stage, model_override=model_override,
            max_tokens=max_tokens,
        )
        parsed = self._try_parse_json(result.content)
        return LLMResult(
            content=result.content,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            parsed_json=parsed,
            input_cost_usd=result.input_cost_usd,
            output_cost_usd=result.output_cost_usd,
            total_cost_usd=result.total_cost_usd,
        )

    def vision_analyze(
        self,
        image_base64: str,
        prompt: str,
        stage: str = "vision",
        max_tokens: int = 1024,
    ) -> LLMResult:
        """发送图片 + 文本给 Vision 模型（GLM-4.6V 等）"""
        cfg = self._config()
        model = cfg.model_vision or cfg.model_deep
        if cfg.provider in ("openai", "zhipu") and cfg.api_key:
            try:
                base_url = self._resolve_base_url(cfg)
                client = _get_openai_client(cfg.api_key or "", base_url)
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_base64}",
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ]
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                )
                vmsg = response.choices[0].message
                content = vmsg.content or ""
                if not content:
                    rc = getattr(vmsg, "reasoning_content", None)
                    if rc and isinstance(rc, str):
                        content = rc
                usage = response.usage
                in_tokens = usage.prompt_tokens if usage else None
                out_tokens = usage.completion_tokens if usage else None
                in_cost, out_cost = self._estimate_cost(
                    model=model, input_tokens=in_tokens, output_tokens=out_tokens,
                )
                return LLMResult(
                    content=content,
                    input_tokens=in_tokens,
                    output_tokens=out_tokens,
                    input_cost_usd=in_cost,
                    output_cost_usd=out_cost,
                    total_cost_usd=in_cost + out_cost,
                )
            except Exception as exc:
                logger.warning("Vision call failed: %s", exc)
                return LLMResult(content=f"[vision fallback] {prompt[:200]}")
        return LLMResult(content=f"[vision unavailable] {prompt[:200]}")

    def embed_text(
        self, text: str, dimensions: int = 1536
    ) -> list[float]:
        cfg = self._config()
        if cfg.provider in ("openai", "zhipu") and cfg.api_key:
            maybe = self._embed_openai_compatible(text, cfg)
            if maybe:
                return maybe
        return self._pseudo_embedding(text, dimensions)

    def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
    ) -> Iterator[StreamEvent]:
        """Stream chat completions with optional tool calling support"""
        cfg = self._config()
        if cfg.provider in ("openai", "zhipu") and cfg.api_key:
            yield from self._chat_stream_openai_compatible(
                messages, tools, max_tokens, cfg
            )
        elif cfg.provider == "anthropic" and cfg.api_key:
            yield from self._chat_stream_anthropic_fallback(
                messages, max_tokens, cfg
            )
        else:
            yield from self._chat_stream_pseudo(messages, cfg)

    def _chat_stream_openai_compatible(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        max_tokens: int,
        cfg: LLMConfig,
    ) -> Iterator[StreamEvent]:
        try:
            model = self._resolve_model("rag", None, cfg)
            base_url = self._resolve_base_url(cfg)
            client = _get_openai_client(cfg.api_key or "", base_url)
            kwargs: dict = {
                "model": model,
                "messages": messages,
                "stream": True,
                "max_tokens": max_tokens,
                "stream_options": {"include_usage": True},
            }
            if tools:
                kwargs["tools"] = tools

            stream = client.chat.completions.create(**kwargs)
            tools_buffer: dict[int, dict[str, str]] = {}
            in_tok, out_tok = 0, 0

            for chunk in stream:
                # 捕获 usage（通常在最后一个 chunk）
                usage = getattr(chunk, "usage", None)
                if usage:
                    in_tok = getattr(usage, "prompt_tokens", 0) or 0
                    out_tok = getattr(usage, "completion_tokens", 0) or 0

                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta is None:
                    continue

                if delta.content:
                    yield StreamEvent(type="text_delta", content=delta.content)

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = getattr(tc, "index", 0)
                        if idx not in tools_buffer:
                            tools_buffer[idx] = {
                                "id": "",
                                "name": "",
                                "arguments": "",
                            }
                        buf = tools_buffer[idx]
                        if getattr(tc, "id", None):
                            buf["id"] = tc.id
                        fn = getattr(tc, "function", None)
                        if fn:
                            if getattr(fn, "name", None):
                                buf["name"] += fn.name or ""
                            if getattr(fn, "arguments", None):
                                buf["arguments"] += fn.arguments or ""

            for idx in sorted(tools_buffer.keys()):
                buf = tools_buffer[idx]
                if buf["id"] or buf["name"] or buf["arguments"]:
                    yield StreamEvent(
                        type="tool_call",
                        tool_call_id=buf["id"],
                        tool_name=buf["name"],
                        tool_arguments=buf["arguments"],
                    )

            # yield usage event before done
            if in_tok or out_tok:
                yield StreamEvent(
                    type="usage", model=model,
                    input_tokens=in_tok, output_tokens=out_tok,
                )
            yield StreamEvent(type="done")
        except Exception as exc:
            logger.warning("chat_stream OpenAI-compatible failed: %s", exc)
            yield StreamEvent(type="error", content=str(exc))

    def _chat_stream_anthropic_fallback(
        self,
        messages: list[dict],
        max_tokens: int,
        cfg: LLMConfig,
    ) -> Iterator[StreamEvent]:
        try:
            prompt = "\n\n".join(
                f"{m.get('role', 'user')}: {m.get('content', '')}"
                for m in messages
                if isinstance(m.get("content"), str)
            )
            result = self._call_anthropic(
                prompt, "rag", cfg, None, max_tokens=max_tokens
            )
            if result.content:
                yield StreamEvent(type="text_delta", content=result.content)
            yield StreamEvent(type="done")
        except Exception as exc:
            logger.warning("chat_stream Anthropic fallback failed: %s", exc)
            yield StreamEvent(type="error", content=str(exc))

    def _chat_stream_pseudo(
        self, messages: list[dict], cfg: LLMConfig
    ) -> Iterator[StreamEvent]:
        prompt = "\n\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}"
            for m in messages
            if isinstance(m.get("content"), str)
        )
        result = self._pseudo_summary(prompt, "rag", cfg, None)
        if result.content:
            yield StreamEvent(type="text_delta", content=result.content)
        yield StreamEvent(type="done")

    # ---------- OpenAI 兼容调用（OpenAI / 智谱）----------

    def _call_openai_compatible(
        self,
        prompt: str,
        stage: str,
        cfg: LLMConfig,
        model_override: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        try:
            model = self._resolve_model(
                stage, model_override, cfg
            )
            base_url = self._resolve_base_url(cfg)
            client = _get_openai_client(cfg.api_key or "", base_url)
            kwargs: dict = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
            }
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            response = client.chat.completions.create(**kwargs)
            msg = response.choices[0].message
            content = msg.content or ""
            # GLM-4.7 等模型可能把输出放在 reasoning_content 中
            if not content:
                rc = getattr(msg, "reasoning_content", None)
                if rc and isinstance(rc, str):
                    content = rc
            usage = response.usage
            in_tokens = (
                usage.prompt_tokens if usage else None
            )
            out_tokens = (
                usage.completion_tokens if usage else None
            )
            in_cost, out_cost = self._estimate_cost(
                model=model,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
            )
            return LLMResult(
                content=content,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                input_cost_usd=in_cost,
                output_cost_usd=out_cost,
                total_cost_usd=in_cost + out_cost,
            )
        except Exception as exc:
            logger.warning(
                "OpenAI-compatible call failed: %s", exc
            )
            return self._pseudo_summary(
                prompt, stage, cfg, model_override
            )

    def _embed_openai_compatible(
        self, text: str, cfg: LLMConfig
    ) -> list[float] | None:
        if not text:
            return None
        try:
            base_url = self._resolve_base_url(cfg)
            client = _get_openai_client(cfg.api_key or "", base_url)
            response = client.embeddings.create(
                model=cfg.model_embedding, input=text
            )
            vector = response.data[0].embedding
            # 追踪 embedding token
            usage = response.usage
            in_tokens = getattr(usage, "total_tokens", None) or getattr(usage, "prompt_tokens", None)
            in_cost, _ = self._estimate_cost(
                model=cfg.model_embedding,
                input_tokens=in_tokens,
                output_tokens=0,
            )
            self.trace_result(
                LLMResult(
                    content="",
                    input_tokens=in_tokens,
                    output_tokens=0,
                    input_cost_usd=in_cost,
                    output_cost_usd=0.0,
                    total_cost_usd=in_cost,
                ),
                stage="embed",
                model=cfg.model_embedding,
                prompt_digest=f"embed:{text[:80]}",
            )
            return [float(v) for v in vector]
        except Exception as exc:
            logger.warning("Embedding call failed: %s", exc)
            return None

    # ---------- Anthropic ----------

    def _call_anthropic(
        self,
        prompt: str,
        stage: str,
        cfg: LLMConfig,
        model_override: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        try:
            from anthropic import Anthropic

            model = self._resolve_model(
                stage, model_override, cfg
            )
            client = Anthropic(api_key=cfg.api_key)
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens or 4096,
                messages=[{"role": "user", "content": prompt}],
            )
            text_blocks: list[str] = []
            for block in response.content:
                if getattr(block, "type", "") == "text":
                    text_blocks.append(
                        getattr(block, "text", "")
                    )
            content = "\n".join(text_blocks).strip()
            usage = getattr(response, "usage", None)
            in_tokens = getattr(usage, "input_tokens", None)
            out_tokens = getattr(usage, "output_tokens", None)
            in_cost, out_cost = self._estimate_cost(
                model=model,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
            )
            return LLMResult(
                content=content,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                input_cost_usd=in_cost,
                output_cost_usd=out_cost,
                total_cost_usd=in_cost + out_cost,
            )
        except Exception:
            return self._pseudo_summary(
                prompt, stage, cfg, model_override
            )

    # ---------- Pseudo（无 API Key 回退）----------

    def _pseudo_summary(
        self,
        prompt: str,
        stage: str,
        cfg: LLMConfig,
        model_override: str | None = None,
    ) -> LLMResult:
        snippet = prompt[:800]
        model = self._resolve_model(
            stage, model_override, cfg
        )
        pseudo = (
            f"[{stage}] provider={cfg.provider}; "
            f"model={model}; "
            f"summary={snippet[:220]}"
        )
        in_tokens = len(prompt) // 4
        out_tokens = len(pseudo) // 4
        in_cost, out_cost = self._estimate_cost(
            model=model,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
        )
        return LLMResult(
            content=pseudo,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            input_cost_usd=in_cost,
            output_cost_usd=out_cost,
            total_cost_usd=in_cost + out_cost,
        )

    @staticmethod
    def _pseudo_embedding(
        text: str, dimensions: int = 1536
    ) -> list[float]:
        if not text:
            return [0.0] * dimensions
        vals = [0.0] * dimensions
        for idx, ch in enumerate(text.encode("utf-8")):
            vals[idx % dimensions] += float(ch) / 255.0
        scale = max(sum(v * v for v in vals) ** 0.5, 1e-6)
        return [v / scale for v in vals]

    # ---------- 工具 ----------

    @staticmethod
    def _try_parse_json(text: str) -> dict | None:
        raw = text.strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _estimate_cost(
        *,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> tuple[float, float]:
        model_lower = (model or "").lower()
        price_book: list[tuple[str, float, float]] = [
            # 顺序：更具体的模式放前面
            ("gpt-4.1-mini", 0.4, 1.6),
            ("gpt-4.1", 2.0, 8.0),
            ("gpt-4o-mini", 0.15, 0.6),
            ("gpt-4o", 2.5, 10.0),
            ("claude-3-haiku", 0.25, 1.25),
            ("claude-3-5-sonnet", 3.0, 15.0),
            ("glm-4.6v", 0.14, 0.14),
            ("glm-4.7", 0.1, 0.1),
            ("glm-4-flash", 0.01, 0.01),
            ("glm-4v", 0.14, 0.14),
            ("glm-4", 0.1, 0.1),
            ("embedding", 0.005, 0.0),
        ]
        in_million = 1.0
        out_million = 4.0
        for key, pin, pout in price_book:
            if key in model_lower:
                in_million = pin
                out_million = pout
                break
        in_t = input_tokens or 0
        out_t = output_tokens or 0
        in_cost = float(in_t) * in_million / 1_000_000.0
        out_cost = float(out_t) * out_million / 1_000_000.0
        return in_cost, out_cost

    def estimate_cost(
        self,
        *,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> tuple[float, float, float]:
        in_cost, out_cost = self._estimate_cost(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        return in_cost, out_cost, in_cost + out_cost
