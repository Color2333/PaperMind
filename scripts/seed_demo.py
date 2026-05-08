"""
Demo 站数据预灌脚本
@author Color2333

用法:
  DEMO_MODE=false python scripts/seed_demo.py --dry-run    # 先看会拉哪些
  DEMO_MODE=false python scripts/seed_demo.py --count 5     # 先 5 篇验证
  DEMO_MODE=false python scripts/seed_demo.py --count 30    # 实际入库 30 篇
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from uuid import UUID

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("seed_demo")

CATEGORIES = ["cs.AI", "cs.CL", "cs.CV"]
FAILED_LOG = os.path.join(project_root, "data", "seed_failed.txt")


def main():
    parser = argparse.ArgumentParser(description="PaperMind Demo 站数据预灌")
    parser.add_argument("--count", type=int, default=30, help="总入库论文数（每个类别均分）")
    parser.add_argument("--dry-run", action="store_true", help="只预览不实际入库")
    args = parser.parse_args()

    per_category = max(1, args.count // len(CATEGORIES))
    logger.info("目标: %d 篇 / %d 类别 = %d 篇/类别", args.count, len(CATEGORIES), per_category)

    from packages.ai.pipelines import PaperPipelines
    from packages.integrations.arxiv_client import ArxivClient

    arxiv = ArxivClient()
    pipelines = PaperPipelines()
    all_inserted: list[str] = []
    all_failed: list[str] = []

    for cat in CATEGORIES:
        query = f"cat:{cat}"
        logger.info("=== 抓取 %s ===", cat)

        try:
            papers = arxiv.fetch_latest(
                query=query,
                max_results=per_category * 2,
                sort_by="relevance",
                days_back=60,
            )
        except Exception as exc:
            logger.error("ArXiv 抓取失败 [%s]: %s", cat, exc)
            all_failed.append(f"[fetch] {cat}: {exc}")
            continue

        logger.info("ArXiv 返回 %d 篇", len(papers))

        for paper in papers[:per_category]:
            if args.dry_run:
                logger.info("[dry] %s: %s", cat, paper.title[:80])
                continue

            try:
                # 入库（ingest_arxiv 自带 upsert 去重）
                _, ids, _ = pipelines.ingest_arxiv(
                    query=f'ti:"{paper.title[:60]}"',
                    max_results=1,
                    sort_by="relevance",
                    days_back=0,
                )
                if not ids:
                    # 精确搜索没命中，用 arxiv_id 直接拉
                    if not paper.arxiv_id:
                        logger.warning("跳过 (无 arxiv_id)")
                        all_failed.append("[ingest] 无 arxiv_id")
                        continue
                    fetched = arxiv.fetch_by_ids([paper.arxiv_id])
                    if fetched:
                        from packages.storage.db import session_scope
                        from packages.storage.repositories import PaperRepository

                        with session_scope() as session:
                            repo = PaperRepository(session)
                            saved = repo.upsert_paper(fetched[0])
                            ids = [str(saved.id)]
                    else:
                        logger.warning("跳过 %s (无法入库)", paper.arxiv_id)
                        all_failed.append(f"[ingest] {paper.arxiv_id}: 无法入库")
                        continue

                paper_id = ids[0]
                logger.info("[ingested] %s → %s", paper.arxiv_id, paper.title[:60])

                # 向量化
                try:
                    pipelines.embed_paper(UUID(paper_id))
                    logger.info("[embedded] %s", paper.arxiv_id)
                except Exception as exc:
                    logger.warning("embed 失败 %s: %s", paper.arxiv_id, exc)
                    all_failed.append(f"[embed] {paper.arxiv_id}: {exc}")

                # 粗读（含关键词提取）
                try:
                    pipelines.skim(UUID(paper_id))
                    logger.info("[skimmed] %s", paper.arxiv_id)
                except Exception as exc:
                    logger.warning("skim 失败 %s: %s", paper.arxiv_id, exc)
                    all_failed.append(f"[skim] {paper.arxiv_id}: {exc}")

                all_inserted.append(paper_id)
                time.sleep(1)  # 避免触发 arXiv 限流

            except Exception as exc:
                logger.error("处理失败 %s: %s", paper.arxiv_id, exc)
                all_failed.append(f"[pipeline] {paper.arxiv_id}: {exc}")

    # 汇总
    logger.info("=" * 50)
    logger.info("完成! 成功: %d 篇, 失败: %d 条", len(all_inserted), len(all_failed))

    if all_failed:
        os.makedirs(os.path.dirname(FAILED_LOG), exist_ok=True)
        with open(FAILED_LOG, "w") as f:
            for line in all_failed:
                f.write(line + "\n")
        logger.info("失败记录写入: %s", FAILED_LOG)

    if args.dry_run:
        logger.info("(dry-run 模式，未实际入库)")


if __name__ == "__main__":
    main()
