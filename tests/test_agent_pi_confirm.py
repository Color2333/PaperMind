"""E7：Web 聊天破坏性工具确认链测试（Pi 引擎 pending-action 决定落库）。

覆盖：
- pending-action 创建（conversation_state 记 engine=pi/status=pending）；
- 轮询端点读取状态；404 = 过期；
- confirm/reject 对 Pi 动作：轻量落决定（返回 JSON，不开续播流）；
- confirm/reject 对 Python 引擎动作：不误伤（返回 SSE，走原逻辑）。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from apps.api.routers.agent import (
    _resolve_pi_action,
    create_pending_action,
    get_pending_action,
)


@pytest.fixture()
def pi_action(db_session):
    """一条 Pi 引擎 pending action。"""
    from packages.storage.repositories import AgentPendingActionRepository

    repo = AgentPendingActionRepository(db_session)
    record = repo.create(
        action_id="pi-action-1",
        tool_name="pm_submit_job",
        tool_args={"capability": "skim_paper", "paper_id": "p1"},
        conversation_state={"engine": "pi", "status": "pending", "description": "提交 skim？"},
    )
    db_session.flush()
    return record


def test_create_pending_action_requires_tool():
    with pytest.raises(HTTPException) as ei:
        create_pending_action({"tool": ""})
    assert ei.value.status_code == 400


def test_create_and_poll_pending_action(db_session):
    created = create_pending_action(
        {
            "tool": "pm_cancel_job",
            "args": {"job_id": "j1"},
            "description": "取消 Job j1？",
            "conversation_id": None,
        }
    )
    assert created["status"] == "pending"

    state = get_pending_action(created["id"])
    assert state["status"] == "pending"
    assert state["tool"] == "pm_cancel_job"
    assert state["description"] == "取消 Job j1？"


def test_poll_missing_action_is_404():
    with pytest.raises(HTTPException) as ei:
        get_pending_action("nonexistent")
    assert ei.value.status_code == 404


def test_pi_action_confirm_resolves_decision(db_session, pi_action):
    """Pi 动作 confirm：轻量落决定（approved），不抛出、不开流"""
    assert _resolve_pi_action("pi-action-1", "approved") is True
    db_session.expire_all()
    assert get_pending_action("pi-action-1")["status"] == "approved"


def test_pi_action_reject_resolves_decision(db_session, pi_action):
    assert _resolve_pi_action("pi-action-1", "rejected") is True
    db_session.expire_all()
    assert get_pending_action("pi-action-1")["status"] == "rejected"


def test_python_engine_action_not_intercepted(db_session):
    """Python 引擎动作（conversation_state 无 engine=pi）不被 Pi 分支误伤——
    仍走原 SSE 续播逻辑。"""
    from packages.storage.repositories import AgentPendingActionRepository

    repo = AgentPendingActionRepository(db_session)
    repo.create(
        action_id="py-action-1",
        tool_name="ingest_arxiv",
        tool_args={"query": "llm"},
        conversation_state={"conversation": []},  # Python 引擎：无 engine 字段
    )
    db_session.flush()
    assert _resolve_pi_action("py-action-1", "approved") is False


def test_missing_action_not_intercepted():
    assert _resolve_pi_action("ghost", "approved") is False
