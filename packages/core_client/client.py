"""Go Core Executor Protocol 的 Python 客户端（Stage C0）。

协议契约（与 core/protocol.go 对齐）：
- 所有请求/响应为信封 {"schema_version", "correlation_id", "payload"}；
- correlation_id 由客户端生成（全链路追踪）；
- schema_version 不匹配时服务端返回 400，客户端抛 SchemaMismatchError。

C0 阶段仅覆盖协议面（register/claim/heartbeat/complete/fail/cancel + health）；
执行循环、lease 续约策略与失败退避在 C7 落地。
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any
from uuid import uuid4

import httpx

SCHEMA_VERSION = 1  # 与 core/protocol.go SchemaVersion 保持一致


class SchemaMismatchError(RuntimeError):
    """Core 返回 schema_version_mismatch——客户端与服务端协议版本不一致"""


class CoreProtocolError(RuntimeError):
    """Core 拒绝了协议请求（4xx/409 等）"""


def _new_correlation_id() -> str:
    return uuid4().hex


class CoreClient:
    """Go Core 的同步协议客户端。"""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self._base = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout_s, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> CoreClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ---------- 低层 ----------

    def _call(
        self, path: str, payload: dict[str, Any], correlation_id: str | None = None
    ) -> dict[str, Any]:
        cid = correlation_id or _new_correlation_id()
        envelope = {"schema_version": SCHEMA_VERSION, "correlation_id": cid, "payload": payload}
        resp = self._client.post(f"{self._base}{path}", json=envelope)
        if resp.status_code == 400:
            body = resp.json().get("body", {})
            if body.get("error") == "schema_version_mismatch":
                raise SchemaMismatchError(f"core 期望 schema_version={body.get('expected')}")
        if resp.status_code >= 400:
            with suppress(Exception):
                body = resp.json().get("body", {})
            raise CoreProtocolError(f"{path} → {resp.status_code}: {body}")
        envelope_out = resp.json()
        if envelope_out.get("correlation_id") != cid:
            raise CoreProtocolError("correlation_id 未回显")
        return envelope_out.get("body", {})

    # ---------- 协议动作 ----------

    def health(self) -> dict[str, Any]:
        resp = self._client.get(f"{self._base}/health")
        resp.raise_for_status()
        return resp.json().get("body", {})

    def register(self, executor_id: str, capabilities: list[dict[str, Any]]) -> dict[str, Any]:
        return self._call(
            "/v1/executors/register",
            {"executor_id": executor_id, "capabilities": capabilities},
        )

    def claim(self, executor_id: str, capabilities: list[str]) -> dict[str, Any] | None:
        body = self._call(
            "/v1/tasks/claim",
            {"executor_id": executor_id, "capabilities": capabilities},
        )
        return body.get("task")

    def heartbeat(self, executor_id: str, task_id: str, attempt_id: str) -> dict[str, Any]:
        return self._call(
            f"/v1/tasks/{task_id}/heartbeat",
            {"executor_id": executor_id, "task_id": task_id, "attempt_id": attempt_id},
        )

    def complete(
        self, executor_id: str, task_id: str, attempt_id: str, result: dict[str, Any]
    ) -> dict[str, Any]:
        return self._call(
            f"/v1/tasks/{task_id}/complete",
            {
                "executor_id": executor_id,
                "task_id": task_id,
                "attempt_id": attempt_id,
                "result": result,
            },
        )

    def fail(
        self, executor_id: str, task_id: str, attempt_id: str, *, error_class: str, message: str
    ) -> dict[str, Any]:
        return self._call(
            f"/v1/tasks/{task_id}/fail",
            {
                "executor_id": executor_id,
                "task_id": task_id,
                "attempt_id": attempt_id,
                "error_class": error_class,
                "message": message,
            },
        )

    def cancel(self, task_id: str, *, reason: str = "") -> dict[str, Any]:
        return self._call(
            f"/v1/tasks/{task_id}/cancel",
            {"task_id": task_id, "reason": reason},
        )
