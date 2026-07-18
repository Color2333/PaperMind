#!/usr/bin/env python3
"""Worker 健康检查脚本（High 2e）。

读取 /tmp/worker_heartbeat（JSON {ts, error}），判定心跳时效：
- 文件不存在 / 解析失败 → 不健康（exit 1）
- ts 距今超过 1200 秒 → 不健康（worker 卡死或全部任务失败，心跳已过期）
- 否则健康（exit 0）

此前 healthcheck 仅 test -f 文件存在 → 即使所有 job 失败 worker 仍判健康。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HEALTH_FILE = Path("/tmp/worker_heartbeat")
STALE_SECONDS = 1200  # 20 分钟


def main() -> int:
    try:
        data = json.loads(HEALTH_FILE.read_text())
        ts = float(data.get("ts", 0))
    except (OSError, ValueError, TypeError):
        # 文件不存在或损坏 → 视为不健康
        return 1
    return 0 if (time.time() - ts) < STALE_SECONDS else 1


if __name__ == "__main__":
    sys.exit(main())
