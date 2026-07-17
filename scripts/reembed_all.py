#!/usr/bin/env python3
"""
全量重新嵌入 - 把所有论文的 embedding 统一重算为当前 embedding provider 的向量。

背景：历史上换过多个 embedding provider（智谱 embedding-3=2048维 / 阿里百炼
text-embedding-v4=1024维 / 伪向量兜底=1536维），维度混存导致召回时 zip 静默截断。
切换到硅基流动 bge-m3（固定 1024 维）后，用本脚本把库里所有 embedding 重算对齐。

embed_paper 是幂等覆盖（update_embedding 直接覆写 embedding 列），所以不需要
先清状态，直接重跑即可。

@author Color2333

使用方式:
    # 预览要处理的论文数量（不实际调用）
    python scripts/reembed_all.py --dry-run

    # 处理全部论文
    python scripts/reembed_all.py

    # 只处理 embedding 为空或维度不对的（跳过已经是 1024 维的）
    python scripts/reembed_all.py --only-mismatched

    # 限制处理数量 + 调整并发
    python scripts/reembed_all.py --limit 100 --concurrency 5
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

# 让脚本能直接 `python scripts/x.py` 运行（不依赖 PYTHONPATH 环境变量）
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select

from packages.ai.pipelines import PaperPipelines
from packages.ai.rate_limiter import acquire_api
from packages.storage.db import _is_sqlite, session_scope
from packages.storage.models import Paper


def _embedding_dim_expr():
    """方言通用的 embedding 维度计算表达式。

    - SQLite：json_array_length(embedding)（NULL 兜底 0）
    - PostgreSQL：jsonb_array_length(embedding)（NULL 兜底 0）
    """
    if _is_sqlite:
        return func.coalesce(func.json_array_length(Paper.embedding), 0)
    return func.coalesce(func.jsonb_array_length(Paper.embedding), 0)


# 目标维度（bge-m3 固定 1024 维）
TARGET_DIM = 1024

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def get_all_papers(
    limit: int = 0, only_mismatched: bool = False
) -> list[tuple[str, str, int | None]]:
    """
    获取待重嵌入的论文列表。

    Args:
        limit: 限制数量，0 表示不限制
        only_mismatched: 只返回 embedding 为空或维度 != TARGET_DIM 的论文

    Returns:
        list: [(paper_id, title, current_dim), ...]
    """
    with session_scope() as session:
        stmt = select(Paper.id, Paper.title, Paper.embedding)
        if only_mismatched:
            # 方言通用的 embedding 维度表达式（NULL 兜底 0）
            stmt = stmt.where(_embedding_dim_expr() != TARGET_DIM)
        stmt = stmt.order_by(Paper.created_at.asc())
        if limit > 0:
            stmt = stmt.limit(limit)

        rows = session.execute(stmt).all()
        result = []
        for r in rows:
            dim = len(r.embedding) if r.embedding else None
            result.append((str(r.id), r.title, dim))
        return result


def reembed_single(paper_id: str, title: str) -> dict:
    """
    重新嵌入单篇论文。

    Returns:
        dict: 处理结果
    """
    pipelines = PaperPipelines()
    result = {
        "paper_id": paper_id[:8],
        "title": title[:50],
        "embed_success": False,
        "new_dim": None,
        "error": None,
    }

    try:
        logger.info(f"📌 [{paper_id[:8]}] 开始重嵌入...")
        if not acquire_api("embedding", timeout=30.0):
            result["error"] = "Embedding API 限流"
            logger.warning(f"⚠️  [{paper_id[:8]}] API 限流，跳过")
            return result

        pipelines.embed_paper(paper_id)
        result["embed_success"] = True

        # 读回新向量维度确认
        with session_scope() as session:
            row = session.execute(
                select(Paper.embedding).where(Paper.id == paper_id)
            ).scalar_one_or_none()
            result["new_dim"] = len(row) if row else None

        logger.info(f"✅ [{paper_id[:8]}] 重嵌入完成 (新维度={result['new_dim']})")
    except Exception as e:
        result["error"] = f"embed: {e}"
        logger.warning(f"❌ [{paper_id[:8]}] 重嵌入失败：{e}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="全量重新嵌入 - 统一所有论文的 embedding 维度",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 预览数量（不调用 API）
  python scripts/reembed_all.py --dry-run

  # 处理全部论文
  python scripts/reembed_all.py

  # 只处理维度不对的（跳过已经是 1024 维的）
  python scripts/reembed_all.py --only-mismatched
        """,
    )
    parser.add_argument("--limit", type=int, default=0, help="限制处理数量 (0=不限制)")
    parser.add_argument("--concurrency", type=int, default=3, help="并发数 (默认 3，避免 API 限流)")
    parser.add_argument(
        "--only-mismatched",
        action="store_true",
        help="只处理 embedding 为空或维度 != 1024 的论文",
    )
    parser.add_argument("--dry-run", action="store_true", help="只显示数量，不实际处理")
    args = parser.parse_args()

    print("=" * 70)
    print("🚀 PaperMind 全量重嵌入工具 (bge-m3 1024维对齐)")
    print("=" * 70)
    print()

    papers = get_all_papers(limit=args.limit, only_mismatched=args.only_mismatched)

    if not papers:
        print("✅ 没有需要重嵌入的论文！")
        return

    # 统计当前维度分布
    dim_dist: dict[int | None, int] = {}
    for _, _, dim in papers:
        dim_dist[dim] = dim_dist.get(dim, 0) + 1

    print(f"📊 找到 {len(papers)} 篇待重嵌入论文")
    print(f"⚡ 并发数：{args.concurrency}")
    print(f"🎯 目标维度：{TARGET_DIM} (bge-m3)")
    print("📋 当前维度分布：")
    for dim, n in sorted(dim_dist.items(), key=lambda x: (x[0] is not None, x[0] or 0)):
        label = f"{dim}维" if dim else "空(NULL)"
        flag = "  ✅" if dim == TARGET_DIM else "  ❌需重算"
        print(f"    {label:10} -> {n}{flag}")
    print()

    if args.dry_run:
        print("🔍 前 10 篇预览:")
        for i, (_pid, title, dim) in enumerate(papers[:10], 1):
            print(f"  {i:2d}. [{dim or '空'}] {title[:60]}")
        print()
        print("（使用 --dry-run 预览，移除该参数开始处理）")
        return

    # 批量处理
    results = []
    start_time = datetime.now(UTC)

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {executor.submit(reembed_single, pid, title): pid for pid, title, _ in papers}

        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            results.append(result)

            if i % 10 == 0 or i == len(papers):
                ok = sum(1 for r in results if r["embed_success"])
                fail = sum(1 for r in results if r["error"])
                elapsed = (datetime.now(UTC) - start_time).total_seconds()
                eta = (elapsed / i * (len(papers) - i)) if i > 0 else 0
                logger.info(
                    f"进度：{i}/{len(papers)} | 成功：{ok} | 失败：{fail} | 预计剩余：{eta:.0f}s"
                )

    # 统计
    print()
    print("=" * 70)
    print("📋 重嵌入结果统计")
    print("=" * 70)

    total = len(results)
    ok = sum(1 for r in results if r["embed_success"])
    fail = sum(1 for r in results if r["error"])
    elapsed = (datetime.now(UTC) - start_time).total_seconds()

    # 新维度分布
    new_dim_dist: dict[int | None, int] = {}
    for r in results:
        if r["embed_success"]:
            d = r["new_dim"]
            new_dim_dist[d] = new_dim_dist.get(d, 0) + 1

    print(f"总处理：{total} 篇")
    print(f"✅ 成功：{ok} ({ok / total * 100:.1f}%)")
    print(f"❌ 失败：{fail} ({fail / total * 100:.1f}%)")
    print(f"⏱️  总耗时：{elapsed:.1f}秒 ({elapsed / total:.1f}秒/篇)")
    print("📊 重嵌入后维度分布：")
    for dim, n in sorted(new_dim_dist.items(), key=lambda x: x[0] or 0):
        flag = "  ✅对齐" if dim == TARGET_DIM else "  ❌未对齐"
        print(f"    {dim}维 -> {n}{flag}")
    print()

    if fail > 0:
        print("⚠️  以下论文重嵌入失败:")
        for r in results:
            if r["error"]:
                print(f"  - {r['title'][:40]}... : {r['error']}")
        print()

    aligned = new_dim_dist.get(TARGET_DIM, 0)
    print(f"✨ 完成！{aligned}/{total} 已对齐到 {TARGET_DIM} 维")


if __name__ == "__main__":
    main()
