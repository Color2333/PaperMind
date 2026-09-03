"""Stage I 精简与收敛门（I1–I3 可检查守卫）

双重完成门的退出口断言：
- I1 任务系统：唯一权威 = durable store；TaskTracker/双写桥接已删除；
- I2 能力入口：所有长任务能力在 C4 注册表，handler 可导入且遵守
  progress/cancel 约定；
- I3 执行路径：无进程内直跑业务的旁路（worker 只提交 + Executor 宿主）。
"""

from __future__ import annotations

import importlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_task_tracker_module_is_gone():
    """I1：内存 TaskTracker 已删除——任务状态唯一权威是 durable store"""
    assert not (REPO / "packages/domain/task_tracker.py").exists(), (
        "packages/domain/task_tracker.py 应已删除（C3 退出口）"
    )


def test_no_production_code_references_tracker():
    """I1：生产代码零 global_tracker / submit_tracked_* 引用（注释亦不得误导）"""
    banned = ("global_tracker", "submit_tracked_compat", "submit_durable_job", "task_tracker")
    offenders: list[str] = []
    for base in ("packages", "apps"):
        for py in (REPO / base).rglob("*.py"):
            if "test" in py.parts or "__pycache__" in py.parts:
                continue
            text = py.read_text(errors="replace")
            for b in banned:
                if b in text:
                    offenders.append(f"{py.relative_to(REPO)}: {b}")
    assert offenders == [], f"退出口后仍存在 tracker 引用：{offenders}"


def test_batch_consumer_retired():
    """I1/C11：batch_jobs 消费者已删除，无生产引用"""
    assert not (REPO / "packages/agent_core/batch_consumer.py").exists()
    offenders = [
        str(p.relative_to(REPO))
        for p in (REPO / "packages").rglob("*.py")
        if "batch_consumer" in p.read_text(errors="replace")
    ]
    offenders += [
        str(p.relative_to(REPO))
        for p in (REPO / "apps").rglob("*.py")
        if "batch_consumer" in p.read_text(errors="replace")
    ]
    assert offenders == [], f"batch_consumer 仍被引用：{offenders}"


def test_all_capabilities_importable_and_conventioned():
    """I2：每个 C4 能力 handler 可导入；模块级 handler 接受 progress 注入"""
    from packages.application.commands.task_registry import TASK_CAPABILITIES
    from packages.executor_runtime.runner import resolve_handler

    assert len(TASK_CAPABILITIES) >= 25, "C3 退出口后应有 25+ 项能力"
    for name, spec in TASK_CAPABILITIES.items():
        fn = resolve_handler(spec.handler)
        assert callable(fn), f"{name}: handler 不可调用"
        if "task_handlers" in (getattr(fn, "__module__", "") or ""):
            # 统一约定：*, progress=None + 业务参数
            import inspect

            params = inspect.signature(fn).parameters
            assert "progress" in params, f"{name}: task_handlers 函数须接受 progress 注入"


def test_worker_is_submit_only_with_executor_host():
    """I3：worker 无直跑业务 import；只有 submit + Executor 宿主"""
    src = (REPO / "apps/worker/main.py").read_text()
    for banned in (
        "run_daily_brief",
        "run_topic_ingest",
        "run_weekly_graph_maintenance",
        "CSFeedOrchestrator",
        "PaperPipelines",
    ):
        assert banned not in src, f"worker 仍直接引用业务执行体：{banned}"
    assert "submit_job" in src, "worker 调度应经 submit_job 提交"
    assert "ExecutorRunner" in src, "worker 应内置 Executor 宿主"


def test_api_commands_do_not_spawn_threads_for_business():
    """I3：命令层不再自管业务线程（BackgroundTasks/threading 执行业务已消失）"""
    banned_files = [
        REPO / "packages/application/commands/daily.py",
        REPO / "packages/application/commands/pipelines.py",
        REPO / "packages/application/commands/graph.py",
    ]
    for f in banned_files:
        src = f.read_text()
        assert "threading.Thread(" not in src, f"{f.name} 仍在自管线程执行业务"
        assert "ThreadPoolExecutor" not in src, f"{f.name} 仍在自管线程池执行业务"


def test_tasks_observation_surface_is_durable_only():
    """I1：/tasks 观察面只读 durable store（queries/tasks.py 无 tracker 概念）"""
    src = (REPO / "packages/application/queries/tasks.py").read_text()
    assert "external_ref" in src  # 历史行兼容解析保留
    assert "TaskRepository" in src or "DurableTask" in src  # 只读 durable


def test_inline_executor_is_test_only():
    """I3：InlineExecutor 只存在于 tests/（生产执行路径唯一 = Go Core 调度）"""
    prod = [
        str(p.relative_to(REPO))
        for base in ("packages", "apps")
        for p in (REPO / base).rglob("*.py")
        if "InlineExecutor" in p.read_text(errors="replace")
    ]
    assert prod == [], f"InlineExecutor 泄漏进生产代码：{prod}"


def test_capability_specs_survive_registry_invariants():
    """I2：注册表不变量对全部能力生效（handler 可导入/资源类/超时）"""
    from packages.application.commands.task_registry import RESOURCE_CLASSES, TASK_CAPABILITIES

    for name, spec in TASK_CAPABILITIES.items():
        importlib.import_module(spec.handler.split(":")[0])
        assert spec.resource_class in RESOURCE_CLASSES, f"{name}: 资源类不合法"
        assert spec.timeout_s > 0 and spec.max_attempts >= 1, f"{name}: 重试参数非法"
        if spec.manual_recovery:
            assert spec.max_attempts == 1, f"{name}: manual_recovery 不得自动重试"
