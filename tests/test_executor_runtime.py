"""C7：Python Executor 运行时测试（hermetic——fake Core 走 httpx MockTransport）

覆盖：完整执行周期（claim→handler→complete）、handler 异常→fail、
心跳响应 cancel_requested→协作取消、drain 停止领取、capability 无 handler→fail(no_handler)。
"""

from __future__ import annotations

import json
import threading
import time

import httpx

from packages.core_client.client import CoreClient
from packages.executor_runtime.runner import ExecutorConfig, ExecutorRunner


class FakeCore:
    """内存 fake Core：按脚本回放协议响应"""

    def __init__(self, tasks: list[dict], *, cancel_on_heartbeat: bool = False):
        self.tasks = list(tasks)
        self.claimed: list[dict] = []
        self.completed: list[dict] = []
        self.failed: list[dict] = []
        self.cancel_on_heartbeat = cancel_on_heartbeat

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        cid = json.loads(request.content)["correlation_id"] if request.content else ""

        def env(body: dict, status: int = 200) -> httpx.Response:
            return httpx.Response(
                status, json={"schema_version": 1, "correlation_id": cid, "body": body}
            )

        if path == "/v1/tasks/claim":
            if self.tasks and not self._drained():
                task = self.tasks.pop(0)
                self.claimed.append(task)
                return env({"ok": True, "task": task})
            return env({"ok": True, "task": None})
        if path.endswith("/heartbeat"):
            return env({"ok": True, "cancel_requested": self.cancel_on_heartbeat})
        if path.endswith("/complete"):
            self.completed.append(json.loads(request.content)["payload"])
            return env({"ok": True, "status": "done"})
        if path.endswith("/fail"):
            self.failed.append(json.loads(request.content)["payload"])
            return env({"ok": True, "retry_scheduled": True, "attempt_recorded": True})
        return env({"ok": True})

    def _drained(self) -> bool:
        return False


def _make_runner(fake: FakeCore, handlers: dict, **cfg) -> tuple[ExecutorRunner, ExecutorConfig]:
    transport = httpx.MockTransport(fake.handler)
    client = CoreClient("http://core.test", transport=transport)
    defaults = {"poll_interval_s": 0.05, "heartbeat_interval_s": 0.05}
    defaults.update(cfg)
    config = ExecutorConfig(executor_id="py-test", capabilities=["fake_cap"], **defaults)
    return ExecutorRunner(client=client, config=config, handlers=handlers), config


def _task(task_id: str, capability: str = "fake_cap") -> dict:
    return {
        "task_id": task_id,
        "attempt_id": f"att_{task_id}",
        "capability": capability,
        "input": {"paper_id": "p1"},
        "resource_class": "default",
        "timeout_s": 60,
        "cancel_requested": False,
    }


def _run_until(runner: ExecutorRunner, done: threading.Event, timeout: float = 10.0) -> None:
    thread = runner.run_in_thread()
    done.wait(timeout)
    runner.drain()
    runner.wait_stopped(timeout)
    thread.join(timeout=5)


def test_full_cycle_claim_execute_complete():
    fake = FakeCore([_task("t1")])
    done = threading.Event()
    executed = []

    def handler(input, cancel_check):
        executed.append(input)
        return {"out": "ok"}

    runner, _ = _make_runner(fake, {"fake_cap": handler})
    _run_until(runner, done)
    time.sleep(0.1)

    assert executed == [{"paper_id": "p1"}]
    assert len(fake.completed) == 1
    assert fake.completed[0]["result"] == {"out": "ok"}
    assert not fake.failed


def test_handler_exception_reports_fail():
    fake = FakeCore([_task("t2")])
    done = threading.Event()

    def handler(input, cancel_check):
        raise RuntimeError("handler exploded")

    runner, _ = _make_runner(fake, {"fake_cap": handler})
    _run_until(runner, done)
    time.sleep(0.1)

    assert len(fake.failed) == 1
    assert fake.failed[0]["error_class"] == "RuntimeError"
    assert "handler exploded" in fake.failed[0]["message"]
    assert not fake.completed


def test_no_handler_capability_reports_fail():
    fake = FakeCore([_task("t3", capability="unknown_cap")])
    done = threading.Event()

    runner, _ = _make_runner(fake, {"fake_cap": lambda input, cancel_check: {}})
    _run_until(runner, done)
    time.sleep(0.1)

    assert len(fake.failed) == 1
    assert fake.failed[0]["error_class"] == "no_handler"


def test_cancel_requested_cooperative_exit():
    fake = FakeCore([_task("t4")], cancel_on_heartbeat=True)
    done = threading.Event()
    cancel_seen = threading.Event()

    def handler(input, cancel_check):
        deadline = time.monotonic() + 5
        while not cancel_check():
            if time.monotonic() > deadline:
                raise AssertionError("取消请求未到达 handler")
            cancel_seen.set()
            time.sleep(0.05)
        return {"cancelled": True}

    runner, _ = _make_runner(fake, {"fake_cap": handler}, heartbeat_interval_s=0.05)
    _run_until(runner, done, timeout=10)
    time.sleep(0.2)

    assert cancel_seen.is_set()
    assert len(fake.failed) == 1
    assert fake.failed[0]["error_class"] == "cancelled"


def test_drain_stops_claiming():
    fake = FakeCore([_task("t5"), _task("t6")])
    executed = threading.Event()
    release = threading.Event()

    def handler(input, cancel_check):
        executed.set()
        release.wait(5)  # 阻塞当前 Attempt，主线程先 drain
        return {}

    runner, _ = _make_runner(fake, {"fake_cap": handler}, idle_exit_after_s=0.5)
    thread = runner.run_in_thread()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not executed.is_set():
        time.sleep(0.05)
    runner.drain()
    release.set()
    thread.join(timeout=10)
    assert runner.wait_stopped(1)
    # t6 未被领取（drain 后不再 claim）
    assert len(fake.claimed) == 1
