"""Inline test executor（C3 退出口的测试支撑）

生产执行路径是 Go Core 调度的独立 Executor（P0 闭环）。本模块仅供测试：
与 runner 共用 C4 handler 解析与 durable 仓储 fencing 语义，但不经 Go Core，
直接在测试进程内 claim/complete——使提交式命令（start_skim/daily/…）的
pytest 可以同步推进任务。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


class InlineExecutor:
    """直接驱动 durable store 的测试执行器（非生产路径）"""

    def __init__(
        self,
        capabilities: list[str] | None = None,
        executor_id: str = "inline-exec",
        handler_overrides: dict[str, Callable[..., Any]] | None = None,
    ) -> None:
        from packages.application.commands.task_registry import TASK_CAPABILITIES
        from packages.executor_runtime.runner import handlers_from_registry

        self.capabilities = capabilities or [
            name for name, spec in TASK_CAPABILITIES.items() if not spec.manual_recovery
        ]
        self.executor_id = executor_id
        self.handlers = handlers_from_registry(self.capabilities)
        if handler_overrides:
            self.handlers.update(handler_overrides)
        self._handler_overrides = handler_overrides or {}

    def run_until_idle(self, timeout: float = 60.0) -> int:
        """处理所有当前 queued 任务直到无剩余；返回处理数"""
        from packages.storage.db import session_scope
        from packages.storage.repositories import TaskRepository

        processed = 0
        import time as _time

        deadline = _time.monotonic() + timeout
        while _time.monotonic() < deadline:
            claimed = None
            with session_scope() as session:
                claimed = TaskRepository(session).claim_task(
                    executor_id=self.executor_id, capabilities=self.capabilities
                )
                if claimed is None:
                    break
                task_id = claimed.id
                capability = claimed.capability
                lease_token = claimed.lease_token
                input_ref = dict(claimed.input_ref or {})

            handler = self.handlers.get(capability)
            try:
                if handler is None:
                    raise KeyError(f"capability {capability} 未注册 handler")
                result = handler(input=input_ref, cancel_check=lambda: False, progress=None)
                json_result = _jsonable(result)
                with session_scope() as session:
                    # proposal 模式（skim 等）：领域 apply 与 Task 终态同事务提交
                    # （与 durable-state /complete 的权威语义一致）
                    stored_ref = json_result
                    proposal = (json_result or {}).get("proposal") or {}
                    kind = proposal.get("kind")
                    if kind == "skim_paper":
                        from packages.application.commands.domain_apply import (
                            apply_prompt_trace,
                            apply_skim_proposal,
                        )

                        apply_skim_proposal(session, proposal)
                        apply_prompt_trace(session, proposal)
                        stored_ref = proposal.get("skim") or json_result
                    elif kind == "deep_read_paper":
                        from packages.application.commands.domain_apply import (
                            apply_deep_read_proposal,
                            apply_prompt_trace,
                        )

                        apply_deep_read_proposal(session, proposal)
                        apply_prompt_trace(session, proposal)
                        stored_ref = proposal.get("deep") or json_result
                    elif kind == "embed_paper":
                        from packages.application.commands.domain_apply import apply_embed_proposal

                        apply_embed_proposal(session, proposal)
                        stored_ref = {"embedded": True}
                    elif kind == "extract_claims":
                        from packages.application.commands.domain_apply import (
                            apply_extract_claims_proposal,
                            apply_prompt_trace,
                        )

                        stats = apply_extract_claims_proposal(session, proposal)
                        apply_prompt_trace(session, proposal)
                        stored_ref = stats or json_result
                    TaskRepository(session).complete_task(
                        task_id=task_id,
                        executor_id=self.executor_id,
                        lease_token=lease_token,
                        result_ref=stored_ref,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("inline executor: task %s failed: %s", task_id[:8], exc)
                with session_scope() as session:
                    task = TaskRepository(session).get(task_id)
                    if task.lease_token == lease_token:
                        TaskRepository(session).fail_task(
                            task_id=task_id,
                            executor_id=self.executor_id,
                            lease_token=lease_token,
                            error_class=type(exc).__name__,
                            message=str(exc),
                        )
            processed += 1
        return processed

    def run_while(self, predicate: Callable[[], bool], timeout: float = 60.0) -> int:
        """predicate 为真期间持续处理（如「任务未完成」）"""
        processed = 0
        import time as _time

        deadline = _time.monotonic() + timeout
        while predicate() and _time.monotonic() < deadline:
            n = self.run_until_idle(timeout=1.0)
            if n == 0:
                _time.sleep(0.05)
            processed += n
        return processed


def _jsonable(result: Any) -> dict:
    if result is None:
        return {}
    dump = getattr(result, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except Exception:  # noqa: BLE001
            pass
    if isinstance(result, dict):
        return result
    return {"repr": str(result)[:500]}
