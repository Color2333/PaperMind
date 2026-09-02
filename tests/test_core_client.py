"""C0：Python Executor Protocol 客户端契约测试（hermetic——fake core 走 httpx MockTransport）"""

from __future__ import annotations

import json

import httpx
import pytest

from packages.core_client.client import (
    SCHEMA_VERSION,
    CoreClient,
    CoreProtocolError,
    SchemaMismatchError,
)


def _fake_core(handler):
    transport = httpx.MockTransport(handler)
    return CoreClient("http://core.test", transport=transport)


def _echo_envelope(request: httpx.Request, body: dict, *, status: int = 200) -> httpx.Response:
    """回显请求方 correlation_id（协议要求服务端原样返回）"""
    cid = json.loads(request.content)["correlation_id"]
    return httpx.Response(
        status, json={"schema_version": SCHEMA_VERSION, "correlation_id": cid, "body": body}
    )


def test_health_and_register_roundtrip():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(
                200,
                json={
                    "schema_version": 1,
                    "correlation_id": "",
                    "body": {"status": "ok", "core_version": "0.1.0-c0"},
                },
            )
        seen["path"] = request.url.path
        seen["envelope"] = json.loads(request.content)
        return _echo_envelope(request, {"ok": True, "executor_id": "py-1"})

    with _fake_core(handler) as client:
        health = client.health()
        assert health["status"] == "ok"
        result = client.register(
            "py-1", [{"name": "fake_cap", "version": 1, "resource_class": "default"}]
        )

    assert result["ok"] is True
    # 契约：信封带 schema_version + correlation_id（客户端生成、服务端回显）
    assert seen["envelope"]["schema_version"] == SCHEMA_VERSION
    assert seen["path"] == "/v1/executors/register"


def test_full_executor_cycle_with_fake_core():
    """fake core 上的完整执行周期：register → claim → heartbeat → complete"""
    state = {"task_id": "task_abc", "attempt_id": "att_1", "claimed": False}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/tasks/claim":
            if state["claimed"]:
                return _echo_envelope(request, {"ok": True, "task": None})
            state["claimed"] = True
            return _echo_envelope(
                request,
                {
                    "ok": True,
                    "task": {
                        "task_id": state["task_id"],
                        "attempt_id": state["attempt_id"],
                        "capability": "fake_cap",
                        "input": {"prompt": "hello"},
                        "resource_class": "default",
                        "timeout_s": 60,
                        "cancel_requested": False,
                    },
                },
            )
        if path.endswith("/heartbeat"):
            return _echo_envelope(request, {"ok": True, "cancel_requested": False})
        if path.endswith("/complete"):
            return _echo_envelope(request, {"ok": True, "status": "done"})
        return _echo_envelope(request, {"ok": True})

    with _fake_core(handler) as client:
        assert client.claim("py-1", ["fake_cap"]) is not None  # 第一次领取到任务
        assert client.claim("py-1", ["fake_cap"]) is None  # 之后为空
        hb = client.heartbeat("py-1", state["task_id"], state["attempt_id"])
        assert hb["cancel_requested"] is False
        done = client.complete("py-1", state["task_id"], state["attempt_id"], {"output": "done"})
        assert done["status"] == "done"


def test_fail_requests_retry():
    def handler(request: httpx.Request) -> httpx.Response:
        return _echo_envelope(
            request, {"ok": True, "retry_scheduled": True, "attempt_recorded": True}
        )

    with _fake_core(handler) as client:
        result = client.fail("py-1", "task_1", "att_1", error_class="network", message="boom")
    assert result["retry_scheduled"] is True


def test_schema_mismatch_raises_typed_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "schema_version": 1,
                "correlation_id": json.loads(request.content)["correlation_id"],
                "body": {"ok": False, "error": "schema_version_mismatch", "expected": 2},
            },
        )

    with _fake_core(handler) as client, pytest.raises(SchemaMismatchError):
        client.register("py-1", [])


def test_protocol_error_on_4xx_and_correlation_echo():
    def handler(request: httpx.Request) -> httpx.Response:
        cid = json.loads(request.content)["correlation_id"]
        if cid != "fixed-cid":
            raise AssertionError("客户端应使用传入的 correlation_id")
        return _echo_envelope(request, {"ok": False, "error": "complete_rejected"}, status=409)

    with (
        _fake_core(handler) as client,
        pytest.raises(CoreProtocolError, match="complete_rejected"),
    ):
        client._call("/v1/tasks/t1/complete", {"executor_id": "ghost"}, correlation_id="fixed-cid")
