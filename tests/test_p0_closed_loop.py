"""P0 闭环验收（第二轮 REVIEW P0）：真实 capability 全链路 + 故障恢复。

链路：API 只写 durable Job/Task（POST /jobs/durable）→ Go Core 代理调度
（控制面网关，零任务内存态）→ 独立 Python Executor 进程注册并领取 →
真实 skim pipeline（fake LLM）执行 → lease/fencing 提交 →
强杀/重启 API / Core / Executor 后从 durable store 恢复。
全过程不回落 global_tracker（断言 attempt.executor_id 为独立 executor）。

需要：Go 工具链（构建 core binary）。无 go 时整模块 skip。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_TOKEN = "core-test-token"
STATE_TOKEN = "state-test-token"

pytestmark = pytest.mark.p0_closed_loop


def _go_available() -> bool:
    from shutil import which

    return which("go") is not None


@pytest.fixture(scope="module")
def core_binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not _go_available():
        pytest.skip("Go 工具链不可用")
    out = tmp_path_factory.mktemp("gobuild") / "papermind-core"
    subprocess.run(
        ["go", "build", "-o", str(out), "./cmd/papermind-core"],
        cwd=REPO_ROOT / "core",
        check=True,
        capture_output=True,
    )
    return out


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Harness:
    """API / Go Core / Executor 三进程生命周期 + 观察辅助"""

    def __init__(self, tmp_path: Path, core_bin: Path) -> None:
        self.tmp = tmp_path
        self.db_path = tmp_path / "closedloop.db"
        self.core_bin = core_bin
        self.api_port = _free_port()
        self.core_port = _free_port()
        self.procs: dict[str, subprocess.Popen] = {}
        self.logs: dict[str, list[str]] = {}

    # ---------- 环境 ----------

    def base_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["DATABASE_URL"] = f"sqlite:///{self.db_path}"
        env["PAPERMIND_ENV_FILE"] = str(self.tmp / "no-such-env")  # 隔离仓库 .env
        env["AUTH_PASSWORD"] = ""  # 关闭用户面认证
        env["DURABLE_STATE_TOKEN"] = STATE_TOKEN
        env["PYTHONPATH"] = str(REPO_ROOT)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return env

    # ---------- 进程 ----------

    def _spawn(self, name: str, cmd: list[str], env_extra: dict[str, str] | None = None) -> None:
        env = self.base_env()
        env.update(env_extra or {})
        log = open(self.tmp / f"{name}.log", "ab")  # noqa: SIM115
        proc = subprocess.Popen(cmd, cwd=REPO_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        self.procs[name] = proc

    def start_api(self) -> None:
        self._spawn(
            "api",
            [
                sys.executable,
                "-m",
                "uvicorn",
                "apps.api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.api_port),
                "--log-level",
                "warning",
            ],
        )
        self._wait_http(f"http://127.0.0.1:{self.api_port}/health", "api")

    def start_core(self) -> None:
        self._spawn(
            "core",
            [str(self.core_bin)],
            env_extra={
                "CORE_ADDR": f"127.0.0.1:{self.core_port}",
                "CORE_TOKEN": CORE_TOKEN,
                "STATE_ADDR": f"http://127.0.0.1:{self.api_port}",
                "STATE_TOKEN": STATE_TOKEN,
                "RECONCILE_INTERVAL_S": "1",
                "RECLAIM_BACKOFF_S": "1",
            },
        )
        self._wait_http(f"http://127.0.0.1:{self.core_port}/health", "core")

    def start_executor(self, *, executor_id: str = "exec-1", delay_s: float = 0.0) -> None:
        cmd = [
            sys.executable,
            "-m",
            "apps.executor",
            "--core-url",
            f"http://127.0.0.1:{self.core_port}",
            "--core-token",
            CORE_TOKEN,
            "--executor-id",
            executor_id,
            "--capabilities",
            "skim_paper",
            "--poll-interval",
            "0.5",
            "--heartbeat-interval",
            "1",
        ]
        if delay_s:
            cmd += ["--handler-delay-s", str(delay_s)]
        self._spawn(f"executor-{executor_id}", cmd)

    def kill(self, name: str) -> None:
        proc = self.procs.pop(name, None)
        if proc is not None and proc.poll() is None:
            proc.kill()  # SIGKILL——强杀
            proc.wait(timeout=10)

    def stop_all(self) -> None:
        for name in list(self.procs):
            proc = self.procs[name]
            if proc.poll() is None:
                proc.terminate()
        for name in list(self.procs):
            try:
                self.procs[name].wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.procs[name].kill()
                self.procs[name].wait(timeout=5)
        self.procs.clear()

    # ---------- 观察 ----------

    def _wait_http(self, url: str, name: str, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            proc = self.procs.get(name)
            if proc is not None and proc.poll() is not None:
                log = (self.tmp / f"{name}.log").read_text(errors="replace")[-2000:]
                raise RuntimeError(f"{name} 提前退出：\n{log}")
            try:
                resp = httpx.get(url, timeout=2.0)
                if resp.status_code < 500:
                    return
            except Exception:  # noqa: BLE001
                time.sleep(0.3)
        raise RuntimeError(f"{name} 未在 {timeout}s 内就绪")

    def api(self) -> httpx.Client:
        return httpx.Client(base_url=f"http://127.0.0.1:{self.api_port}", timeout=10.0)

    def core_post(self, path: str, payload: dict, cid: str = "test-cid") -> httpx.Response:
        envelope = {"schema_version": 1, "correlation_id": cid, "payload": payload}
        return httpx.post(
            f"http://127.0.0.1:{self.core_port}{path}",
            json=envelope,
            headers={"Authorization": f"Bearer {CORE_TOKEN}"},
            timeout=10.0,
        )

    def seed_paper(self) -> str:
        """独立进程向同一 durable store 种一篇论文（模拟既有数据）"""
        snippet = (
            "from packages.storage.db import run_migrations, session_scope\n"
            "run_migrations()\n"
            "from packages.domain.schemas import PaperCreate\n"
            "from packages.storage.repositories import PaperRepository\n"
            "with session_scope() as s:\n"
            "    p = PaperRepository(s).upsert_paper(PaperCreate(\n"
            "        arxiv_id='2401.00001', title='Streaming transformer diarization',\n"
            "        abstract='We propose a streaming transformer diarization method "
            "with multi-channel feature fusion and evaluate on LibriSpeech.'))\n"
            "    print(p.id)\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", snippet],
            cwd=REPO_ROOT,
            env=self.base_env(),
            check=True,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip().splitlines()[-1]

    def submit_job(
        self,
        *,
        capability: str = "skim_paper",
        paper_id: str = "",
        timeout_s: int = 1800,
        max_attempts: int = 3,
    ) -> dict:
        resp = self.api().post(
            "/jobs/durable",
            json={
                "kind": "SkimPaper",
                "capability": capability,
                "title": "P0 closed-loop skim",
                "input_ref": {"paper_id": paper_id},
                "timeout_s": timeout_s,
                "max_attempts": max_attempts,
            },
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    def job(self, job_id: str) -> dict:
        with self.api() as client:
            resp = client.get(f"/jobs/{job_id}")
            assert resp.status_code == 200, resp.text
            return resp.json()

    def wait_job(self, job_id: str, statuses: set[str], timeout: float = 60.0) -> dict:
        deadline = time.monotonic() + timeout
        last: dict = {}
        while time.monotonic() < deadline:
            last = self.job(job_id)
            if last["status"] in statuses:
                return last
            time.sleep(0.4)
        raise AssertionError(
            f"job {job_id} 未在 {timeout}s 内到达 {statuses}，最后状态 {last['status']}"
        )

    def wait_task_attempt(self, job_id: str, min_count: int, timeout: float = 30.0) -> list[dict]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            attempts = self.job(job_id)["attempts"]
            if len(attempts) >= min_count:
                return attempts
            time.sleep(0.3)
        raise AssertionError(f"attempts 未达到 {min_count}（{timeout}s）")


def _run_py(harness: Harness, snippet: str) -> None:
    """在 harness 的 DB 环境里执行一段 python（绝不触碰开发库）"""
    subprocess.run(
        [sys.executable, "-c", snippet],
        cwd=REPO_ROOT,
        env=harness.base_env(),
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def harness(tmp_path: Path, core_binary: Path) -> Harness:
    h = Harness(tmp_path, core_binary)
    h.start_api()
    h.start_core()
    yield h
    h.stop_all()


# ---------- 场景 ----------


def test_api_only_writes_durable_job_then_executor_executes_real_skim(harness: Harness):
    """主链路：API 只写 → Go 调度 → 独立 executor → 真实 skim 生效；无 api-thread 回落"""
    paper_id = harness.seed_paper()
    harness.start_executor(executor_id="exec-1")
    submitted = harness.submit_job(paper_id=paper_id, timeout_s=60)
    # API 只写：任务初始 queued，未领取
    assert submitted["status"] == "queued"
    job_id = submitted["job_id"]

    graph = harness.wait_job(job_id, {"succeeded"}, timeout=60)
    task = graph["tasks"][0]
    assert task["status"] == "succeeded"
    assert task["attempt_count"] == 1
    # 全程不经 global_tracker：attempt 的 executor 是独立进程
    attempts = graph["attempts"]
    assert len(attempts) == 1
    assert attempts[0]["executor_id"] == "exec-1"
    assert attempts[0]["status"] == "succeeded"
    # 真实业务效果：skim pipeline 改写了 read_status
    with harness.api() as client:
        paper = client.get(f"/papers/{paper_id}").json()
    assert paper["read_status"] == "skimmed"


def test_kill_executor_midrun_lease_reclaimed_then_recovered(harness: Harness):
    """强杀 executor：lease 过期 → Reconciler 回收 → 新 executor 第二次 attempt 完成"""
    paper_id = harness.seed_paper()
    harness.start_executor(executor_id="exec-slow", delay_s=30)
    submitted = harness.submit_job(paper_id=paper_id, timeout_s=3, max_attempts=3)
    job_id = submitted["job_id"]

    # 等第一次 attempt 进入 running（exec-slow 领取并卡在慢 handler）
    attempts = harness.wait_task_attempt(job_id, 1)
    assert attempts[0]["executor_id"] == "exec-slow"

    harness.kill("executor-exec-slow")  # SIGKILL：无 complete/fail，无心跳

    # lease(3s)+backoff(1s) 后 Reconciler 重入队；新 executor 领取
    harness.start_executor(executor_id="exec-2")
    graph = harness.wait_job(job_id, {"succeeded"}, timeout=60)
    task = graph["tasks"][0]
    assert task["attempt_count"] == 2
    assert [a["executor_id"] for a in graph["attempts"]] == ["exec-slow", "exec-2"]
    assert graph["attempts"][0]["status"] == "failed"  # 第一次 attempt 被回收标记失败

    with harness.api() as client:
        paper = client.get(f"/papers/{paper_id}").json()
    assert paper["read_status"] == "skimmed"


def test_late_complete_rejected_by_fencing_after_reclaim(harness: Harness):
    """重复/迟到回执：Reclaim 后旧 lease 的 complete 经 Go Core 返回 409"""
    paper_id = harness.seed_paper()
    harness.start_executor(executor_id="exec-slow", delay_s=30)
    submitted = harness.submit_job(paper_id=paper_id, timeout_s=3, max_attempts=3)
    job_id = submitted["job_id"]
    harness.wait_task_attempt(job_id, 1)
    task_id = submitted["task_id"]
    harness.kill("executor-exec-slow")  # SIGKILL：无 complete/fail，无心跳
    # 第一次领取的 lease_token 已随 executor 死亡；等 Reconciler 回收
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        t0 = harness.job(job_id)["tasks"][0]
        if t0["status"] == "queued" and t0["attempt_count"] >= 1:
            break
        time.sleep(0.4)
    else:
        raise AssertionError(
            f"lease 未被回收重入队：task={t0} attempts={harness.job(job_id)['attempts']}"
        )

    # 用未知的旧 lease_token 提交——fencing 拒绝，409 透传
    resp = harness.core_post(
        f"/v1/tasks/{task_id}/complete",
        {
            "executor_id": "exec-slow",
            "task_id": task_id,
            "lease_token": "stale-lease-token",
            "result": {"late": True},
        },
    )
    assert resp.status_code == 409, resp.text

    # 新 executor 完成后，同样的迟到写入依旧 409
    harness.start_executor(executor_id="exec-2")
    harness.wait_job(job_id, {"succeeded"}, timeout=60)
    resp = harness.core_post(
        f"/v1/tasks/{task_id}/complete",
        {
            "executor_id": "exec-2",
            "task_id": task_id,
            "lease_token": "stale-lease-token",
            "result": {"late": True},
        },
    )
    assert resp.status_code == 409, resp.text


def test_core_restart_recovery(harness: Harness):
    """强杀 Go Core → 重启 → executor 重注册 → durable store 状态无损继续调度"""
    paper_id = harness.seed_paper()
    submitted = harness.submit_job(paper_id=paper_id, timeout_s=60)
    job_id = submitted["job_id"]

    harness.kill("core")  # 任务还在 queued——Core 零任务内存态，重启无损
    time.sleep(0.5)
    harness.start_core()
    harness.start_executor(executor_id="exec-1")
    graph = harness.wait_job(job_id, {"succeeded"}, timeout=60)
    assert graph["tasks"][0]["status"] == "succeeded"
    assert graph["attempts"][0]["executor_id"] == "exec-1"


def test_api_restart_recovery(harness: Harness):
    """强杀 API（durable-state 所在）→ 任务停留 durable store → 重启后 executor 领取完成"""
    paper_id = harness.seed_paper()
    submitted = harness.submit_job(paper_id=paper_id, timeout_s=60)
    job_id = submitted["job_id"]

    harness.kill("api")
    harness.start_executor(executor_id="exec-1")
    time.sleep(2.0)  # executor 在 API 宕机期间 claim 应失败重试，任务保持 queued
    harness.start_api()
    graph = harness.wait_job(job_id, {"succeeded"}, timeout=60)
    assert graph["tasks"][0]["status"] == "succeeded"


def test_pause_blocks_claims_cross_process_then_resume(harness: Harness):
    """跨进程 pause：持久化标志（独立进程写入）→ executor 领取不到任务 → 恢复后完成"""
    paper_id = harness.seed_paper()
    _run_py(harness, "from packages.application.commands.jobs import pause_queue\npause_queue()")
    harness.start_executor(executor_id="exec-1")
    submitted = harness.submit_job(paper_id=paper_id, timeout_s=60)
    job_id = submitted["job_id"]
    time.sleep(3.0)
    assert harness.job(job_id)["status"] == "queued"  # 暂停期间不得执行

    _run_py(harness, "from packages.application.commands.jobs import resume_queue\nresume_queue()")
    graph = harness.wait_job(job_id, {"succeeded"}, timeout=60)
    assert graph["tasks"][0]["status"] == "succeeded"


def test_cancel_running_task_cooperative_exit(harness: Harness):
    """取消运行中的真实 handler：安全点退出 → cancelled（不重试不失败）"""
    paper_id = harness.seed_paper()
    harness.start_executor(executor_id="exec-slow", delay_s=30)
    submitted = harness.submit_job(paper_id=paper_id, timeout_s=120, max_attempts=3)
    job_id = submitted["job_id"]
    harness.wait_task_attempt(job_id, 1)

    resp = harness.api().post(f"/jobs/{job_id}/cancel")
    assert resp.status_code == 200
    graph = harness.wait_job(job_id, {"cancelled"}, timeout=30)
    task = graph["tasks"][0]
    assert task["status"] == "cancelled"
    assert graph["attempts"][0]["status"] == "cancelled"
    # 未产生业务效果
    with harness.api() as client:
        paper = client.get(f"/papers/{paper_id}").json()
    assert paper["read_status"] != "skimmed"


def test_unregistered_executor_cannot_claim_via_core(harness: Harness):
    """未注册 executor 直接向 Go Core claim → 403（能力越权防护）"""
    resp = harness.core_post(
        "/v1/tasks/claim",
        {"executor_id": "ghost", "capabilities": ["skim_paper"]},
    )
    assert resp.status_code == 403


def test_submit_idempotency_key_deduplicates(harness: Harness):
    """同 idempotency_key 重复提交返回同一 Job/Task（不重复入队）"""
    paper_id = harness.seed_paper()
    first = (
        harness.api()
        .post(
            "/jobs/durable",
            json={
                "kind": "SkimPaper",
                "capability": "skim_paper",
                "title": "P0 dedupe",
                "input_ref": {"paper_id": paper_id},
                "idempotency_key": "p0-dedupe-1",
            },
        )
        .json()
    )
    second = (
        harness.api()
        .post(
            "/jobs/durable",
            json={
                "kind": "SkimPaper",
                "capability": "skim_paper",
                "title": "P0 dedupe",
                "input_ref": {"paper_id": paper_id},
                "idempotency_key": "p0-dedupe-1",
            },
        )
        .json()
    )
    harness.start_executor(executor_id="exec-1")
    harness.wait_job(first["job_id"], {"succeeded"}, timeout=60)
    assert second["job_id"] == first["job_id"]
    assert second["task_id"] == first["task_id"]
    assert second["created"] is False


def test_state_api_requires_internal_token(harness: Harness):
    """durable-state 内部 API：无/错 token → 401；用户面认证不影响"""
    url = f"http://127.0.0.1:{harness.api_port}/internal/durable/queue/stats"
    assert httpx.get(url, timeout=5).status_code == 401
    assert httpx.get(url, headers={"X-Internal-Token": "wrong"}, timeout=5).status_code == 401
    ok = httpx.get(url, headers={"X-Internal-Token": STATE_TOKEN}, timeout=5)
    assert ok.status_code == 200
    assert "counts" in json.loads(ok.text)


def test_domain_committed_then_killed_guard_prevents_rerun(harness: Harness):
    """P0-1（第三轮 REVIEW）：领域事务已提交、complete 回执丢失 → 第二 Attempt
    经幂等卫兵复用既有结果，不重复执行 handler（不重复 LLM 成本/领域写入）"""
    paper_id = harness.seed_paper()

    # 注入"前 Attempt 已提交领域结果但 complete 丢失"状态：
    # Task1 succeeded（带 result_ref），同 Job 同 capability+paper 的 Task2 queued
    task2_id = (
        subprocess.run(
            [
                sys.executable,
                "-c",
                f"""
from packages.storage.db import session_scope
from packages.storage.repositories import JobRepository, TaskRepository
from packages.domain.enums import TaskStatus
with session_scope() as s:
    job, _ = JobRepository(s).create_job(kind="GuardTest")
    t1, _ = TaskRepository(s).add_task(
        job_id=job.id, capability="skim_paper",
        input_ref={{"paper_id": "{paper_id}", "result_ref": {{"one_liner": "前次结果", "skim_score": 0.9}}}},
        idempotency_key="guard:t1",
    )
    t1.status = TaskStatus.succeeded
    t2, _ = TaskRepository(s).add_task(
        job_id=job.id, capability="skim_paper",
        input_ref={{"paper_id": "{paper_id}"}},
        idempotency_key="guard:t2",
    )
    print(t2.id)
""",
            ],
            cwd=REPO_ROOT,
            env=harness.base_env(),
            check=True,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
        .splitlines()[-1]
    )

    harness.start_executor(executor_id="exec-guard")
    deadline = time.monotonic() + 30
    status = ""
    while time.monotonic() < deadline:
        resp = httpx.get(
            f"http://127.0.0.1:{harness.api_port}/internal/durable/tasks/{task2_id}",
            headers={"X-Internal-Token": STATE_TOKEN},
            timeout=5,
        )
        task = resp.json()["task"]
        status = task["status"]
        if status in ("succeeded", "failed", "dead_letter"):
            with httpx.Client() as c:
                r = c.get(
                    f"http://127.0.0.1:{harness.api_port}/internal/durable/tasks/{task2_id}/domain-result",
                    headers={"X-Internal-Token": STATE_TOKEN},
                    timeout=5,
                )
            break
        time.sleep(0.4)
    assert status == "succeeded", f"Task2 应经卫兵 succeeded，实际 {status}"
    # 卫兵语义：result 来自前 Attempt（one_liner=前次结果），handler 未重新执行
    body = r.json()
    assert body["found"] is True
    assert body["result"]["one_liner"] == "前次结果"
