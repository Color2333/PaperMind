"""
LLM 提供者抽象层 - OpenAI / Anthropic / ZhipuAI / Pseudo
支持从数据库动态加载激活的 LLM 配置
@author Bamzc
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from packages.config import get_settings

logger = logging.getLogger(__name__)


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


def _load_active_config() -> LLMConfig:
    """从数据库加载激活的 LLM 配置，无则用 .env 默认"""
    settings = get_settings()
    try:
        from packages.storage.db import session_scope
        from packages.storage.repositories import (
            LLMConfigRepository,
        )

        with session_scope() as session:
            active = LLMConfigRepository(session).get_active()
            if active:
                return LLMConfig(
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

    # 根据 provider 选择对应的 api_key
    api_key = None
    base_url = None
    if settings.llm_provider == "zhipu":
        api_key = settings.zhipu_api_key
        base_url = "https://open.bigmodel.cn/api/paas/v4/"
    elif settings.llm_provider == "openai":
        api_key = settings.openai_api_key
    elif settings.llm_provider == "anthropic":
        api_key = settings.anthropic_api_key

    return LLMConfig(
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


# 预置的 provider → base_url 映射
PROVIDER_BASE_URLS: dict[str, str] = {
    "zhipu": "https://open.bigmodel.cn/api/paas/v4/",
    "openai": "https://api.openai.com/v1",
    "anthropic": "",
}


class LLMClient:
    """
    统一 LLM 调用客户端。
    每次调用动态读取当前激活配置。
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

    # ---------- 公开 API ----------

    def summarize_text(
        self,
        prompt: str,
        stage: str,
        model_override: str | None = None,
    ) -> LLMResult:
        cfg = self._config()
        if cfg.provider in ("openai", "zhipu") and cfg.api_key:
            return self._call_openai_compatible(
                prompt, stage, cfg, model_override
            )
        if cfg.provider == "anthropic" and cfg.api_key:
            return self._call_anthropic(
                prompt, stage, cfg, model_override
            )
        return self._pseudo_summary(
            prompt, stage, cfg, model_override
        )

    def complete_json(
        self,
        prompt: str,
        stage: str,
        model_override: str | None = None,
    ) -> LLMResult:
        wrapped = (
            "请只输出单个 JSON 对象，"
            "不要输出 markdown，不要输出额外解释。\n"
            "如果信息不足，请根据上下文给出最合理的保守估计，"
            "并保持 JSON 结构完整。\n\n"
            f"{prompt}"
        )
        result = self.summarize_text(
            wrapped, stage=stage, model_override=model_override
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

    def embed_text(
        self, text: str, dimensions: int = 1536
    ) -> list[float]:
        cfg = self._config()
        if cfg.provider in ("openai", "zhipu") and cfg.api_key:
            maybe = self._embed_openai_compatible(text, cfg)
            if maybe:
                return maybe
        return self._pseudo_embedding(text, dimensions)

    # ---------- OpenAI 兼容调用（OpenAI / 智谱）----------

    def _call_openai_compatible(
        self,
        prompt: str,
        stage: str,
        cfg: LLMConfig,
        model_override: str | None = None,
    ) -> LLMResult:
        try:
            from openai import OpenAI

            model = self._resolve_model(
                stage, model_override, cfg
            )
            base_url = self._resolve_base_url(cfg)
            client = OpenAI(
                api_key=cfg.api_key, base_url=base_url
            )
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.choices[0].message.content or ""
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
            from openai import OpenAI

            base_url = self._resolve_base_url(cfg)
            client = OpenAI(
                api_key=cfg.api_key, base_url=base_url
            )
            response = client.embeddings.create(
                model=cfg.model_embedding, input=text
            )
            vector = response.data[0].embedding
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
    ) -> LLMResult:
        try:
            from anthropic import Anthropic

            model = self._resolve_model(
                stage, model_override, cfg
            )
            client = Anthropic(api_key=cfg.api_key)
            response = client.messages.create(
                model=model,
                max_tokens=1500,
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
            ("gpt-4.1", 2.0, 8.0),
            ("gpt-4o-mini", 0.15, 0.6),
            ("claude-3-haiku", 0.25, 1.25),
            ("claude-3-5-sonnet", 3.0, 15.0),
            ("glm-4", 0.1, 0.1),
            ("glm-4v", 0.15, 0.15),
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
