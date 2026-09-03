#!/usr/bin/env python3
"""导出 capability metadata JSON（E5，构建期供 TS 侧 @papermind/presentation 生成类型）"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from packages.application.capability import export_capability_metadata


def main() -> None:
    out_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "packages", "application"
    )
    out_path = os.path.join(out_dir, "capability_metadata.json")
    data = export_capability_metadata()
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(data)
    print(f"capability metadata exported to {out_path} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
