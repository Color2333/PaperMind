"""
TeamProtocols — Agent Team 通信协议，参考 learn-claude-code s10

核心设计：
- 5 种消息类型驱动所有协作：
    message              — 普通文本消息
    broadcast           — 广播给所有 teammate
    shutdown_request     — 请求关闭
    shutdown_response    — 同意/拒绝关闭
    plan_approval_request  — 请求批准计划
    plan_approval_response — 同意/拒绝计划

- shutdown FSM:
    lead → shutdown_request → teammate → shutdown_response → lead

- plan_approval FSM:
    teammate → plan_approval_request → lead
    lead → plan_approval_response (approved/rejected) → teammate

这些协议保证了多 agent 协作的确定性行为。
"""

from __future__ import annotations

from enum import Enum


class ProtocolState(Enum):
    IDLE = "idle"
    AWAITING_SHUTDOWN_RESPONSE = "awaiting_shutdown_response"
    AWAITING_PLAN_APPROVAL = "awaiting_plan_approval"
    WORKING = "working"


class ProtocolError(Exception):
    pass


class TeamProtocols:
    """
    管理 team-level 协议状态。
    提供 shutdown 和 plan_approval FSM 实现。
    """

    def __init__(self):
        self._states: dict[str, ProtocolState] = {}
        self._pending_approvals: dict[str, dict] = {}

    def state(self, agent_name: str) -> ProtocolState:
        return self._states.get(agent_name, ProtocolState.IDLE)

    def set_state(self, agent_name: str, state: ProtocolState) -> None:
        self._states[agent_name] = state

    def request_shutdown(self, agent_name: str) -> dict:
        """生成 shutdown_request 消息"""
        self._states[agent_name] = ProtocolState.AWAITING_SHUTDOWN_RESPONSE
        return {
            "type": "shutdown_request",
            "content": f"Lead requests graceful shutdown of '{agent_name}'.",
        }

    def handle_shutdown_response(
        self,
        agent_name: str,
        approved: bool,
        message: str = "",
    ) -> str:
        """处理 shutdown_response"""
        if self._states.get(agent_name) != ProtocolState.AWAITING_SHUTDOWN_RESPONSE:
            return f"Error: Not awaiting shutdown response from '{agent_name}'"

        self._states[agent_name] = ProtocolState.IDLE
        if approved:
            return f"'{agent_name}' approved shutdown."
        return f"'{agent_name}' rejected shutdown: {message}"

    def request_plan_approval(
        self,
        agent_name: str,
        plan_summary: str,
        plan_detail: str,
    ) -> dict:
        """生成 plan_approval_request 消息"""
        self._states[agent_name] = ProtocolState.AWAITING_PLAN_APPROVAL
        approval_id = f"approval_{agent_name}_{len(self._pending_approvals)}"
        self._pending_approvals[approval_id] = {
            "agent_name": agent_name,
            "plan_summary": plan_summary,
            "plan_detail": plan_detail,
            "approved": None,
        }
        return {
            "type": "plan_approval_request",
            "approval_id": approval_id,
            "content": f"Plan from '{agent_name}': {plan_summary}",
        }

    def handle_plan_response(
        self,
        approval_id: str,
        approved: bool,
        feedback: str = "",
    ) -> str:
        """处理 plan_approval_response"""
        if approval_id not in self._pending_approvals:
            return f"Error: Unknown approval_id '{approval_id}'"

        pending = self._pending_approvals[approval_id]
        pending["approved"] = approved
        pending["feedback"] = feedback
        self._states[pending["agent_name"]] = ProtocolState.IDLE

        agent = pending["agent_name"]
        if approved:
            return f"Plan approved for '{agent}': {feedback}"
        return f"Plan rejected for '{agent}': {feedback}"

    def get_pending_approvals(self) -> list[dict]:
        return [
            {**p, "approval_id": k}
            for k, p in self._pending_approvals.items()
            if p["approved"] is None
        ]
