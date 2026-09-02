"""UUIDv7 id 生成 — research state 表的时间有序主键

Python 3.11 stdlib 尚无 uuid7，这里按 RFC 9562 手写：
48 bit unix 毫秒 + 4 bit version(7) + 12 bit rand_a + 2 bit variant + 62 bit rand_b。
输出 32 位 hex（无连字符），与既有 String(36) hex 主键风格一致；
同毫秒内靠随机位区分，跨毫秒严格按时间排序，分页/diff 不再依赖第二排序键。
"""

from __future__ import annotations

import os
import time
import uuid


def new_id() -> str:
    """生成 UUIDv7 的 32 位 hex 字符串"""
    ts_ms = time.time_ns() // 1_000_000
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & 0x3FFF_FFFF_FFFF_FFFF
    value = (ts_ms & 0xFFFF_FFFF_FFFF) << 80
    value |= 0x7 << 76  # version 7
    value |= rand_a << 64
    value |= 0b10 << 62  # variant
    value |= rand_b
    return uuid.UUID(int=value).hex
