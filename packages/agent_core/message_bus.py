"""
MessageBus — Agent Team 邮箱机制，参考 learn-claude-code s09

核心设计：
- 每个 teammate 有一个 JSONL 格式的收件箱
- 发消息 = 追加到目标 teammate 的 .jsonl 文件
- 读消息 = 读取并清空自己的收件箱
- append-only 保证消息不丢失

    .team/inbox/
      alice.jsonl   ← alice 的消息
      bob.jsonl     ← bob 的消息
      lead.jsonl    ← lead 的消息

    send_message("alice", "check the bug"):
      → open("alice.jsonl", "a").write(json.dumps(msg))
"""

from __future__ import annotations

import json
import time
from contextlib import suppress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

VALID_MSG_TYPES = {
    "message",
    "broadcast",
    "shutdown_request",
    "shutdown_response",
    "plan_approval_request",
    "plan_approval_response",
}


class MessageBus:
    def __init__(self, inbox_dir: Path):
        self.dir = inbox_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    def send(
        self,
        sender: str,
        to: str,
        content: str,
        msg_type: str = "message",
        extra: dict | None = None,
    ) -> str:
        if msg_type not in VALID_MSG_TYPES:
            return f"Error: Invalid type '{msg_type}'. Valid: {VALID_MSG_TYPES}"

        msg = {
            "type": msg_type,
            "from": sender,
            "content": content,
            "timestamp": time.time(),
        }
        if extra:
            msg.update(extra)

        inbox_path = self.dir / f"{to}.jsonl"
        with open(inbox_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")

        return f"Sent {msg_type} to {to}"

    def read_inbox(self, name: str) -> list[dict]:
        inbox_path = self.dir / f"{name}.jsonl"
        if not inbox_path.exists():
            return []

        messages = []
        for line in inbox_path.read_text(encoding="utf-8").strip().splitlines():
            if line:
                with suppress(json.JSONDecodeError):
                    messages.append(json.loads(line))

        # drain after reading
        inbox_path.write_text("", encoding="utf-8")
        return messages

    def broadcast(self, sender: str, content: str, teammates: list[str]) -> str:
        count = 0
        for name in teammates:
            if name != sender:
                self.send(sender, name, content, "broadcast")
                count += 1
        return f"Broadcast to {count} teammates"

    def count_pending(self, name: str) -> int:
        inbox_path = self.dir / f"{name}.jsonl"
        if not inbox_path.exists():
            return 0
        return len(
            [line for line in inbox_path.read_text(encoding="utf-8").strip().splitlines() if line]
        )
