"""图谱分析共享静态辅助函数。"""

from __future__ import annotations

import re
from collections import defaultdict


def _normalize_arxiv_id(arxiv_id: str | None) -> str | None:
    """去版本号归一化: '2502.12082v2' -> '2502.12082'"""
    if not arxiv_id:
        return None
    return re.sub(r"v\d+$", "", arxiv_id.strip())


def _title_to_id(title: str) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "-" for ch in title).strip("-")
    return f"ss-{normalized[:48]}"


def _pagerank(nodes: list[str], edges: list) -> dict[str, float]:
    if not nodes:
        return {}
    node_set = set(nodes)
    outgoing: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        if e.source_paper_id in node_set and e.target_paper_id in node_set:
            outgoing[e.source_paper_id].append(e.target_paper_id)
    n = len(nodes)
    rank = dict.fromkeys(nodes, 1.0 / n)
    damping = 0.85
    for _ in range(20):
        next_rank = dict.fromkeys(nodes, (1.0 - damping) / n)
        for node in nodes:
            refs = outgoing.get(node, [])
            if not refs:
                continue
            share = rank[node] / len(refs)
            for dst in refs:
                next_rank[dst] += damping * share
        rank = next_rank
    return rank


def _milestones_by_year(
    items: list[dict],
) -> list[dict]:
    best_per_year: dict[int, dict] = {}
    for x in items:
        year = x["year"]
        if year not in best_per_year or x["seminal_score"] > best_per_year[year]["seminal_score"]:
            best_per_year[year] = x
    return [best_per_year[y] for y in sorted(best_per_year.keys())]
