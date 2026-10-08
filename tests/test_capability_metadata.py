"""E5/E6：capability metadata 导出 + permission profiles 校验测试"""

from __future__ import annotations

import json

import pytest

from packages.application.capability import (
    PROFILES,
    check_scope,
    export_capability_metadata,
    get_capability,
    validate_profile,
)


def test_export_capability_metadata():
    data = json.loads(export_capability_metadata())
    assert data["schema_version"] == 1
    assert len(data["capabilities"]) >= 10
    for cap in data["capabilities"]:
        assert cap["name"]
        assert cap["kind"] in ("query", "command", "start_job")
        assert cap["risk"] in ("read_only", "write", "destructive")
        assert cap["required_scope"] in ("research:read", "research:write", "jobs:control", "admin")
        assert "surfaces" in cap


def test_get_capability():
    cap = get_capability("search_papers")
    assert cap.kind == "query"
    with pytest.raises(KeyError):
        get_capability("nonexistent")


def test_validate_profiles():
    assert "research:read" in validate_profile("research")
    assert "admin" in validate_profile("coding")
    assert "jobs:control" not in validate_profile("demo")
    with pytest.raises(ValueError, match="未知 permission profile"):
        validate_profile("nonexistent")


def test_check_scope():
    assert check_scope(["research:read", "research:write"], "research:read") is True
    assert check_scope(["research:read"], "research:write") is False
    assert check_scope(["research:read", "jobs:control"], "jobs:control") is True


def test_demo_never_gets_admin():
    """设计④硬规则：Demo 永不开放 coding/admin"""
    demo_scopes = PROFILES["demo"]
    assert "admin" not in demo_scopes
    assert "jobs:control" not in demo_scopes


def test_exec_pool_split():
    """执行池分池契约（防单执行器自死锁）：编排器独立成池，两池不相交且全覆盖"""
    from packages.application.commands.task_registry import (
        EXEC_POOLS,
        TASK_CAPABILITIES,
        capabilities_in_pool,
    )

    orch = set(capabilities_in_pool("orchestration"))
    comp = set(capabilities_in_pool("compute"))
    executor_caps = {n for n, s in TASK_CAPABILITIES.items() if s.trigger == "executor"}

    # 两池不相交，且覆盖全部 executor 触发能力
    assert not (orch & comp)
    assert orch | comp == executor_caps
    # 编排器池必须包含已知 submit+poll 编排器（run_topic_ingest/weekly/cs/daily 链）
    assert {
        "fetch_topic_papers",
        "topic_dispatch",
        "weekly_graph_maintenance",
        "daily_ingest_and_brief",
        "cs_feed_dispatch",
        "batch_process_unread",
        "skim_papers_batch",
    } <= orch
    # compute 池不得混入编排器（它们会 submit+poll 等子任务）
    assert "fetch_topic_papers" not in comp
    assert EXEC_POOLS == ("compute", "orchestration")


def test_worker_host_dual_pool_wiring():
    """worker 宿主按池分领取器（源码契约：编排器池与 compute 池各一个 Runner）"""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "apps" / "worker" / "main.py").read_text()
    assert "capabilities_in_pool" in src, "worker 未按池取领取集合"
    assert "_executor_pools" in src, "worker 未维护多池 Runner 列表"
    # 单池串行旧路径必须消失（全部能力一个 Runner 即自死锁形态）
    assert 'spec.trigger == "executor"]' not in src
