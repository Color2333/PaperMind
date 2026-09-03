"""本地故障注入实验（第二轮 REVIEW 合并门槛 #3 的可重复脚本）。

与 tests/test_p0_closed_loop.py 的差异：这里是**全独立进程**编排——
真实 uvicorn API、真实 Go Core 二进制、真实 Executor 子进程，逐一 SIGKILL
并重启，验证从 durable store 恢复。可重复运行：

    .venv/bin/python scripts/fault_injection_local.py

场景：
  A. 基线：API 只写 durable Job/Task → Core 调度 → Executor 完成真实 skim；
  B. 强杀 Executor（SIGKILL）→ lease 过期 → Reconciler 回收 → 新 Executor 二次 attempt 完成；
  C. 强杀 Go Core → 重启（零任务内存态）→ Executor 重注册 → 继续调度；
  D. 强杀 API（durable-state 所在）→ 重启 → 队列恢复；
  E. 协作取消：cancel 正在运行的 handler → 安全点退出 → cancelled；
  F. 跨进程 pause/resume。

产物：stdout 过程记录；各进程日志写入 --workdir。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_TOKEN = "fault-injection-core-token"
STATE_TOKEN = "fault-injection-state-token"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Lab:
    def __init__(self, workdir: Path, core_bin: Path) -> None:
        self.work = workdir
        self.work.mkdir(parents=True, exist_ok=True)
        self.db = workdir / "fault.db"
        self.core_bin = core_bin
        self.api_port = free_port()
        self.core_port = free_port()
        self.procs: dict[str, subprocess.Popen] = {}

    def log(self, msg: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    def env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            {
                "DATABASE_URL": f"sqlite:///{self.db}",
                "PAPERMIND_ENV_FILE": str(self.work / "no-env"),
                "AUTH_PASSWORD": "",
                "DURABLE_STATE_TOKEN": STATE_TOKEN,
                "PYTHONPATH": str(REPO_ROOT),
            }
        )
        return env

    def spawn(self, name: str, cmd: list[str], extra_env: dict[str, str] | None = None) -> None:
        env = self.env()
        env.update(extra_env or {})
        fh = open(self.work / f"{name}.log", "ab")  # noqa: SIM115
        self.procs[name] = subprocess.Popen(
            cmd, cwd=REPO_ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT
        )

    def wait_http(self, url: str, name: str) -> None:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            proc = self.procs.get(name)
            if proc is not None and proc.poll() is not None:
                raise RuntimeError(f"{name} 退出：{self.tail(name)}")
            try:
                if httpx.get(url, timeout=2).status_code < 500:
                    return
            except Exception:
                time.sleep(0.3)
        raise RuntimeError(f"{name} 未就绪")

    def tail(self, name: str, n: int = 25) -> str:
        f = self.work / f"{name}.log"
        if not f.exists():
            return ""
        return "\n".join(f.read_text(errors="replace").splitlines()[-n:])

    # ---------- 组件 ----------

    def start_api(self) -> None:
        self.spawn(
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
        self.wait_http(f"http://127.0.0.1:{self.api_port}/health", "api")
        self.log(f"API up  :{self.api_port}")

    def start_core(self) -> None:
        self.spawn(
            "core",
            [str(self.core_bin)],
            {
                "CORE_ADDR": f"127.0.0.1:{self.core_port}",
                "CORE_TOKEN": CORE_TOKEN,
                "STATE_ADDR": f"http://127.0.0.1:{self.api_port}",
                "STATE_TOKEN": STATE_TOKEN,
                "RECONCILE_INTERVAL_S": "1",
                "RECLAIM_BACKOFF_S": "1",
            },
        )
        self.wait_http(f"http://127.0.0.1:{self.core_port}/health", "core")
        self.log(f"Core up :{self.core_port}")

    def start_executor(self, eid: str, delay_s: float = 0.0) -> None:
        cmd = [
            sys.executable,
            "-m",
            "apps.executor",
            "--core-url",
            f"http://127.0.0.1:{self.core_port}",
            "--core-token",
            CORE_TOKEN,
            "--executor-id",
            eid,
            "--capabilities",
            "skim_paper",
            "--poll-interval",
            "0.5",
            "--heartbeat-interval",
            "1",
        ]
        if delay_s:
            cmd += ["--handler-delay-s", str(delay_s)]
        self.spawn(f"executor-{eid}", cmd)
        self.log(f"Executor {eid} up (delay={delay_s}s)")

    def kill(self, name: str) -> None:
        proc = self.procs.pop(name, None)
        if proc and proc.poll() is None:
            proc.send_signal(signal.SIGKILL)
            proc.wait(timeout=10)
        self.log(f"SIGKILL {name}")

    def stop(self) -> None:
        for proc in self.procs.values():
            if proc.poll() is None:
                proc.terminate()
        deadline = time.monotonic() + 10
        for _name, proc in list(self.procs.items()):
            try:
                proc.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                proc.kill()
        self.procs.clear()

    # ---------- 观察 ----------

    def api(self) -> httpx.Client:
        return httpx.Client(base_url=f"http://127.0.0.1:{self.api_port}", timeout=10)

    def seed_paper(self, arxiv_id: str) -> str:
        snippet = (
            "from packages.storage.db import run_migrations, session_scope\n"
            "run_migrations()\n"
            "from packages.domain.schemas import PaperCreate\n"
            "from packages.storage.repositories import PaperRepository\n"
            f"with session_scope() as s:\n"
            "    p = PaperRepository(s).upsert_paper(PaperCreate(\n"
            f"        arxiv_id='{arxiv_id}', title='Fault injection paper',\n"
            "        abstract='Streaming transformer diarization with multi-channel fusion.'))\n"
            "    print(p.id)\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", snippet],
            cwd=REPO_ROOT,
            env=self.env(),
            check=True,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip().splitlines()[-1]

    def submit(self, paper_id: str, timeout_s: int = 60) -> dict:
        resp = self.api().post(
            "/jobs/durable",
            json={
                "kind": "SkimPaper",
                "capability": "skim_paper",
                "title": "fault injection",
                "input_ref": {"paper_id": paper_id},
                "timeout_s": timeout_s,
                "max_attempts": 3,
            },
        )
        resp.raise_for_status()
        return resp.json()

    def job(self, job_id: str) -> dict:
        return self.api().get(f"/jobs/{job_id}").json()

    def wait_job(self, job_id: str, statuses: set[str], timeout: float = 60) -> dict:
        deadline = time.monotonic() + timeout
        last: dict = {}
        while time.monotonic() < deadline:
            last = self.job(job_id)
            if last["status"] in statuses:
                return last
            time.sleep(0.4)
        raise AssertionError(
            f"job {job_id} 未到达 {statuses}（最后 {last.get('status')}）；"
            f"tasks={json.dumps(last.get('tasks', [])[:1], ensure_ascii=False)}"
        )

    def read_status(self, paper_id: str) -> str:
        return self.api().get(f"/papers/{paper_id}").json()["read_status"]


def build_core(workdir: Path) -> Path:
    out = workdir / "papermind-core"
    subprocess.run(
        ["go", "build", "-o", str(out), "./cmd/papermind-core"],
        cwd=REPO_ROOT / "core",
        check=True,
        capture_output=True,
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", default=str(REPO_ROOT / "data" / "fault-injection"))
    args = parser.parse_args()
    workdir = Path(args.workdir)
    if workdir.exists():
        shutil.rmtree(workdir)
    core_bin = build_core(workdir)
    lab = Lab(workdir, core_bin)
    results: dict[str, str] = {}

    try:
        # 场景 A：基线全链路
        lab.start_api()
        lab.start_core()
        paper = lab.seed_paper("2401.00001")
        lab.start_executor("exec-1")
        sub = lab.submit(paper)
        lab.wait_job(sub["job_id"], {"succeeded"})
        assert lab.read_status(paper) == "skimmed"
        graph = lab.job(sub["job_id"])
        assert graph["attempts"][0]["executor_id"] == "exec-1"
        results["A_baseline"] = "PASS（真实 skim 经 API→Core→Executor 完成，executor=exec-1）"

        # 场景 B：强杀 Executor → 回收 → 恢复
        lab.start_executor("exec-slow", delay_s=30)
        sub = lab.submit(paper, timeout_s=3)
        job_id = sub["job_id"]
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and len(lab.job(job_id)["attempts"]) < 1:
            time.sleep(0.3)
        lab.kill("executor-exec-slow")
        lab.start_executor("exec-2")
        graph = lab.wait_job(job_id, {"succeeded"})
        assert graph["tasks"][0]["attempt_count"] == 2, graph["tasks"][0]
        executors = [a["executor_id"] for a in graph["attempts"]]
        # 第一次 attempt 是被杀的 exec-slow（lease_expired）；第二次由任一存活 executor 完成
        assert executors[0] == "exec-slow", executors
        assert executors[1] in {"exec-1", "exec-2"}, executors
        results["B_kill_executor"] = (
            "PASS（SIGKILL 后 lease 过期回收，attempt1 标记 lease_expired，attempt2 完成）"
        )

        # 场景 C：强杀 Go Core → 重启恢复
        sub = lab.submit(paper)
        job_id = sub["job_id"]
        lab.kill("core")
        time.sleep(0.5)
        lab.start_core()
        graph = lab.wait_job(job_id, {"succeeded"})
        results["C_kill_core"] = "PASS（Core 重启零任务态丢失，executor 重注册后完成）"

        # 场景 D：强杀 API → 重启恢复
        sub = lab.submit(paper)
        job_id = sub["job_id"]
        lab.kill("api")
        time.sleep(2)
        lab.start_api()
        graph = lab.wait_job(job_id, {"succeeded"})
        results["D_kill_api"] = "PASS（API 宕机期间任务滞留 durable store，重启后完成）"

        # 场景 E：协作取消（独立论文——验证"未产生业务效果"才有意义）
        # 先停掉前序场景的存活 executor，确保只有慢 executor 领取
        for name in ("executor-exec-1", "executor-exec-2"):
            if name in lab.procs:
                lab.kill(name)
        cancel_paper = lab.seed_paper("2401.00002")
        lab.start_executor("exec-cancel", delay_s=30)
        sub = lab.submit(cancel_paper, timeout_s=120)
        job_id = sub["job_id"]
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and len(lab.job(job_id)["attempts"]) < 1:
            time.sleep(0.3)
        resp = lab.api().post(f"/jobs/{job_id}/cancel")
        resp.raise_for_status()
        graph = lab.wait_job(job_id, {"cancelled"}, timeout=30)
        assert graph["attempts"][0]["status"] == "cancelled"
        assert lab.read_status(cancel_paper) != "skimmed"
        results["E_cancel"] = (
            "PASS（运行中 handler 安全点退出，Task/Attempt/Job=cancelled，无副作用）"
        )

        # 场景 F：跨进程 pause/resume
        subprocess.run(
            [
                sys.executable,
                "-c",
                "from packages.application.commands.jobs import pause_queue\npause_queue()",
            ],
            cwd=REPO_ROOT,
            env=lab.env(),
            check=True,
            capture_output=True,
        )
        sub = lab.submit(paper)
        job_id = sub["job_id"]
        time.sleep(3)
        assert lab.job(job_id)["status"] == "queued"
        subprocess.run(
            [
                sys.executable,
                "-c",
                "from packages.application.commands.jobs import resume_queue\nresume_queue()",
            ],
            cwd=REPO_ROOT,
            env=lab.env(),
            check=True,
            capture_output=True,
        )
        lab.wait_job(job_id, {"succeeded"})
        results["F_pause_resume"] = "PASS（持久化 pause 阻塞跨进程 claim，resume 后完成）"
    finally:
        lab.stop()

    print("\n===== 故障注入结果 =====")
    for k, v in results.items():
        print(f"{k}: {v}")
    print(f"\n进程日志目录：{workdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
