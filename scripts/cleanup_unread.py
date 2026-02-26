#!/usr/bin/env python3
"""
定期清理未读论文 - 批量粗读 + 嵌入（不精读）
@author Color2333

使用方式:
    # 处理 20 篇（默认）
    python scripts/cleanup_unread.py

    # 处理 50 篇，并发 5 个
    python scripts/cleanup_unread.py --limit 50 --concurrency 5

    # 添加到 crontab（每天 UTC 14 点执行，北京时间 22 点）
    0 14 * * * cd /path/to/PaperMind && /path/to/venv/bin/python scripts/cleanup_unread.py --limit 30
"""

from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from packages.ai.pipelines import PaperPipelines
from packages.ai.rate_limiter import acquire_api, get_rate_limiter
from packages.config import get_settings
from packages.storage.db import session_scope
from packages.storage.models import Paper, AnalysisReport
from sqlalchemy import select

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def get_unread_papers(limit: int = 50) -> list[tuple[str, str, str]]:
    """
    获取未读且未处理的论文列表

    Returns:
        list: [(paper_id, title, arxiv_id), ...]
    """
    with session_scope() as session:
        # 查询未读论文，左连接分析表，筛选没有分析的
        papers = session.execute(
            select(Paper.id, Paper.title, Paper.arxiv_id)
            .where(Paper.read_status == "unread")
            .outerjoin(AnalysisReport, Paper.id == AnalysisReport.paper_id)
            .where((AnalysisReport.summary_md.is_(None)) | (AnalysisReport.id.is_(None)))
            .order_by(Paper.created_at.asc())  # 优先处理旧的
            .limit(limit)
        ).all()
        return [(str(p.id), p.title, p.arxiv_id) for p in papers]


def process_single_paper(paper_id: str, title: str, arxiv_id: str) -> dict:
    """
    处理单篇论文：只粗读 + 嵌入，不精读

    Returns:
        dict: 处理结果
    """
    pipelines = PaperPipelines()
    result = {
        "paper_id": paper_id[:8],
        "title": title[:50],
        "arxiv_id": arxiv_id,
        "skim_success": False,
        "embed_success": False,
        "skim_score": None,
        "error": None,
    }

    try:
        # Step 1: 嵌入
        logger.info(f"📌 [{paper_id[:8]}] 开始嵌入...")
        try:
            if acquire_api("embedding", timeout=30.0):
                pipelines.embed_paper(paper_id)
                result["embed_success"] = True
                logger.info(f"✅ [{paper_id[:8]}] 嵌入完成")
            else:
                result["error"] = "Embedding API 限流"
                logger.warning(f"⚠️  [{paper_id[:8]}] Embedding API 限流，跳过")
        except Exception as e:
            result["error"] = f"embed: {e}"
            logger.warning(f"❌ [{paper_id[:8]}] 嵌入失败：{e}")

        # Step 2: 粗读
        logger.info(f"📖 [{paper_id[:8]}] 开始粗读...")
        try:
            if acquire_api("llm", timeout=30.0):
                skim_result = pipelines.skim(paper_id)
                result["skim_success"] = True
                if skim_result and skim_result.relevance_score:
                    result["skim_score"] = skim_result.relevance_score
                    logger.info(
                        f"✅ [{paper_id[:8]}] 粗读完成 (分数={skim_result.relevance_score:.2f})"
                    )
                else:
                    logger.info(f"✅ [{paper_id[:8]}] 粗读完成 (分数=N/A)")
            else:
                result["error"] = "LLM API 限流"
                logger.warning(f"⚠️  [{paper_id[:8]}] LLM API 限流，跳过粗读")
        except Exception as e:
            result["error"] = f"skim: {e}"
            logger.warning(f"❌ [{paper_id[:8]}] 粗读失败：{e}")

    except Exception as e:
        result["error"] = str(e)
        logger.exception(f"❌ [{paper_id[:8]}] 处理异常：{e}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="批量处理未读论文 - 只粗读 + 嵌入，不精读",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 处理 20 篇（默认）
  python scripts/cleanup_unread.py
  
  # 处理 50 篇，并发 5 个
  python scripts/cleanup_unread.py --limit 50 --concurrency 5
  
  # 添加到 crontab（每天 UTC 14 点执行）
  0 14 * * * cd /path/to/PaperMind && /path/to/venv/bin/python scripts/cleanup_unread.py --limit 30
        """,
    )
    parser.add_argument("--limit", type=int, default=20, help="每次处理的论文数量 (默认 20)")
    parser.add_argument(
        "--concurrency", type=int, default=3, help="并发处理数量 (默认 3，避免 LLM 限流)"
    )
    parser.add_argument("--dry-run", action="store_true", help="只显示待处理论文，不执行处理")
    args = parser.parse_args()

    print("=" * 70)
    print("🚀 PaperMind 未读论文批量处理器")
    print("=" * 70)
    print()

    # 获取待处理论文
    papers = get_unread_papers(limit=args.limit)

    if not papers:
        print("✅ 没有需要处理的未读论文！")
        print()
        print("所有未读论文都已经完成粗读和嵌入处理。")
        return

    print(f"📊 找到 {len(papers)} 篇待处理论文")
    print(f"⚡ 并发数：{args.concurrency}")
    print(f"📋 处理模式：粗读 + 嵌入 (不精读)")
    print()

    if args.dry_run:
        print("🔍 待处理论文列表:")
        for i, (pid, title, arxiv_id) in enumerate(papers, 1):
            print(f"  {i:2d}. {title[:60]}")
            print(f"      ID: {pid[:8]}... | arXiv: {arxiv_id}")
        print()
        print("（使用 --dry-run 预览，移除该参数开始处理）")
        return

    # 批量处理
    results = []
    start_time = datetime.now(timezone.utc)

    limiter = get_rate_limiter()

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {
            executor.submit(process_single_paper, pid, title, arxiv_id): pid
            for pid, title, arxiv_id in papers
        }

        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            results.append(result)

            # 进度汇报
            if i % 5 == 0 or i == len(papers):
                success = sum(1 for r in results if r["skim_success"] and r["embed_success"])
                partial = sum(1 for r in results if r["skim_success"] or r["embed_success"])
                errors = sum(1 for r in results if r["error"])

                elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                eta = (elapsed / i * (len(papers) - i)) if i > 0 else 0

                logger.info(
                    f"进度：{i}/{len(papers)} | "
                    f"成功：{success} | 部分：{partial} | 失败：{errors} | "
                    f"预计剩余：{eta:.0f}s"
                )

    # 统计结果
    print()
    print("=" * 70)
    print("📋 处理结果统计")
    print("=" * 70)

    total = len(results)
    embed_ok = sum(1 for r in results if r["embed_success"])
    skim_ok = sum(1 for r in results if r["skim_success"])
    both_ok = sum(1 for r in results if r["skim_success"] and r["embed_success"])
    errors = sum(1 for r in results if r["error"])

    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

    print(f"总处理：{total} 篇")
    print(f"✅ 嵌入成功：{embed_ok} ({embed_ok / total * 100:.1f}%)")
    print(f"✅ 粗读成功：{skim_ok} ({skim_ok / total * 100:.1f}%)")
    print(f"✅ 全部完成：{both_ok} ({both_ok / total * 100:.1f}%)")
    print(f"❌ 出现错误：{errors} ({errors / total * 100:.1f}%)")
    print(f"⏱️  总耗时：{elapsed:.1f}秒")
    print(f"⚡ 平均速度：{elapsed / total:.1f}秒/篇")
    print()

    # 显示失败的
    if errors > 0:
        print("⚠️  以下论文处理失败:")
        for r in results:
            if r["error"]:
                print(f"  - {r['title'][:40]}... : {r['error']}")
        print()

    # 高分论文提示
    high_score_papers = [
        r for r in results if r["skim_success"] and r["skim_score"] and r["skim_score"] >= 0.8
    ]
    if high_score_papers:
        print("🎯 发现高分论文（建议精读）:")
        for r in high_score_papers:
            print(f"  - {r['title'][:40]}... (分数={r['skim_score']:.2f})")
        print()

    print("✨ 批量处理完成！")
    print()
    print("💡 提示:")
    print("  • 可以在前端手动触发高分论文的精读")
    print("  • 或添加定时任务定期执行此脚本")
    print("  • 推荐配置：每天 UTC 14 点处理 30 篇")
    print()


if __name__ == "__main__":
    main()
