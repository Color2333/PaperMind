"""独立 Python Executor 进程（P0 闭环的执行载体）。

用法：
    python -m apps.executor \
        --core-url http://127.0.0.1:8081 \
        --core-token "$CORE_TOKEN" \
        --capabilities skim_paper,deep_read_paper \
        [--executor-id exec-1] [--idle-exit-after 10] \
        [--fake-llm] [--handler-delay-s 30]

- claim/heartbeat/complete/fail 全部经 Go Core（控制面网关）；
- handler 来自 C4 注册表（TASK_CAPABILITIES）；
- SIGTERM/SIGINT → drain（停止领取，当前 Attempt 收敛后退出）。

测试钩子（故障注入实验专用，生产禁用）：
- --fake-llm：类级 patch LLMClient，确定性返回（无 API key 也能跑通真实 pipeline）；
- --handler-delay-s N：所有 handler 前插入 N 秒慢阶段，期间探测协作取消
  （cancel_check 置位则抛 TaskCancelledError——模拟安全点退出）。

环境：DATABASE_URL 决定 durable store（经 packages.config 读取，与 API 同库）。
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from packages.executor_runtime.runner import TaskCancelledError


def _install_fake_llm() -> None:
    """类级 patch：LLMClient.summarize_text/embed_text → 确定性 fake（同 e2e 契约）"""
    import json

    from packages.integrations.llm_client import LLMClient, LLMResult

    fake_payloads = {
        "skim": {
            "one_liner": "提出基于 transformer 的流式说话人分离方法，在 LibriSpeech 上相对降低 DER 12%。",
            "innovations": ["流式 transformer 分离架构", "多通道特征融合"],
            "keywords": ["speaker diarization", "transformer", "streaming"],
            "title_zh": "基于Transformer的流式说话人分离",
            "abstract_zh": "本文提出一种流式 transformer 说话人分离方法，并验证多通道融合带来的增益。",
            "relevance_score": 0.9,
        },
        "deep": {
            "method_summary": "Method: streaming transformer diarization.",
            "experiments_summary": "Experiments: 12% relative DER reduction.",
            "ablation_summary": "Ablation: each module contributes gains.",
            "reviewer_risks": ["Generalization under-validated."],
        },
        "claim_extraction": {"claims": []},
    }

    def _fake_summarize_text(
        self,
        prompt: str,
        stage: str,
        model_override: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:  # noqa: ARG001
        payload = fake_payloads.get(stage, {"answer": "[fake-rag-answer]"})
        return LLMResult(
            content=json.dumps(payload, ensure_ascii=False),
            parsed_json=payload,
            input_tokens=64,
            output_tokens=32,
            input_cost_usd=0.0,
            output_cost_usd=0.0,
            total_cost_usd=0.0,
        )

    def _fake_embed_text(self, text: str, dimensions: int = 1536) -> list[float]:  # noqa: ARG001
        return [0.01] * dimensions

    LLMClient.summarize_text = _fake_summarize_text  # type: ignore[method-assign]
    LLMClient.embed_text = _fake_embed_text  # type: ignore[method-assign]
    logging.getLogger(__name__).warning("fake-llm 已启用（测试钩子，生产禁用）")


def _wrap_with_delay(handlers: dict, delay_s: float) -> dict:
    """给每个 handler 前插入慢阶段（故障注入用），期间探测协作取消。

    包装器在调用时再解析 cancel_check 注入（runner 传入），无需反向引用 runner。
    """

    def _wrap(fn):
        def _call(input: dict, cancel_check) -> object:  # noqa: ANN001
            deadline = time.monotonic() + delay_s
            while time.monotonic() < deadline:
                if cancel_check():
                    raise TaskCancelledError("协作取消（handler-delay 安全点）")
                time.sleep(0.2)
            return fn(input=input, cancel_check=cancel_check)

        return _call

    return {name: _wrap(fn) for name, fn in handlers.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PaperMind durable executor")
    parser.add_argument("--core-url", default="http://127.0.0.1:8081")
    parser.add_argument("--core-token", default="")
    parser.add_argument("--executor-id", default="exec-1")
    parser.add_argument("--capabilities", default="skim_paper")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--heartbeat-interval", type=float, default=5.0)
    parser.add_argument("--idle-exit-after", type=float, default=None)
    parser.add_argument("--fake-llm", action="store_true", help="测试钩子：确定性 LLM")
    parser.add_argument("--handler-delay-s", type=float, default=0.0, help="测试钩子：慢 handler")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if args.fake_llm:
        _install_fake_llm()

    from packages.core_client.client import CoreClient
    from packages.executor_runtime.runner import (
        ExecutorConfig,
        ExecutorRunner,
        handlers_from_registry,
    )

    capabilities = [c.strip() for c in args.capabilities.split(",") if c.strip()]
    handlers = handlers_from_registry(capabilities)

    client = CoreClient(args.core_url, token=args.core_token)
    runner = ExecutorRunner(
        client=client,
        config=ExecutorConfig(
            executor_id=args.executor_id,
            capabilities=capabilities,
            poll_interval_s=args.poll_interval,
            heartbeat_interval_s=args.heartbeat_interval,
            idle_exit_after_s=args.idle_exit_after,
        ),
        handlers=handlers,
    )
    if args.handler_delay_s > 0:
        runner.handlers = _wrap_with_delay(handlers, args.handler_delay_s)

    def _graceful(_sig, _frame) -> None:  # noqa: ANN001
        logging.getLogger(__name__).info("收到退出信号 → drain")
        runner.drain()

    signal.signal(signal.SIGTERM, _graceful)
    signal.signal(signal.SIGINT, _graceful)

    runner.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
