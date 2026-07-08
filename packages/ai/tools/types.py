"""Agent 工具相关数据类型。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolResult:
    success: bool
    data: dict = field(default_factory=dict)
    summary: str = ""


@dataclass
class ToolProgress:
    """工具执行中间进度事件"""

    message: str
    current: int = 0
    total: int = 0


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict
    requires_confirm: bool = False
