"""全库概览与跨主题分析服务。"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

from packages.ai.graph._common import _pagerank
from packages.storage.db import session_scope
from packages.storage.models import PaperTopic
from packages.storage.repositories import (
    CitationRepository,
    PaperRepository,
    TopicRepository,
)

logger = logging.getLogger(__name__)


class OverviewService:
    def __init__(self) -> None:
        pass

    def library_overview(self) -> dict:
        """全库概览 — 节点 + 引用边 + PageRank + 统计"""
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            cit_repo = CitationRepository(session)
            topic_repo = TopicRepository(session)

            papers = paper_repo.list_lightweight(limit=50000)
            edges = cit_repo.list_all()
            topics = topic_repo.list_topics()
            topic_map = {t.id: t.name for t in topics}

            paper_ids = {p.id for p in papers}
            valid_edges = [
                e
                for e in edges
                if e.source_paper_id in paper_ids and e.target_paper_id in paper_ids
            ]

            in_deg: dict[str, int] = defaultdict(int)
            out_deg: dict[str, int] = defaultdict(int)
            for e in valid_edges:
                out_deg[e.source_paper_id] += 1
                in_deg[e.target_paper_id] += 1

            pagerank = _pagerank(list(paper_ids), valid_edges)

            from sqlalchemy import select as sa_select

            pt_rows = session.execute(sa_select(PaperTopic)).scalars().all()
            paper_topics: dict[str, list[str]] = defaultdict(list)
            for pt in pt_rows:
                tn = topic_map.get(pt.topic_id, "未分配")
                paper_topics[pt.paper_id].append(tn)

            nodes = []
            for p in papers:
                yr = p.publication_date.year if isinstance(p.publication_date, date) else None
                nodes.append(
                    {
                        "id": p.id,
                        "title": p.title,
                        "arxiv_id": p.arxiv_id,
                        "year": yr,
                        "in_degree": in_deg.get(p.id, 0),
                        "out_degree": out_deg.get(p.id, 0),
                        "pagerank": round(pagerank.get(p.id, 0), 6),
                        "topics": paper_topics.get(p.id, []),
                        "read_status": p.read_status.value if p.read_status else "unread",
                    }
                )

            edge_list = [
                {"source": e.source_paper_id, "target": e.target_paper_id} for e in valid_edges
            ]

            pr_sorted = sorted(nodes, key=lambda n: n["pagerank"], reverse=True)
            top_papers = pr_sorted[:10]

            topic_stats = defaultdict(lambda: {"count": 0, "edges": 0})
            for n in nodes:
                for t in n["topics"]:
                    topic_stats[t]["count"] += 1

            n_papers = len(nodes)
            max_e = n_papers * (n_papers - 1) if n_papers > 1 else 1

        return {
            "total_papers": n_papers,
            "total_edges": len(edge_list),
            "density": round(len(edge_list) / max_e, 6) if max_e else 0,
            "nodes": nodes,
            "edges": edge_list,
            "top_papers": top_papers,
            "topic_stats": dict(topic_stats),
        }

    def cross_topic_bridges(self) -> dict:
        """跨主题桥接论文 — 被多个主题的论文引用的关键论文"""
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            cit_repo = CitationRepository(session)
            topic_repo = TopicRepository(session)

            papers = paper_repo.list_lightweight(limit=50000)
            edges = cit_repo.list_all()
            topics = topic_repo.list_topics()
            topic_map = {t.id: t.name for t in topics}

            from sqlalchemy import select as sa_select

            pt_rows = session.execute(sa_select(PaperTopic)).scalars().all()
            paper_topic: dict[str, set[str]] = defaultdict(set)
            for pt in pt_rows:
                paper_topic[pt.paper_id].add(pt.topic_id)

            paper_ids = {p.id for p in papers}
            cited_by_topics: dict[str, set[str]] = defaultdict(set)
            for e in edges:
                if e.source_paper_id not in paper_ids:
                    continue
                if e.target_paper_id not in paper_ids:
                    continue
                src_topics = paper_topic.get(e.source_paper_id, set())
                for tid in src_topics:
                    cited_by_topics[e.target_paper_id].add(tid)

            bridges = []
            paper_map = {p.id: p for p in papers}
            for pid, tids in cited_by_topics.items():
                if len(tids) >= 2:
                    p = paper_map.get(pid)
                    if not p:
                        continue
                    bridges.append(
                        {
                            "id": pid,
                            "title": p.title,
                            "arxiv_id": p.arxiv_id,
                            "topics_citing": [topic_map.get(t, t) for t in tids],
                            "cross_topic_count": len(tids),
                            "own_topics": [
                                topic_map.get(t, t) for t in paper_topic.get(pid, set())
                            ],
                        }
                    )

            bridges.sort(key=lambda b: b["cross_topic_count"], reverse=True)

        return {"bridges": bridges[:30], "total": len(bridges)}

    def research_frontier(self, days: int = 90) -> dict:
        """研究前沿检测 — 近期高被引 + 引用速度快的论文"""
        from datetime import timedelta

        cutoff = date.today() - timedelta(days=days)

        with session_scope() as session:
            paper_repo = PaperRepository(session)
            cit_repo = CitationRepository(session)

            papers = paper_repo.list_lightweight(limit=50000)
            edges = cit_repo.list_all()
            paper_ids = {p.id for p in papers}

            in_deg: dict[str, int] = defaultdict(int)
            for e in edges:
                if e.target_paper_id in paper_ids:
                    in_deg[e.target_paper_id] += 1

            recent = [
                p
                for p in papers
                if isinstance(p.publication_date, date) and p.publication_date >= cutoff
            ]

            frontier = []
            for p in recent:
                age_days = max((date.today() - p.publication_date).days, 1)
                citations = in_deg.get(p.id, 0)
                velocity = round(citations / age_days * 30, 2)
                frontier.append(
                    {
                        "id": p.id,
                        "title": p.title,
                        "arxiv_id": p.arxiv_id,
                        "year": p.publication_date.year,
                        "publication_date": p.publication_date.isoformat(),
                        "citations_in_library": citations,
                        "citation_velocity": velocity,
                        "read_status": p.read_status.value if p.read_status else "unread",
                    }
                )

            frontier.sort(key=lambda f: f["citation_velocity"], reverse=True)

        return {
            "period_days": days,
            "total_recent": len(recent),
            "frontier": frontier[:30],
        }

    def cocitation_clusters(self, min_cocite: int = 2) -> dict:
        """共引聚类 — 被同一批论文引用的论文会聚在一起"""
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            cit_repo = CitationRepository(session)

            papers = paper_repo.list_lightweight(limit=50000)
            edges = cit_repo.list_all()
            paper_ids = {p.id for p in papers}
            paper_map = {p.id: p for p in papers}

            cited_by_map: dict[str, set[str]] = defaultdict(set)
            for e in edges:
                if e.source_paper_id in paper_ids and e.target_paper_id in paper_ids:
                    cited_by_map[e.target_paper_id].add(e.source_paper_id)

            target_ids = list(cited_by_map.keys())
            cocite_pairs: dict[tuple[str, str], int] = defaultdict(int)

            for i, a in enumerate(target_ids):
                citers_a = cited_by_map[a]
                for b in target_ids[i + 1 :]:
                    citers_b = cited_by_map[b]
                    overlap = len(citers_a & citers_b)
                    if overlap >= min_cocite:
                        cocite_pairs[(a, b)] = overlap

            clusters: list[set[str]] = []
            assigned: set[str] = set()
            sorted_pairs = sorted(
                cocite_pairs.items(),
                key=lambda x: x[1],
                reverse=True,
            )
            for (a, b), _strength in sorted_pairs:
                found = None
                for cl in clusters:
                    if a in cl or b in cl:
                        found = cl
                        break
                if found:
                    found.add(a)
                    found.add(b)
                else:
                    clusters.append({a, b})
                assigned.add(a)
                assigned.add(b)

            result_clusters = []
            for cl in clusters:
                members = []
                for pid in cl:
                    p = paper_map.get(pid)
                    if not p:
                        continue
                    members.append(
                        {
                            "id": pid,
                            "title": p.title,
                            "arxiv_id": p.arxiv_id,
                        }
                    )
                if len(members) >= 2:
                    result_clusters.append(
                        {
                            "size": len(members),
                            "papers": members,
                        }
                    )

            result_clusters.sort(key=lambda c: c["size"], reverse=True)

        return {
            "total_clusters": len(result_clusters),
            "clusters": result_clusters[:20],
            "cocitation_pairs": len(cocite_pairs),
        }
