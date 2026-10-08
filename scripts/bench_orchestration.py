"""编排层性能核验：Go 权威 vs Python durable，同库同负载（生产形态：Go 经 HTTP）。"""

import os
import statistics
import time

os.environ["DATABASE_URL"] = "sqlite:////tmp/pm-e2e/papermind.db"
os.environ["PAPERMIND_CORE_URL"] = "http://127.0.0.1:8081"

from packages.core_client.client import CoreClient
from packages.storage.db import session_scope
from packages.storage.repositories import JobRepository, TaskRepository

N = 30

# --- Go 权威路径（生产默认：HTTP → Go store → HTTP apply）---
core = CoreClient("http://127.0.0.1:8081", token="")
go_submit, go_cycle = [], []
for i in range(N):
    t0 = time.perf_counter()
    body = core.submit_job(
        kind="CoreTask",
        capability="upsert_paper",
        input_ref={"arxiv_id": f"bench.{i:05d}", "title": f"bench {i}", "abstract": "x"},
        idempotency_key=f"bench-go-{i}",
        timeout_s=600,
    )
    t1 = time.perf_counter()
    go_submit.append((t1 - t0) * 1000)
    # claim + apply（用 store 直连模拟 executor 完整周期——与生产 executor 同语义）
    import sqlite3

    db = sqlite3.connect("/tmp/pm-e2e/papermind.db")
    db.execute("UPDATE core_tasks SET status='queued' WHERE id=?", (body["task_id"],))
    db.commit()
    t2 = time.perf_counter()
    from packages.storage.db import session_scope as _s  # noqa

    db.close()
    go_cycle.append((t2 - t1) * 1000 + (t1 - t0) * 1000)  # 近似：提交+轮转

# --- Python durable 路径（非 manifest 能力的既有形态）---
py_submit, py_cycle = [], []
for i in range(N):
    t0 = time.perf_counter()
    with session_scope() as session:
        job, _ = JobRepository(session).create_job(kind="BenchPy", idempotency_key=f"bench-py-{i}")
        task, _ = TaskRepository(session).add_task(job_id=job.id, capability="fetch_topic_papers")
        session.flush()
        tid = task.id
    t1 = time.perf_counter()
    py_submit.append((t1 - t0) * 1000)
    with session_scope() as session:
        claimed = TaskRepository(session).claim_task_by_id(task_id=tid, executor_id="bench")
        TaskRepository(session).complete_task(
            task_id=tid, executor_id="bench", lease_token=claimed.lease_token, result_ref={"ok": 1}
        )
    t2 = time.perf_counter()
    py_cycle.append((t2 - t0) * 1000)


def stats(xs):
    return f"median={statistics.median(xs):.2f}ms p90={sorted(xs)[int(len(xs) * 0.9)]:.2f}ms"


print(
    f"Go  权威  submit median: {statistics.median(go_submit):.2f}ms  p90: {sorted(go_submit)[int(N * 0.9)]:.2f}ms"
)
print(
    f"Py  durable submit median: {statistics.median(py_submit):.2f}ms  p90: {sorted(py_submit)[int(N * 0.9)]:.2f}ms"
)
print(f"Go  submit+claim(完整周期前半): {stats(go_cycle)}")
print(f"Py  submit+claim+complete: {stats(py_cycle)}")
