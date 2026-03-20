"""
TeammateManager — 持久化 Agent 团队管理，参考 learn-claude-code s09

核心设计：
- Teammate 和 Subagent 的区别：
    Subagent: spawn → execute → return → destroyed（一次性）
    Teammate:  spawn → work → idle → work → ... → shutdown（持久）
- 每个 teammate 运行在独立线程中
- 线程内部运行自己的 agent_loop
- 通过 MessageBus 异步通信

    spawn_teammate("alice", "coder", "fix the login bug"):
        → 查找/创建 alice 配置
        → 启动 alice_thread(_teammate_loop, args=(alice, role, prompt))
        → alice_thread.start()

    _teammate_loop:
        while True:
            inbox = BUS.read_inbox(alice)
            if inbox: messages.append(inbox messages)
            response = LLM(messages, tools)
            if stop_reason != "tool_use": break
            execute tools...
"""

from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from anthropic import Anthropic

from .message_bus import MessageBus


class TeammateManager:
    def __init__(self, team_dir: Path, inbox_dir: Path, model: str, system_base: str):
        self.team_dir = team_dir
        self.inbox_dir = inbox_dir
        self.model = model
        self.system_base = system_base
        self.bus = MessageBus(inbox_dir)
        self.threads: dict[str, threading.Thread] = {}
        self.config_path = team_dir / "config.json"
        self.config = self._load_config()
        team_dir.mkdir(parents=True, exist_ok=True)

    def _load_config(self) -> dict:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text())
        return {"team_name": "default", "members": []}

    def _save_config(self) -> None:
        self.config_path.write_text(json.dumps(self.config, indent=2))

    def _find_member(self, name: str) -> dict | None:
        for m in self.config["members"]:
            if m["name"] == name:
                return m
        return None

    def list_all(self) -> str:
        if not self.config["members"]:
            return "No teammates."
        lines = [f"Team: {self.config['team_name']}"]
        for m in self.config["members"]:
            lines.append(f"  {m['name']} ({m['role']}): {m['status']}")
        return "\n".join(lines)

    def member_names(self) -> list[str]:
        return [m["name"] for m in self.config["members"]]

    def spawn(
        self,
        name: str,
        role: str,
        prompt: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> str:
        member = self._find_member(name)
        if member:
            if member["status"] not in ("idle", "shutdown"):
                return f"Error: '{name}' is currently {member['status']}"
            member["status"] = "working"
            member["role"] = role
        else:
            member = {"name": name, "role": role, "status": "working"}
            self.config["members"].append(member)

        self._save_config()

        thread = threading.Thread(
            target=self._teammate_loop,
            args=(name, role, prompt, tools or []),
            daemon=True,
        )
        self.threads[name] = thread
        thread.start()
        return f"Spawned '{name}' (role: {role})"

    def shutdown(self, name: str) -> str:
        self.bus.send("lead", name, "Please shutdown gracefully.", "shutdown_request")
        member = self._find_member(name)
        if member:
            member["status"] = "shutdown_requested"
            self._save_config()
        return f"Shutdown requested for '{name}'"

    def _teammate_loop(
        self,
        name: str,
        role: str,
        prompt: str,
        tools: list[dict[str, Any]],
    ) -> None:
        sys_prompt = (
            f"You are '{name}', role: {role}. "
            f"{self.system_base} "
            "Use send_message to communicate with teammates."
        )
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        client = Anthropic()

        for _ in range(500):  # max iterations per session
            inbox = self.bus.read_inbox(name)
            for msg in inbox:
                msg_type = msg.get("type", "message")
                if msg_type == "shutdown_request":
                    self._mark_idle(name)
                    return
                messages.append({"role": "user", "content": json.dumps(msg)})

            try:
                response = client.messages.create(
                    model=self.model,
                    system=sys_prompt,
                    messages=messages,
                    tools=tools,
                    max_tokens=8000,
                )
            except Exception:
                break

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                break

            results = []
            for block in response.content:
                if hasattr(block, "type") and block.type == "tool_use":
                    output = self._exec_tool(name, block.name, block.input)
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(output)[:50_000],
                        }
                    )
                    print(f"  [{name}] {block.name}: {str(output)[:120]}")

            messages.append({"role": "user", "content": results})

        self._mark_idle(name)

    def _mark_idle(self, name: str) -> None:
        member = self._find_member(name)
        if member and member["status"] != "shutdown":
            member["status"] = "idle"
            self._save_config()

    def _exec_tool(self, sender: str, tool_name: str, args: dict) -> str:
        from .tools.bash import run_bash
        from .tools.filesystem import run_edit, run_read, run_write

        if tool_name == "bash":
            return run_bash(args["command"])
        if tool_name == "read_file":
            return run_read(args["path"])
        if tool_name == "write_file":
            return run_write(args["path"], args["content"])
        if tool_name == "edit_file":
            return run_edit(args["path"], args["old_text"], args["new_text"])
        if tool_name == "send_message":
            return self.bus.send(
                sender, args["to"], args["content"], args.get("msg_type", "message")
            )
        if tool_name == "read_inbox":
            return json.dumps(self.bus.read_inbox(sender), indent=2)
        return f"Unknown tool: {tool_name}"
