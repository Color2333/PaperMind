#!/usr/bin/env python3
"""
批量处理未读论文 - 粗读 + 嵌入
@author Color2333
"""

from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from packages.ai.pipelines import PaperPipelines
from packages.config import get_settings
from packages.storage.db import session_scope
from packages.storage.models import Paper, AnalysisReport
from packages.storage.repositories import AnalysisRepository
from sqlalchemy import select

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def get_unread_papers(limit: int = 50) -> list[tuple[str, str, str]]:
    """获取未读且未处理的论文列表"""
    with session_scope() as session:
        # 查询未读论文，左连接分析表，筛选没有分析的
        papers = session.execute(
            select(Paper.id, Paper.title, Paper.arxiv_id)
            .where(Paper.read_status == "unread")
            .outerjoin(AnalysisReport, Paper.id == AnalysisReport.paper_id)
            .where((AnalysisReport.summary_md.is_(None)) | (AnalysisReport.id.is_(None)))
            .order_by(Paper.created_at.desc())
            .limit(limit)
        ).all()
        return [(p.id, p.title, p.arxiv_id) for p in papers]


def process_single_paper(paper_id: str, title: str) -> dict:
    """处理单篇论文：embed + skim 并行"""
    pipelines = PaperPipelines()
    result = {
        "paper_id": paper_id,
        "title": title[:50],
        "skim_success": False,
        "embed_success": False,
        "error": None,
    }

    try:
        # embed 和 skim 并行执行
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=2) as executor:
            embed_future = executor.submit(pipelines.embed_paper, paper_id)
            skim_future = executor.submit(pipelines.skim, paper_id)

            # 等待 embed 完成
            try:
                embed_future.result()
                result["embed_success"] = True
                logger.info(f"✅ {title[:40]}... 嵌入完成")
            except Exception as e:
                result["error"] = f"embed: {e}"
                logger.warning(f"❌ {title[:40]}... 嵌入失败：{e}")

            # 等待 skim 完成
            try:
                skim_result = skim_future.result()
                result["skim_success"] = True
                if skim_result and skim_result.relevance_score:
                    result["relevance_score"] = skim_result.relevance_score
                logger.info(
                    f"✅ {title[:40]}... 粗读完成 (分数：{skim_result.relevance_score if skim_result else 'N/A'})"
                )
            except Exception as e:
                result["error"] = f"skim: {e}"
                logger.warning(f"❌ {title[:40]}... 粗读失败：{e}")

        # 如果粗读分数高，自动精读
        if result["skim_success"] and result.get("relevance_score", 0) >= 0.65:
            try:
                pipelines.deep_dive(paper_id)
                result["deep_success"] = True
                logger.info(f"🎯 {title[:40]}... 自动精读完成 (高分论文)")
            except Exception as e:
                logger.warning(f"⚠️  {title[:40]}... 精读失败：{e}")
                result["deep_success"] = False

    except Exception as e:
        result["error"] = str(e)
        logger.exception(f"❌ {title[:40]}... 处理异常：{e}")

    return result


def main():
    parser = argparse.ArgumentParser(description="批量处理未读论文")
    parser.add_argument("--limit", type=int, default=20, help="每次处理的论文数量 (默认 20)")
    parser.add_argument(
        "--concurrency", type=int, default=3, help="并发处理数量 (默认 3，避免 LLM 限流)"
    )
    parser.add_argument("--auto-deep", action="store_true", help="粗读分数>=0.65 时自动精读")
    args = parser.parse_args()

    print("=" * 60)
    print("🚀 PaperMind 批量论文处理器")
    print("=" * 60)
    print()

    # 获取待处理论文
    papers = get_unread_papers(limit=args.limit)

    if not papers:
        print("✅ 没有需要处理的未读论文！")
        return

    print(f"📊 找到 {len(papers)} 篇待处理论文")
    print(f"⚡ 并发数：{args.concurrency}")
    print(f"🎯 自动精读：{'开启' if args.auto_deep else '关闭'}")
    print()

    # 批量处理
    results = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {
            executor.submit(process_single_paper, pid, title): pid
            for pid, title, arxiv_id in papers
        }

        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            results.append(result)

            # 进度汇报
            if i % 5 == 0 or i == len(papers):
                success = sum(1 for r in results if r["skim_success"] and r["embed_success"])
                logger.info(f"进度：{i}/{len(papers)} | 成功：{success} | 失败：{i - success}")

    # 统计结果
    print()
    print("=" * 60)
    print("📋 处理结果统计")
    print("=" * 60)

    total = len(results)
    skim_ok = sum(1 for r in results if r["skim_success"])
    embed_ok = sum(1 for r in results if r["embed_success"])
    deep_ok = sum(1 for r in results if r.get("deep_success", False))
    errors = sum(1 for r in results if r["error"])

    print(f"总处理：{total} 篇")
    print(f"✅ 粗读成功：{skim_ok} ({skim_ok / total * 100:.1f}%)")
    print(f"✅ 嵌入成功：{embed_ok} ({embed_ok / total * 100:.1f}%)")
    print(f"🎯 自动精读：{deep_ok}")
    print(f"❌ 出现错误：{errors} ({errors / total * 100:.1f}%)")
    print()

    # 显示失败的论文
    if errors > 0:
        print("⚠️  以下论文处理失败:")
        for r in results:
            if r["error"]:
                print(f"  - {r['title'][:40]}... : {r['error']}")
        print()

    print("✨ 批量处理完成！")


if __name__ == "__main__":
    main()
