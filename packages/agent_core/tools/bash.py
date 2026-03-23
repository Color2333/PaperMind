"""
bash — Bash 工具 handler，参考 learn-claude-code s01
"""

from __future__ import annotations

import subprocess

DANGEROUS_PATTERNS = [
    "rm -rf /",
    "sudo",
    "shutdown",
    "reboot",
    "> /dev/",
    "| /dev/",
]


def run_bash(command: str, cwd: str | None = None, timeout: int = 120) -> str:
    """
    执行 Bash 命令。
    包含危险命令检查，防止误执行破坏性操作。
    """
    for pattern in DANGEROUS_PATTERNS:
        if pattern in command:
            return f"Error: Dangerous command blocked: '{pattern}' found in command"

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (result.stdout + result.stderr).strip()
        return out if out else "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: Timeout ({timeout}s exceeded)"
    except Exception as exc:  # noqa: BLE001
        return f"Error: {type(exc).__name__}: {exc}"
