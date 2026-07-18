#!/usr/bin/env python3
"""
补偿精读卡在 skimmed 的存量论文 - 一次性回填脚本。

背景：Critical #6 修复让 idle_processor 补偿 skimmed 未精读的论文，但补偿逻辑
此前挂在 _process_batch 末尾，无 unread 论文时提前 return 导致永远不触发。
库里积累 1239 篇卡在 skimmed（有 summary_md 但 deep_dive_md 空），其中 1233 篇
高分(>=0.8)。本脚本一次性回填这些存量论文，按 skim_score 降序优先精读高价值论文。

修复 idle 补偿 bug 后，新抓取的 stuck 论文由 idle_processor 自动补偿；本脚本只
处理修复前已卡住的存量。deep_dive 是幂等覆盖（upsert_deep_dive 覆写 deep_dive_md），
直接重跑安全。

@author Color2333

使用方式:
    # 预览要精读的论文数量（不调用 API）
    python scripts/redeep_stuck_skimmed.py --dry-run

    # 回填全部 stuck 论文（按分数降序）
    python scripts/redeep_stuck_skimmed.py

    # 限制数量（如先跑 100 篇）
    python scripts/redeep_stuck_skimmed.py --limit 100

    # 只回填高分(>=0.8)的
    python scripts/redeep_stuck_skimmed.py --min-score 0.8
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# 让脚本能直接 `python scripts/x.py` 运行（不依赖 PYTHONPATH 环境变量）
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from packages.ai.pipelines import PaperPipelines
from packages.ai.rate_limiter import acquire_api, get_rate_limiter
from packages.storage.db import session_scope
from packages.storage.models import AnalysisReport, Paper

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def get_stuck_skimmed_papers(
    limit: int = 0, min_score: float = 0.0
) -> list[tuple[str, str, float]]:
    """获取卡在 skimmed 未精读的论文（有 summary_md 但 deep_dive_md 空）。

    按 skim_score 降序，优先精读高价值论文。
    Returns: [(paper_id, title, skim_score), ...]
    """
    with session_scope() as session:
        stmt = (
            select(Paper.id, Paper.title, AnalysisReport.skim_score)
            .join(AnalysisReport, AnalysisReport.paper_id == Paper.id)
            .where(Paper.read_status == "skimmed")
            .where(AnalysisReport.summary_md.is_not(None))
            .where(AnalysisReport.deep_dive_md.is_(None))
            .where(AnalysisReport.skim_score >= min_score)
            .order_by(AnalysisReport.skim_score.desc())
        )
        if limit > 0:
            stmt = stmt.limit(limit)
        rows = session.execute(stmt).all()
        return [(str(r.id), r.title, r.skim_score or 0.0) for r in rows]


def redeep_single(paper_id: str, title: str, score: float) -> dict:
    """精读单篇论文。"""
    pipelines = PaperPipelines()
    limiter = get_rate_limiter()
    result = {
        "paper_id": paper_id[:8],
        "title": title[:50],
        "skim_score": score,
        "deep_success": False,
        "error": None,
    }

    if not limiter.start_task():
        result["error"] = "并发满"
        return result
    try:
        if not acquire_api("llm", timeout=30.0):
            result["error"] = "LLM API 限流"
            logger.warning(f"⚠️  [{paper_id[:8]}] LLM 限流，跳过")
            return result
        logger.info(f"📖 [{paper_id[:8]}] 开始精读 (skim={score:.2f}) {title[:40]}")
        pipelines.deep_dive(paper_id)
        result["deep_success"] = True
        logger.info(f"✅ [{paper_id[:8]}] 精读完成 (skim={score:.2f})")
    except Exception as exc:
        result["error"] = str(exc)[:120]
        logger.warning(f"❌ [{paper_id[:8]}] 精读失败: {exc}")
    finally:
        limiter.end_task()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="回填卡在 skimmed 未精读的存量论文")
    parser.add_argument("--dry-run", action="store_true", help="只统计不精读")
    parser.add_argument("--limit", type=int, default=0, help="限制处理数量（0=全部）")
    parser.add_argument("--min-score", type=float, default=0.0, help="只精读 skim_score >= 此值的")
    parser.add_argument("--concurrency", type=int, default=2, help="并发数")
    args = parser.parse_args()

    papers = get_stuck_skimmed_papers(limit=args.limit, min_score=args.min_score)
    logger.info(f"找到 {len(papers)} 篇卡在 skimmed 未精读的论文 (min_score={args.min_score})")

    if not papers:
        logger.info("无需回填")
        return

    # 分数分布预览
    high = sum(1 for _, _, s in papers if s >= 0.8)
    mid = sum(1 for _, _, s in papers if 0.65 <= s < 0.8)
    low = sum(1 for _, _, s in papers if s < 0.65)
    logger.info(f"分数分布: 高分(>=0.8)={high}, 中(0.65-0.8)={mid}, 低(<0.65)={low}")

    if args.dry_run:
        logger.info("dry-run 模式：不精读，退出")
        return

    success = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(redeep_single, pid, title, score): pid for pid, title, score in papers
        }
        for fut in as_completed(futures):
            r = fut.result()
            if r["deep_success"]:
                success += 1
            else:
                failed += 1

    logger.info(f"回填完成：成功={success}, 失败={failed}, 总计={len(papers)}")


if __name__ == "__main__":
    main()
