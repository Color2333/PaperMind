"""Python Executor 运行时（C7；P0 修复后走 durable lease 语义）

经 Go Core 协议（packages.core_client）领取 Task、执行 C4 注册表的 handler、
心跳续约 lease、提交 complete/fail/cancel-execution。Go Core 是控制面网关——
lease 由 durable store 签发（claim 响应携带 lease_token），fencing 校验在
durable store 落地；Executor 不得绕过 Go 直接访问状态。

- 每次只执行一个 Task Attempt（领取 → 心跳线程续约 → handler → 提交）；
- 协作取消：心跳响应 cancel_requested=true 时设置标志，handler 在安全检查点
  检查 `should_cancel()` 后提前退出，经 cancel-execution 回执（不重试）；
- drain：停止领取新 Task，允许当前 Attempt 收敛；
- handler 解析 C4 注册表的 dotted path；注入 `input`（Task.input_ref）与
  `cancel_check`（取消探测回调）。
"""

from __future__ import annotations

import importlib
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from packages.core_client.client import CoreClient

logger = logging.getLogger(__name__)


class TaskCancelledError(RuntimeError):
    """handler 在安全检查点因协作取消而退出"""


def resolve_handler(dotted: str) -> Callable[..., Any]:
    """解析 "package.module:attr.sub" 形式的 handler 引用"""
    module_path, symbol = dotted.split(":", 1)
    obj: Any = importlib.import_module(module_path)
    for part in symbol.split("."):
        obj = getattr(obj, part)
    return obj  # type: ignore[no-any-return]


@dataclass
class ExecutorConfig:
    executor_id: str
    capabilities: list[str]  # 领取的 capability 名
    poll_interval_s: float = 2.0
    heartbeat_interval_s: float = 60.0
    idle_exit_after_s: float | None = None  # 测试用：空闲 N 秒后退出


@dataclass
class _RunState:
    task_id: str
    attempt_id: str
    lease_token: str | None
    cancel_event: threading.Event = field(default_factory=threading.Event)


class ExecutorRunner:
    """单线程 Executor 循环（C7；多实例水平扩展在部署层）"""

    def __init__(
        self,
        *,
        client: CoreClient,
        config: ExecutorConfig,
        handlers: dict[str, Callable[..., Any]],
    ) -> None:
        self.client = client
        self.config = config
        self.handlers = handlers
        self._drain = threading.Event()
        self._stopped = threading.Event()
        self._current: _RunState | None = None

    # ---------- 对外控制 ----------

    def drain(self) -> None:
        """停止领取新 Task；当前 Attempt 收敛后循环退出"""
        self._drain.set()

    def wait_stopped(self, timeout: float | None = None) -> bool:
        return self._stopped.wait(timeout)

    def should_cancel(self) -> bool:
        """handler 在安全检查点调用：协作取消探测"""
        return self._current is not None and self._current.cancel_event.is_set()

    # ---------- 循环 ----------

    def _ensure_registered(self) -> bool:
        """向 Go Core 注册能力声明（幂等；失败重试到 drain）"""
        from packages.application.commands.task_registry import TASK_CAPABILITIES

        caps: list[dict[str, Any]] = []
        for name in self.config.capabilities:
            spec = TASK_CAPABILITIES.get(name)
            caps.append(
                {
                    "name": name,
                    "version": 1,
                    "resource_class": spec.resource_class if spec else "default",
                }
            )
        for _attempt in range(30):
            if self._drain.is_set():
                return False
            try:
                self.client.register(self.config.executor_id, caps)
                return True
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "register 失败（%.1fs 后重试）: %s", self.config.poll_interval_s, exc
                )
                time.sleep(self.config.poll_interval_s)
        return False

    def run_forever(self) -> None:
        if not self._ensure_registered():
            self._stopped.set()
            return
        idle_since: float | None = None
        while not self._drain.is_set():
            task = None
            try:
                task = self.client.claim(self.config.executor_id, self.config.capabilities)
            except Exception as exc:  # noqa: BLE001
                # Go Core 重启后注册态丢失（403）——重新注册后继续（P0 恢复路径）
                status = getattr(exc, "status_code", None)
                if status == 403:
                    logger.warning("claim 被拒（403）→ 重新注册")
                    self._ensure_registered()
            if task is None:
                if idle_since is None:
                    idle_since = time.monotonic()
                if (
                    self.config.idle_exit_after_s is not None
                    and time.monotonic() - idle_since > self.config.idle_exit_after_s
                ):
                    break
                time.sleep(self.config.poll_interval_s)
                continue
            idle_since = None
            self._execute(task)

        # drain 后等当前 Attempt 收敛（单线程循环内已串行——此处仅为语义完整）
        self._stopped.set()
        logger.info("Executor %s 已停止", self.config.executor_id)

    def run_in_thread(self) -> threading.Thread:
        t = threading.Thread(target=self.run_forever, name=f"executor-{self.config.executor_id}")
        t.start()
        return t

    # ---------- 单次 Attempt ----------

    def _execute(self, task: dict[str, Any]) -> None:
        task_id = task["task_id"]
        attempt_id = task["attempt_id"]
        capability = task["capability"]
        lease_token = task.get("lease_token") or ""
        handler = self.handlers.get(capability)
        state = _RunState(task_id=task_id, attempt_id=attempt_id, lease_token=lease_token)
        self._current = state
        try:
            if handler is None:
                logger.error("capability %s 无 handler，上报失败", capability)
                self.client.fail(
                    self.config.executor_id,
                    task_id,
                    lease_token,
                    error_class="no_handler",
                    message=f"capability {capability} 未注册 handler",
                )
                return

            hb_stop = threading.Event()
            hb_thread = threading.Thread(
                target=self._heartbeat_loop, args=(task_id, lease_token, hb_stop), daemon=True
            )
            hb_thread.start()
            try:
                input_ref = task.get("input") or {}
                result = handler(input=input_ref, cancel_check=self.should_cancel)
            except TaskCancelledError:
                logger.info("task %s 协作取消退出（安全点）", task_id)
                self.client.cancel_execution(self.config.executor_id, task_id, lease_token)
                return
            except Exception as exc:  # noqa: BLE001
                logger.exception("task %s handler 失败", task_id)
                self._submit_with_retry(
                    lambda exc=exc: self.client.fail(
                        self.config.executor_id,
                        task_id,
                        lease_token,
                        error_class=type(exc).__name__,
                        message=str(exc),
                    ),
                    task_id=task_id,
                    action="fail",
                )
                return
            finally:
                hb_stop.set()
                hb_thread.join(timeout=5)

            if self.should_cancel():
                # 协作取消：handler 已安全退出，回执 cancelled（不重试）
                self.client.cancel_execution(self.config.executor_id, task_id, lease_token)
                return

            # P1 修复：complete 失败不可吞——记录并重试；副作用已发生但结果未知时留日志
            self._submit_with_retry(
                lambda: self.client.complete(
                    self.config.executor_id, task_id, lease_token, result=_jsonable(result)
                ),
                task_id=task_id,
                action="complete",
            )
        finally:
            self._current = None

    def _submit_with_retry(
        self, submit: Callable[[], Any], *, task_id: str, action: str, retries: int = 3
    ) -> None:
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                submit()
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(1 << attempt)
        logger.error(
            "task %s %s %d 次均失败（执行已发生，回执未落地——靠 lease 过期回收兜底）: %s",
            task_id,
            action,
            retries,
            last_exc,
        )

    def _heartbeat_loop(self, task_id: str, lease_token: str, stop: threading.Event) -> None:
        interval = max(self.config.heartbeat_interval_s, 1.0)
        while not stop.wait(interval):
            try:
                resp = self.client.heartbeat(self.config.executor_id, task_id, lease_token)
                if resp.get("cancel_requested") and self._current is not None:
                    self._current.cancel_event.set()
                    logger.info("task %s 收到取消请求", task_id)
            except Exception as exc:
                logger.warning("heartbeat 失败（续期重试于下轮）: %s", exc)


def _jsonable(result: Any) -> dict[str, Any]:
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


def handlers_from_registry(
    capability_names: list[str], **bindings: Any
) -> dict[str, Callable[..., Any]]:
    """按 C4 注册表解析 handler，并注入绑定参数（如 ClaimExtractionService 实例）。

    handler 调用约定：fn(input: dict, cancel_check: Callable[[], bool]) -> Any
    """
    from packages.application.commands.task_registry import TASK_CAPABILITIES

    out: dict[str, Callable[..., Any]] = {}
    for name in capability_names:
        spec = TASK_CAPABILITIES[name]
        fn = resolve_handler(spec.handler)
        out[name] = _adapt(fn, **bindings)
    return out


def _bind_method(fn: Callable[..., Any]) -> Callable[..., Any]:
    """注册表 handler 可能是未绑定的类方法（如 PaperPipelines.skim）——实例化后绑定。

    已绑定（模块级函数/实例方法）原样返回。
    """
    if getattr(fn, "__self__", None) is not None:
        return fn
    qual = getattr(fn, "__qualname__", "") or ""
    if "." not in qual:
        return fn
    import importlib as _importlib

    mod = _importlib.import_module(fn.__module__)
    owner = getattr(mod, qual.split(".")[0])
    return getattr(owner(), fn.__name__)


def _adapt(fn: Callable[..., Any], **bindings: Any) -> Callable[..., Any]:
    """把注册表 handler 适配为 fn(input, cancel_check) 约定。

    已知 handler 的入参映射在此集中维护；新增 capability 在此登记。
    """
    fn = _bind_method(fn)

    def _call_paper_pipeline(input: dict, cancel_check: Callable[[], bool]) -> Any:  # noqa: ARG001
        paper_id = input["paper_id"]
        from uuid import UUID

        return fn(UUID(paper_id))

    def _call_service_with_kwargs(input: dict, cancel_check: Callable[[], bool]) -> Any:  # noqa: ARG001
        return fn(**input)

    mod = getattr(fn, "__module__", "") or ""
    if "paper_pipelines" in mod and "extract" not in (getattr(fn, "__name__", "") or ""):
        return _call_paper_pipeline
    if "claim_extractor" in mod:
        return lambda input, cancel_check: fn(
            input["paper_id"], source_text=input.get("source_text")
        )
    return _call_service_with_kwargs
