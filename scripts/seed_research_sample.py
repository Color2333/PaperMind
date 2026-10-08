"""Research State 垂直切片样本种子 CLI（A4/D2）

核心逻辑在 packages/ai/seed_research.py（可导入、可测试）；本脚本只是命令行包装。

用法：
  python scripts/seed_research_sample.py --dry-run                 # 只预览
  python scripts/seed_research_sample.py                           # 取最近已 skim 的 3 篇
  python scripts/seed_research_sample.py --arxiv-id 2608.10001 ... # 指定切片论文
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_research_sample")


def main() -> None:
    parser = argparse.ArgumentParser(description="Research State 垂直切片样本种子")
    parser.add_argument(
        "--arxiv-id",
        action="append",
        default=None,
        help="切片论文 arxiv_id（可多次传入）；缺省取最近已 skim 的 3 篇",
    )
    parser.add_argument("--dry-run", action="store_true", help="只预览不写入")
    args = parser.parse_args()

    from packages.ai.seed_research import seed_sample
    from packages.storage.db import session_scope

    with session_scope() as session:
        stats = seed_sample(session, arxiv_ids=args.arxiv_id, dry_run=args.dry_run)
    logger.info("结果：%s", stats)


if __name__ == "__main__":
    main()
