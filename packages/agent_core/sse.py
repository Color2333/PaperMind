"""
SSE 事件格式化工具
@author Color2333
"""

from __future__ import annotations

import json


def make_sse(event: str, data: dict) -> str:
    """格式化 SSE 事件"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
