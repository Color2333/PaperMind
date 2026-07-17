#!/usr/bin/env python3
"""
重跑坏 skim 论文 - 修复 skim_score=0.5 的兜底坏数据。

背景：历史上智谱 glm-4.7 和小米 mimo-v2-omni 时期，部分论文 skim 时模型未真正
总结（返回 prompt 模板占位符 / relevance_score 缺失），代码用 get(...,0.5) 兜底，
产生 484 篇 skim_score 恰好 0.5 的坏数据。这些论文已被标记为 skimmed，idle_processor
永远不会再选中它们，必须主动重跑。

skim() 是幂等覆盖（upsert_skim 覆写 summary_md/skim_score），直接重跑即可。
本脚本只重跑 skim，不重嵌入（embedding 由 reembed_all.py 统一处理）。

@author Color2333

使用方式:
    # 预览坏论文数量（不调用 API）
    python scripts/reskim_bad.py --dry-run

    # 重跑全部 score=0.5 的坏论文
    python scripts/reskim_bad.py

    # 限制数量 + 调整并发
    python scripts/reskim_bad.py --limit 50 --concurrency 5
"""

from __future__ import annotations

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

from sqlalchemy import select

from packages.ai.pipelines import PaperPipelines
from packages.ai.rate_limiter import acquire_api
from packages.storage.db import session_scope
from packages.storage.models import AnalysisReport, Paper

# 坏 skim 的判定值：兜底分数恰好 0.5
BAD_SCORE = 0.5

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def get_bad_skim_papers(limit: int = 0) -> list[tuple[str, str]]:
    """
    获取 skim_score 恰好 0.5 的已 skim 论文（兜底坏数据）。

    Returns:
        list: [(paper_id, title), ...]
    """
    with session_scope() as session:
        stmt = (
            select(Paper.id, Paper.title)
            .join(AnalysisReport, AnalysisReport.paper_id == Paper.id)
            .where(AnalysisReport.skim_score == BAD_SCORE)
            .where(Paper.read_status == "skimmed")
            .order_by(Paper.created_at.asc())
        )
        if limit > 0:
            stmt = stmt.limit(limit)
        rows = session.execute(stmt).all()
        return [(str(r.id), r.title) for r in rows]


def reskim_single(paper_id: str, title: str) -> dict:
    """
    重新粗读单篇论文。

    Returns:
        dict: 处理结果
    """
    pipelines = PaperPipelines()
    result = {
        "paper_id": paper_id[:8],
        "title": title[:50],
        "skim_success": False,
        "old_score": BAD_SCORE,
        "new_score": None,
        "is_template": False,  # 是否仍是模板占位符
        "error": None,
    }

    try:
        logger.info(f"📖 [{paper_id[:8]}] 开始重粗读...")
        if not acquire_api("llm", timeout=30.0):
            result["error"] = "LLM API 限流"
            logger.warning(f"⚠️  [{paper_id[:8]}] API 限流，跳过")
            return result

        skim_result = pipelines.skim(paper_id)
        result["skim_success"] = True

        if skim_result and skim_result.relevance_score is not None:
            result["new_score"] = skim_result.relevance_score
            logger.info(
                f"✅ [{paper_id[:8]}] 重粗读完成 "
                f"(旧={BAD_SCORE} → 新={skim_result.relevance_score:.2f})"
            )

            # 检查新结果是否还是模板占位符（SkimReport.one_liner 是一句话总结）
            one_liner = getattr(skim_result, "one_liner", "") or ""
            if "一句话中文总结" in one_liner or not one_liner.strip():
                result["is_template"] = True
                logger.warning(f"⚠️  [{paper_id[:8]}] 新结果仍是模板占位符！")
        else:
            logger.info(f"✅ [{paper_id[:8]}] 重粗读完成 (分数=N/A)")
    except Exception as e:
        result["error"] = f"skim: {e}"
        logger.warning(f"❌ [{paper_id[:8]}] 重粗读失败：{e}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="重跑坏 skim 论文 - 修复 skim_score=0.5 的兜底数据",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 预览坏论文数量（不调用 API）
  python scripts/reskim_bad.py --dry-run

  # 重跑全部
  python scripts/reskim_bad.py

  # 限制数量 + 调整并发
  python scripts/reskim_bad.py --limit 50 --concurrency 5
        """,
    )
    parser.add_argument("--limit", type=int, default=0, help="限制处理数量 (0=不限制)")
    parser.add_argument("--concurrency", type=int, default=3, help="并发数 (默认 3，避免 LLM 限流)")
    parser.add_argument("--dry-run", action="store_true", help="只显示数量，不实际处理")
    args = parser.parse_args()

    print("=" * 70)
    print("🚀 PaperMind 坏 skim 重跑工具 (修复 score=0.5 兜底数据)")
    print("=" * 70)
    print()

    papers = get_bad_skim_papers(limit=args.limit)

    if not papers:
        print("✅ 没有需要重跑的坏 skim 论文！")
        return

    print(f"📊 找到 {len(papers)} 篇 skim_score={BAD_SCORE} 的坏论文")
    print(f"⚡ 并发数：{args.concurrency}")
    print("🎯 模型：当前 .env 配置的 LLM_MODEL_SKIM (mimo-v2.5)")
    print()

    if args.dry_run:
        print("🔍 前 10 篇预览:")
        for i, (pid, title) in enumerate(papers[:10], 1):
            print(f"  {i:2d}. [{pid[:8]}] {title[:60]}")
        print()
        print("（使用 --dry-run 预览，移除该参数开始处理）")
        return

    # 批量处理
    results = []
    start_time = datetime.now(UTC)

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {executor.submit(reskim_single, pid, title): pid for pid, title in papers}

        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            results.append(result)

            if i % 10 == 0 or i == len(papers):
                ok = sum(1 for r in results if r["skim_success"])
                still_bad = sum(1 for r in results if r["new_score"] == BAD_SCORE)
                fail = sum(1 for r in results if r["error"])
                elapsed = (datetime.now(UTC) - start_time).total_seconds()
                eta = (elapsed / i * (len(papers) - i)) if i > 0 else 0
                logger.info(
                    f"进度：{i}/{len(papers)} | 成功：{ok} | 仍坏：{still_bad} | "
                    f"失败：{fail} | 预计剩余：{eta:.0f}s"
                )

    # 统计
    print()
    print("=" * 70)
    print("📋 重跑结果统计")
    print("=" * 70)

    total = len(results)
    ok = sum(1 for r in results if r["skim_success"])
    fail = sum(1 for r in results if r["error"])
    elapsed = (datetime.now(UTC) - start_time).total_seconds()

    # 新分数分布
    still_bad = sum(1 for r in results if r["new_score"] == BAD_SCORE)
    fixed = sum(1 for r in results if r["skim_success"] and r["new_score"] != BAD_SCORE)
    template = sum(1 for r in results if r["is_template"])

    print(f"总处理：{total} 篇")
    print(f"✅ 已修复（新分数≠0.5）：{fixed} ({fixed / total * 100:.1f}%)")
    print(f"⚠️  仍是 0.5：{still_bad} ({still_bad / total * 100:.1f}%)")
    print(f"⚠️  仍是模板占位符：{template}")
    print(f"❌ 失败：{fail} ({fail / total * 100:.1f}%)")
    print(f"⏱️  总耗时：{elapsed:.1f}秒 ({elapsed / total:.1f}秒/篇)")
    print()

    if fail > 0:
        print("⚠️  以下论文重跑失败:")
        for r in results:
            if r["error"]:
                print(f"  - {r['title'][:40]}... : {r['error']}")
        print()

    if still_bad > 0:
        print(f"⚠️  仍有 {still_bad} 篇分数=0.5，可能模型仍未正常工作，请检查 LLM_MODEL_SKIM 配置")
        print()

    print(f"✨ 完成！{fixed}/{total} 已修复")


if __name__ == "__main__":
    main()
