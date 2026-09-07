"""Go Core Executor Protocol 的 Python 客户端（P0 lease 语义）。

协议契约（与 core/protocol.go 对齐）：
- 所有请求/响应为信封 {"schema_version", "correlation_id", "payload"}；
- correlation_id 由客户端生成（全链路追踪）；
- schema_version 不匹配时服务端返回 400，客户端抛 SchemaMismatchError；
- claim 返回的 lease_token 是 durable store 签发的 fencing 凭证，
  heartbeat/complete/fail/cancel_execution 必须原样带回。

Go Core 是控制面网关：这些调用最终落在 Python durable-state API
（/internal/durable/*）——权威状态只有一份（durable store）。
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

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _new_correlation_id() -> str:
    return uuid4().hex


class CoreClient:
    """Go Core 的同步协议客户端。"""

    def __init__(
        self,
        base_url: str,
        *,
        token: str = "",
        timeout_s: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self._base = base_url.rstrip("/")
        self._token = token
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = httpx.Client(timeout=timeout_s, transport=transport, headers=headers)

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
            with suppress(Exception):
                body = resp.json().get("body", {})
            if body.get("error") == "schema_version_mismatch":
                raise SchemaMismatchError(f"core 期望 schema_version={body.get('expected')}")
        if resp.status_code >= 400:
            with suppress(Exception):
                body = resp.json().get("body", {})
            raise CoreProtocolError(
                f"{path} → {resp.status_code}: {body}", status_code=resp.status_code
            )
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

    def heartbeat(self, executor_id: str, task_id: str, lease_token: str) -> dict[str, Any]:
        return self._call(
            f"/v1/tasks/{task_id}/heartbeat",
            {"executor_id": executor_id, "task_id": task_id, "lease_token": lease_token},
        )

    def progress(
        self,
        executor_id: str,
        task_id: str,
        lease_token: str,
        *,
        current: int,
        total: int,
        message: str = "",
    ) -> dict[str, Any]:
        """进度上报（聚合进度 + 续约 lease；fencing 校验 lease 持有者）"""
        return self._call(
            f"/v1/tasks/{task_id}/progress",
            {
                "executor_id": executor_id,
                "task_id": task_id,
                "lease_token": lease_token,
                "current": current,
                "total": total,
                "message": message,
            },
        )

    def submit_job(
        self,
        *,
        kind: str,
        capability: str,
        input_ref: dict[str, Any],
        idempotency_key: str | None = None,
        timeout_s: int = 1800,
        max_attempts: int = 3,
        resource_class: str = "default",
        priority: int = 0,
    ) -> dict[str, Any]:
        """Go-authority 任务提交（A 档 manifest 内）"""
        return self._call(
            "/v1/jobs",
            {
                "kind": kind,
                "capability": capability,
                "input_ref": input_ref,
                "idempotency_key": idempotency_key or "",
                "timeout_s": timeout_s,
                "max_attempts": max_attempts,
                "resource_class": resource_class,
                "priority": priority,
            },
        )

    def jobs_graph(self, job_id: str) -> dict[str, Any] | None:
        """Go 权威 Job graph（观察面代理）；404 返回 None"""
        try:
            resp = self._client.get(f"{self._base}/v1/jobs/{job_id}")
        except Exception:
            return None
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            return None
        return resp.json()

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        """Go 权威 Job 取消"""
        return self._call(f"/v1/jobs/{job_id}/cancel", {})

    def jobs_list(self, limit: int = 20) -> list[dict[str, Any]]:
        """Go 权威 Job 列表（观察面合并）"""
        try:
            resp = self._client.get(f"{self._base}/v1/jobs?limit={limit}")
        except Exception:
            return []
        if resp.status_code >= 400:
            return []
        return resp.json().get("items", [])

    def domain_result(self, task_id: str) -> dict[str, Any]:
        """幂等卫兵：查同 Job 内同 capability+input 的既有成功领域结果"""
        resp = self._client.get(f"{self._base}/v1/tasks/{task_id}/domain-result")
        if resp.status_code >= 400:
            raise CoreProtocolError(
                f"domain-result → {resp.status_code}", status_code=resp.status_code
            )
        return resp.json().get("body", {})

    def complete(
        self,
        executor_id: str,
        task_id: str,
        lease_token: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        return self._call(
            f"/v1/tasks/{task_id}/complete",
            {
                "executor_id": executor_id,
                "task_id": task_id,
                "lease_token": lease_token,
                "result": result,
            },
        )

    def fail(
        self,
        executor_id: str,
        task_id: str,
        lease_token: str,
        *,
        error_class: str,
        message: str,
    ) -> dict[str, Any]:
        return self._call(
            f"/v1/tasks/{task_id}/fail",
            {
                "executor_id": executor_id,
                "task_id": task_id,
                "lease_token": lease_token,
                "error_class": error_class,
                "message": message,
            },
        )

    def cancel_execution(self, executor_id: str, task_id: str, lease_token: str) -> dict[str, Any]:
        """协作取消的完成回执：安全点退出后把 Task/Attempt 标记 cancelled（不重试）"""
        return self._call(
            f"/v1/tasks/{task_id}/cancel-execution",
            {
                "executor_id": executor_id,
                "task_id": task_id,
                "lease_token": lease_token,
            },
        )

    def cancel(self, task_id: str, *, reason: str = "") -> dict[str, Any]:
        """控制面取消（queued→直接取消；leased→协作取消标记）"""
        return self._call(
            f"/v1/tasks/{task_id}/cancel",
            {"task_id": task_id, "reason": reason},
        )
