"""
图谱分析服务 - 引用树、时间线、质量评估、演化分析、综述生成
@author Bamzc
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict, deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from packages.ai.prompts import (
    build_evolution_prompt,
    build_paper_wiki_prompt,
    build_research_gaps_prompt,
    build_survey_prompt,
    build_topic_wiki_prompt,
    build_wiki_outline_prompt,
    build_wiki_section_prompt,
)
from packages.ai.wiki_context import WikiContextGatherer
from packages.config import get_settings
from packages.domain.schemas import PaperCreate
from packages.integrations.llm_client import LLMClient
from packages.integrations.semantic_scholar_client import (
    RichCitationInfo,
    SemanticScholarClient,
)
from packages.storage.db import session_scope
from packages.storage.models import PaperTopic
from packages.storage.repositories import (
    CitationRepository,
    PaperRepository,
    TopicRepository,
)

logger = logging.getLogger(__name__)


class GraphService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.scholar = SemanticScholarClient(
            api_key=self.settings.semantic_scholar_api_key
        )
        self.llm = LLMClient()
        self.context_gatherer = WikiContextGatherer()

    def sync_citations_for_paper(
        self, paper_id: str, limit: int = 8
    ) -> dict:
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            cit_repo = CitationRepository(session)
            source = paper_repo.get_by_id(paper_id)
            edges = self.scholar.fetch_edges_by_title(
                source.title, limit=limit
            )
            inserted = 0
            for edge in edges:
                src = paper_repo.upsert_paper(
                    PaperCreate(
                        arxiv_id=self._title_to_id(
                            edge.source_title
                        ),
                        title=edge.source_title,
                        abstract="",
                        metadata={"source": "semantic_scholar"},
                    )
                )
                dst = paper_repo.upsert_paper(
                    PaperCreate(
                        arxiv_id=self._title_to_id(
                            edge.target_title
                        ),
                        title=edge.target_title,
                        abstract="",
                        metadata={"source": "semantic_scholar"},
                    )
                )
                cit_repo.upsert_edge(
                    src.id, dst.id, context=edge.context
                )
                inserted += 1
            return {
                "paper_id": paper_id,
                "edges_inserted": inserted,
            }

    def sync_citations_for_topic(
        self,
        topic_id: str,
        paper_limit: int = 30,
        edge_limit_per_paper: int = 6,
    ) -> dict:
        total_edges = 0
        paper_count = 0
        with session_scope() as session:
            topic = TopicRepository(session).get_by_id(topic_id)
            if topic is None:
                raise ValueError(f"topic {topic_id} not found")
            papers = PaperRepository(session).list_by_topic(
                topic_id, limit=paper_limit
            )
            paper_ids = [p.id for p in papers]
        for pid in paper_ids:
            result = self.sync_citations_for_paper(
                pid, limit=edge_limit_per_paper
            )
            total_edges += int(result.get("edges_inserted", 0))
            paper_count += 1
        return {
            "topic_id": topic_id,
            "papers_processed": paper_count,
            "edges_inserted": total_edges,
        }

    def auto_link_citations(self, paper_ids: list[str]) -> dict:
        """入库后自动关联引用 — 轻量版，只匹配已在库的论文"""
        norm = self._normalize_arxiv_id
        linked = 0
        errors = 0
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            cit_repo = CitationRepository(session)
            all_papers = paper_repo.list_all(limit=50000)
            lib_norm: dict[str, str] = {}
            for p in all_papers:
                pn = norm(p.arxiv_id)
                if pn:
                    lib_norm[pn] = p.id

        for pid in paper_ids:
            try:
                with session_scope() as session:
                    paper = PaperRepository(session).get_by_id(pid)
                    if not paper:
                        continue
                    title = paper.title

                rich = self.scholar.fetch_rich_citations(
                    title, ref_limit=30, cite_limit=30,
                )
                with session_scope() as session:
                    cit_repo = CitationRepository(session)
                    for info in rich:
                        info_n = norm(info.arxiv_id)
                        if info_n and info_n in lib_norm:
                            target_id = lib_norm[info_n]
                            if target_id == pid:
                                continue
                            if info.direction == "reference":
                                cit_repo.upsert_edge(
                                    pid, target_id, context="auto-ingest",
                                )
                            else:
                                cit_repo.upsert_edge(
                                    target_id, pid, context="auto-ingest",
                                )
                            linked += 1
            except Exception as exc:
                logger.warning("auto_link_citations error for %s: %s", pid, exc)
                errors += 1

        logger.info("auto_link_citations: %d edges, %d errors", linked, errors)
        return {"papers": len(paper_ids), "edges_linked": linked, "errors": errors}

    def library_overview(self) -> dict:
        """全库概览 — 节点 + 引用边 + PageRank + 统计"""
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            cit_repo = CitationRepository(session)
            topic_repo = TopicRepository(session)

            papers = paper_repo.list_all(limit=50000)
            edges = cit_repo.list_all()
            topics = topic_repo.list_topics()
            topic_map = {t.id: t.name for t in topics}

            paper_ids = {p.id for p in papers}
            valid_edges = [
                e for e in edges
                if e.source_paper_id in paper_ids
                and e.target_paper_id in paper_ids
            ]

            in_deg: dict[str, int] = defaultdict(int)
            out_deg: dict[str, int] = defaultdict(int)
            for e in valid_edges:
                out_deg[e.source_paper_id] += 1
                in_deg[e.target_paper_id] += 1

            pagerank = self._pagerank(list(paper_ids), valid_edges)

            from sqlalchemy import select as sa_select
            pt_rows = session.execute(sa_select(PaperTopic)).scalars().all()
            paper_topics: dict[str, list[str]] = defaultdict(list)
            for pt in pt_rows:
                tn = topic_map.get(pt.topic_id, "未分配")
                paper_topics[pt.paper_id].append(tn)

            nodes = []
            for p in papers:
                yr = (
                    p.publication_date.year
                    if isinstance(p.publication_date, date) else None
                )
                nodes.append({
                    "id": p.id,
                    "title": p.title,
                    "arxiv_id": p.arxiv_id,
                    "year": yr,
                    "in_degree": in_deg.get(p.id, 0),
                    "out_degree": out_deg.get(p.id, 0),
                    "pagerank": round(pagerank.get(p.id, 0), 6),
                    "topics": paper_topics.get(p.id, []),
                    "read_status": p.read_status.value if p.read_status else "unread",
                })

            edge_list = [
                {"source": e.source_paper_id, "target": e.target_paper_id}
                for e in valid_edges
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

            papers = paper_repo.list_all(limit=50000)
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
                    bridges.append({
                        "id": pid,
                        "title": p.title,
                        "arxiv_id": p.arxiv_id,
                        "topics_citing": [
                            topic_map.get(t, t) for t in tids
                        ],
                        "cross_topic_count": len(tids),
                        "own_topics": [
                            topic_map.get(t, t)
                            for t in paper_topic.get(pid, set())
                        ],
                    })

            bridges.sort(key=lambda b: b["cross_topic_count"], reverse=True)

        return {"bridges": bridges[:30], "total": len(bridges)}

    def research_frontier(self, days: int = 90) -> dict:
        """研究前沿检测 — 近期高被引 + 引用速度快的论文"""
        from datetime import timedelta
        cutoff = date.today() - timedelta(days=days)

        with session_scope() as session:
            paper_repo = PaperRepository(session)
            cit_repo = CitationRepository(session)

            papers = paper_repo.list_all(limit=50000)
            edges = cit_repo.list_all()
            paper_ids = {p.id for p in papers}

            in_deg: dict[str, int] = defaultdict(int)
            for e in edges:
                if e.target_paper_id in paper_ids:
                    in_deg[e.target_paper_id] += 1

            recent = [
                p for p in papers
                if isinstance(p.publication_date, date)
                and p.publication_date >= cutoff
            ]

            frontier = []
            for p in recent:
                age_days = max((date.today() - p.publication_date).days, 1)
                citations = in_deg.get(p.id, 0)
                velocity = round(citations / age_days * 30, 2)
                frontier.append({
                    "id": p.id,
                    "title": p.title,
                    "arxiv_id": p.arxiv_id,
                    "year": p.publication_date.year,
                    "publication_date": p.publication_date.isoformat(),
                    "citations_in_library": citations,
                    "citation_velocity": velocity,
                    "read_status": p.read_status.value if p.read_status else "unread",
                })

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

            papers = paper_repo.list_all(limit=50000)
            edges = cit_repo.list_all()
            paper_ids = {p.id for p in papers}
            paper_map = {p.id: p for p in papers}

            cited_by_map: dict[str, set[str]] = defaultdict(set)
            for e in edges:
                if (
                    e.source_paper_id in paper_ids
                    and e.target_paper_id in paper_ids
                ):
                    cited_by_map[e.target_paper_id].add(e.source_paper_id)

            target_ids = list(cited_by_map.keys())
            cocite_pairs: dict[tuple[str, str], int] = defaultdict(int)

            for i, a in enumerate(target_ids):
                citers_a = cited_by_map[a]
                for b in target_ids[i + 1:]:
                    citers_b = cited_by_map[b]
                    overlap = len(citers_a & citers_b)
                    if overlap >= min_cocite:
                        cocite_pairs[(a, b)] = overlap

            clusters: list[set[str]] = []
            assigned: set[str] = set()
            sorted_pairs = sorted(
                cocite_pairs.items(), key=lambda x: x[1], reverse=True,
            )
            for (a, b), strength in sorted_pairs:
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
                    members.append({
                        "id": pid,
                        "title": p.title,
                        "arxiv_id": p.arxiv_id,
                    })
                if len(members) >= 2:
                    result_clusters.append({
                        "size": len(members),
                        "papers": members,
                    })

            result_clusters.sort(key=lambda c: c["size"], reverse=True)

        return {
            "total_clusters": len(result_clusters),
            "clusters": result_clusters[:20],
            "cocitation_pairs": len(cocite_pairs),
        }

    def sync_incremental(
        self,
        paper_limit: int = 40,
        edge_limit_per_paper: int = 6,
    ) -> dict:
        with session_scope() as session:
            papers = PaperRepository(session).list_latest(
                limit=paper_limit * 3
            )
            edges = CitationRepository(session).list_all()
            touched = set()
            for e in edges:
                touched.add(e.source_paper_id)
                touched.add(e.target_paper_id)
            targets = [
                p for p in papers if p.id not in touched
            ][:paper_limit]
        processed = 0
        inserted = 0
        for p in targets:
            out = self.sync_citations_for_paper(
                p.id, limit=edge_limit_per_paper
            )
            processed += 1
            inserted += int(out.get("edges_inserted", 0))
        return {
            "processed_papers": processed,
            "edges_inserted": inserted,
            "strategy": "papers_without_existing_citation_edges",
        }

    def citation_tree(
        self, root_paper_id: str, depth: int = 2
    ) -> dict:
        with session_scope() as session:
            papers = {
                p.id: p
                for p in PaperRepository(session).list_all(
                    limit=10000
                )
            }
            edges = CitationRepository(session).list_all()
            out_edges: dict[str, list[str]] = defaultdict(list)
            in_edges: dict[str, list[str]] = defaultdict(list)
            for e in edges:
                out_edges[e.source_paper_id].append(
                    e.target_paper_id
                )
                in_edges[e.target_paper_id].append(
                    e.source_paper_id
                )

            def bfs(
                start: str, graph: dict[str, list[str]]
            ) -> list[dict]:
                visited = {start}
                q: deque[tuple[str, int]] = deque(
                    [(start, 0)]
                )
                result: list[dict] = []
                while q:
                    node, d = q.popleft()
                    if d >= depth:
                        continue
                    for nxt in graph.get(node, []):
                        result.append(
                            {
                                "source": node,
                                "target": nxt,
                                "depth": d + 1,
                            }
                        )
                        if nxt not in visited:
                            visited.add(nxt)
                            q.append((nxt, d + 1))
                return result

            ancestors = bfs(root_paper_id, out_edges)
            descendants = bfs(root_paper_id, in_edges)
            all_node_ids = {root_paper_id}
            for e in ancestors + descendants:
                all_node_ids.add(e["source"])
                all_node_ids.add(e["target"])
            nodes = [
                {
                    "id": pid,
                    "title": (
                        papers[pid].title
                        if pid in papers
                        else None
                    ),
                    "year": (
                        papers[pid].publication_date.year
                        if pid in papers
                        and isinstance(
                            papers[pid].publication_date,
                            date,
                        )
                        else None
                    ),
                }
                for pid in all_node_ids
            ]
            root_paper = papers.get(root_paper_id)
            root_title = (
                root_paper.title if root_paper else None
            )
        return {
            "root": root_paper_id,
            "root_title": root_title,
            "ancestors": ancestors,
            "descendants": descendants,
            "nodes": nodes,
            "edge_count": len(ancestors) + len(descendants),
        }

    def citation_detail(self, paper_id: str) -> dict:
        """获取单篇论文的丰富引用详情"""
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            cit_repo = CitationRepository(session)
            source = paper_repo.get_by_id(paper_id)
            if source is None:
                return {
                    "paper_id": paper_id, "paper_title": "",
                    "references": [], "cited_by": [],
                    "stats": {
                        "total_references": 0, "total_cited_by": 0,
                        "in_library_references": 0, "in_library_cited_by": 0,
                    },
                }
            source_title = source.title
            source_arxiv_id = source.arxiv_id

            try:
                rich_list = self.scholar.fetch_rich_citations(
                    source_title, ref_limit=50, cite_limit=50,
                    arxiv_id=source_arxiv_id,
                )
            except Exception as exc:
                logger.warning("fetch_rich_citations failed: %s", exc)
                rich_list = []

            norm = self._normalize_arxiv_id
            ext_normed = {
                norm(r.arxiv_id): r.arxiv_id
                for r in rich_list if r.arxiv_id
            }
            lib_norm_map: dict[str, str] = {}
            if ext_normed:
                for p in paper_repo.list_all(limit=50000):
                    pn = norm(p.arxiv_id)
                    if pn and pn in ext_normed:
                        lib_norm_map[pn] = p.id

            references: list[dict] = []
            cited_by: list[dict] = []

            for info in rich_list:
                info_norm = norm(info.arxiv_id)
                in_library = info_norm is not None and info_norm in lib_norm_map
                library_paper_id = lib_norm_map.get(info_norm) if in_library else None
                entry = {
                    "scholar_id": info.scholar_id,
                    "title": info.title,
                    "year": info.year,
                    "venue": info.venue,
                    "citation_count": info.citation_count,
                    "arxiv_id": info.arxiv_id,
                    "abstract": info.abstract,
                    "in_library": in_library,
                    "library_paper_id": library_paper_id,
                }
                if info.direction == "reference":
                    references.append(entry)
                    if in_library and library_paper_id:
                        cit_repo.upsert_edge(
                            paper_id, library_paper_id,
                            context="reference",
                        )
                else:
                    cited_by.append(entry)
                    if in_library and library_paper_id:
                        cit_repo.upsert_edge(
                            library_paper_id, paper_id,
                            context="citation",
                        )

        return {
            "paper_id": paper_id,
            "paper_title": source_title,
            "references": references,
            "cited_by": cited_by,
            "stats": {
                "total_references": len(references),
                "total_cited_by": len(cited_by),
                "in_library_references": sum(
                    1 for r in references if r["in_library"]
                ),
                "in_library_cited_by": sum(
                    1 for c in cited_by if c["in_library"]
                ),
            },
        }

    def topic_citation_network(self, topic_id: str) -> dict:
        """获取主题内论文的互引网络"""
        with session_scope() as session:
            topic_repo = TopicRepository(session)
            paper_repo = PaperRepository(session)
            cit_repo = CitationRepository(session)

            topic = topic_repo.get_by_id(topic_id)
            if topic is None:
                raise ValueError(f"topic {topic_id} not found")
            topic_name = topic.name

            papers = paper_repo.list_by_topic(topic_id, limit=500)
            paper_ids = {p.id for p in papers}

            all_edges = cit_repo.list_for_paper_ids(list(paper_ids))
            internal_edges = [
                e for e in all_edges
                if e.source_paper_id in paper_ids
                and e.target_paper_id in paper_ids
            ]

            in_degree: dict[str, int] = defaultdict(int)
            out_degree: dict[str, int] = defaultdict(int)
            for e in internal_edges:
                out_degree[e.source_paper_id] += 1
                in_degree[e.target_paper_id] += 1

            degrees = [
                in_degree.get(pid, 0) for pid in paper_ids
            ]
            median_deg = sorted(degrees)[len(degrees) // 2] if degrees else 0
            hub_threshold = max(median_deg * 2, 2)

            nodes = []
            for p in papers:
                ind = in_degree.get(p.id, 0)
                outd = out_degree.get(p.id, 0)
                nodes.append({
                    "id": p.id,
                    "title": p.title,
                    "year": (
                        p.publication_date.year
                        if isinstance(p.publication_date, date)
                        else None
                    ),
                    "arxiv_id": p.arxiv_id,
                    "in_degree": ind,
                    "out_degree": outd,
                    "is_hub": ind >= hub_threshold,
                    "is_external": False,
                })

            edges = [
                {
                    "source": e.source_paper_id,
                    "target": e.target_paper_id,
                }
                for e in internal_edges
            ]

            hub_count = sum(1 for n in nodes if n["is_hub"])
            n_papers = len(nodes)
            max_edges = n_papers * (n_papers - 1) if n_papers > 1 else 1
            density = round(len(edges) / max_edges, 4) if max_edges else 0

        return {
            "topic_id": topic_id,
            "topic_name": topic_name,
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "total_papers": n_papers,
                "total_edges": len(edges),
                "density": density,
                "hub_papers": hub_count,
            },
        }

    def topic_deep_trace(self, topic_id: str, max_concurrency: int = 3) -> dict:
        """对主题内论文执行深度溯源，拉取外部引用并进行共引分析"""
        with session_scope() as session:
            papers = PaperRepository(session).list_by_topic(
                topic_id, limit=500,
            )
            paper_ids = [p.id for p in papers]
            topic = TopicRepository(session).get_by_id(topic_id)
            if topic is None:
                raise ValueError(f"topic {topic_id} not found")
            topic_name = topic.name

        synced = 0
        with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
            futures = {
                pool.submit(self.citation_detail, pid): pid
                for pid in paper_ids
            }
            for fut in as_completed(futures):
                try:
                    result = fut.result()
                    synced += (
                        result["stats"]["total_references"]
                        + result["stats"]["total_cited_by"]
                    )
                except Exception as exc:
                    logger.warning("deep-trace sync error: %s", exc)

        with session_scope() as session:
            paper_repo = PaperRepository(session)
            cit_repo = CitationRepository(session)

            topic_papers = paper_repo.list_by_topic(topic_id, limit=500)
            topic_ids_set = {p.id for p in topic_papers}
            all_edges = cit_repo.list_for_paper_ids(list(topic_ids_set))

            external_ref_count: dict[str, int] = defaultdict(int)
            internal_edges = []
            external_edges = []

            for e in all_edges:
                src_in = e.source_paper_id in topic_ids_set
                tgt_in = e.target_paper_id in topic_ids_set
                if src_in and tgt_in:
                    internal_edges.append(e)
                elif src_in and not tgt_in:
                    external_edges.append(e)
                    external_ref_count[e.target_paper_id] += 1
                elif not src_in and tgt_in:
                    external_edges.append(e)
                    external_ref_count[e.source_paper_id] += 1

            co_cited = sorted(
                external_ref_count.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:30]
            co_cited_ids = [pid for pid, _ in co_cited]
            co_cited_papers = {
                p.id: p
                for p in paper_repo.list_by_ids(co_cited_ids)
            }

            in_degree: dict[str, int] = defaultdict(int)
            out_degree: dict[str, int] = defaultdict(int)
            for e in internal_edges:
                out_degree[e.source_paper_id] += 1
                in_degree[e.target_paper_id] += 1

            all_node_ids = set(topic_ids_set)
            topic_paper_map = {p.id: p for p in topic_papers}

            nodes = []
            for p in topic_papers:
                nodes.append({
                    "id": p.id,
                    "title": p.title,
                    "year": (
                        p.publication_date.year
                        if isinstance(p.publication_date, date)
                        else None
                    ),
                    "arxiv_id": p.arxiv_id,
                    "in_degree": in_degree.get(p.id, 0),
                    "out_degree": out_degree.get(p.id, 0),
                    "is_hub": in_degree.get(p.id, 0) >= 2,
                    "is_external": False,
                })

            for pid, count in co_cited:
                p = co_cited_papers.get(pid)
                nodes.append({
                    "id": pid,
                    "title": p.title if p else f"external-{pid[:8]}",
                    "year": (
                        p.publication_date.year
                        if p and isinstance(p.publication_date, date)
                        else None
                    ),
                    "arxiv_id": p.arxiv_id if p else None,
                    "in_degree": 0,
                    "out_degree": 0,
                    "is_hub": False,
                    "is_external": True,
                    "co_citation_count": count,
                })
                all_node_ids.add(pid)

            edges = [
                {"source": e.source_paper_id, "target": e.target_paper_id}
                for e in internal_edges
            ]
            for e in external_edges:
                if (
                    e.source_paper_id in all_node_ids
                    and e.target_paper_id in all_node_ids
                ):
                    edges.append({
                        "source": e.source_paper_id,
                        "target": e.target_paper_id,
                    })

            n_papers = len(nodes)
            max_edges = n_papers * (n_papers - 1) if n_papers > 1 else 1
            density = round(len(edges) / max_edges, 4) if max_edges else 0

            key_external = [
                {
                    "id": pid,
                    "title": (
                        co_cited_papers[pid].title
                        if pid in co_cited_papers
                        else f"external-{pid[:8]}"
                    ),
                    "co_citation_count": count,
                }
                for pid, count in co_cited
            ]

        return {
            "topic_id": topic_id,
            "topic_name": topic_name,
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "total_papers": n_papers,
                "internal_papers": len(topic_ids_set),
                "external_papers": len(co_cited),
                "total_edges": len(edges),
                "internal_edges": len(internal_edges),
                "density": density,
                "new_edges_synced": synced,
            },
            "key_external_papers": key_external,
        }

    def timeline(self, keyword: str, limit: int = 100) -> dict:
        with session_scope() as session:
            papers = PaperRepository(
                session
            ).full_text_candidates(keyword, limit=limit)
            edges = CitationRepository(session).list_all()
            nodes = {p.id: p for p in papers}
            indegree: dict[str, int] = {
                p.id: 0 for p in papers
            }
            outdegree: dict[str, int] = {
                p.id: 0 for p in papers
            }
            for e in edges:
                if (
                    e.target_paper_id in nodes
                    and e.source_paper_id in nodes
                ):
                    indegree[e.target_paper_id] += 1
                    outdegree[e.source_paper_id] += 1
            pagerank = self._pagerank(
                nodes=list(nodes.keys()), edges=edges
            )
            items = []
            for p in papers:
                year = (
                    p.publication_date.year
                    if isinstance(p.publication_date, date)
                    else 1900
                )
                pr = pagerank.get(p.id, 0.0)
                ind = indegree.get(p.id, 0)
                score = 0.65 * ind + 0.35 * pr * 100.0
                items.append(
                    {
                        "paper_id": p.id,
                        "title": p.title,
                        "year": year,
                        "indegree": ind,
                        "outdegree": outdegree.get(
                            p.id, 0
                        ),
                        "pagerank": pr,
                        "seminal_score": score,
                        "why_seminal": (
                            f"indegree={ind}, "
                            f"pagerank={pr:.4f}, "
                            f"score={score:.3f}"
                        ),
                    }
                )
        items.sort(
            key=lambda x: (
                x["year"],
                -x["indegree"],
                x["title"],
            )
        )
        seminal = sorted(
            items,
            key=lambda x: (-x["seminal_score"], x["year"]),
        )[:10]
        milestones = self._milestones_by_year(items)
        return {
            "keyword": keyword,
            "timeline": items,
            "seminal": seminal,
            "milestones": milestones,
        }

    def quality_metrics(
        self, keyword: str, limit: int = 120
    ) -> dict:
        with session_scope() as session:
            papers = PaperRepository(
                session
            ).full_text_candidates(keyword, limit=limit)
            paper_ids = [p.id for p in papers]
            edges = CitationRepository(
                session
            ).list_for_paper_ids(paper_ids)
            node_set = set(paper_ids)
            internal_edges = [
                e
                for e in edges
                if e.source_paper_id in node_set
                and e.target_paper_id in node_set
            ]
            connected_nodes: set[str] = set()
            for e in internal_edges:
                connected_nodes.add(e.source_paper_id)
                connected_nodes.add(e.target_paper_id)
            with_pub = sum(
                1
                for p in papers
                if p.publication_date is not None
            )
        n = max(len(paper_ids), 1)
        ie = len(internal_edges)
        return {
            "keyword": keyword,
            "node_count": len(paper_ids),
            "edge_count": ie,
            "density": ie / max(n * max(n - 1, 1), 1),
            "connected_node_ratio": (
                len(connected_nodes) / n
            ),
            "publication_date_coverage": with_pub / n,
        }

    def weekly_evolution(
        self, keyword: str, limit: int = 160
    ) -> dict:
        tl = self.timeline(keyword=keyword, limit=limit)
        by_year: dict[int, list[dict]] = defaultdict(list)
        for item in tl["timeline"]:
            by_year[item["year"]].append(item)
        year_buckets = []
        for year in sorted(by_year.keys())[-6:]:
            group = by_year[year]
            avg = sum(x["seminal_score"] for x in group) / max(
                len(group), 1
            )
            top_titles = [
                x["title"]
                for x in sorted(
                    group, key=lambda t: -t["seminal_score"]
                )[:3]
            ]
            year_buckets.append(
                {
                    "year": year,
                    "paper_count": len(group),
                    "avg_seminal_score": avg,
                    "top_titles": top_titles,
                }
            )
        prompt = build_evolution_prompt(
            keyword=keyword, year_buckets=year_buckets
        )
        llm_result = self.llm.complete_json(
            prompt,
            stage="rag",
            model_override=self.settings.llm_model_skim,
        )
        self.llm.trace_result(llm_result, stage="graph_evolution", prompt_digest=f"evolution:{keyword}")
        summary = llm_result.parsed_json or {
            "trend_summary": "数据样本不足，建议增加领域样本后重试。",
            "phase_shift_signals": [],
            "next_week_focus": [],
        }
        return {
            "keyword": keyword,
            "year_buckets": year_buckets,
            "summary": summary,
        }

    def survey(self, keyword: str, limit: int = 120) -> dict:
        base = self.timeline(keyword=keyword, limit=limit)
        prompt = build_survey_prompt(
            keyword, base["milestones"], base["seminal"]
        )
        result = self.llm.complete_json(
            prompt,
            stage="rag",
            model_override=self.settings.llm_model_skim,
        )
        self.llm.trace_result(result, stage="graph_survey", prompt_digest=f"survey:{keyword}")
        survey_obj = result.parsed_json or {
            "overview": "当前样本不足以生成高质量综述。",
            "stages": [],
            "reading_list": [
                x["title"] for x in base["seminal"][:5]
            ],
            "open_questions": [],
        }
        return {
            "keyword": keyword,
            "summary": survey_obj,
            "milestones": base["milestones"],
            "seminal": base["seminal"],
        }

    def detect_research_gaps(
        self, keyword: str, limit: int = 120,
    ) -> dict:
        """分析引用网络的稀疏区域，识别研究空白"""
        tl = self.timeline(keyword=keyword, limit=limit)
        quality = self.quality_metrics(keyword=keyword, limit=limit)

        # 构造论文数据（含 indegree/outdegree/keywords）
        papers_data = []
        for item in tl["timeline"]:
            papers_data.append({
                "title": item["title"],
                "year": item["year"],
                "indegree": item["indegree"],
                "outdegree": item["outdegree"],
                "seminal_score": item["seminal_score"],
                "keywords": [],
                "abstract": "",
            })

        # 补充 abstract 和 keywords
        with session_scope() as session:
            repo = PaperRepository(session)
            candidates = repo.full_text_candidates(keyword, limit=limit)
            paper_map = {p.title: p for p in candidates}
            for pd in papers_data:
                p = paper_map.get(pd["title"])
                if p:
                    pd["abstract"] = p.abstract[:400]
                    pd["keywords"] = (p.metadata_json or {}).get("keywords", [])

        # 计算孤立论文数（入度+出度=0）
        isolated = sum(
            1 for item in tl["timeline"]
            if item["indegree"] == 0 and item["outdegree"] == 0
        )

        network_stats = {
            "total_papers": quality["node_count"],
            "edge_count": quality["edge_count"],
            "density": quality["density"],
            "connected_ratio": quality["connected_node_ratio"],
            "isolated_count": isolated,
        }

        prompt = build_research_gaps_prompt(
            keyword=keyword,
            papers_data=papers_data,
            network_stats=network_stats,
        )
        result = self.llm.complete_json(
            prompt,
            stage="deep",
            model_override=self.settings.llm_model_deep,
            max_tokens=8192,
        )
        self.llm.trace_result(result, stage="graph_research_gaps", prompt_digest=f"gaps:{keyword}")

        parsed = result.parsed_json or {
            "research_gaps": [],
            "method_comparison": {"dimensions": [], "methods": [], "underexplored_combinations": []},
            "trend_analysis": {"hot_directions": [], "declining_areas": [], "emerging_opportunities": []},
            "overall_summary": "数据不足，无法完成分析。",
        }

        return {
            "keyword": keyword,
            "network_stats": network_stats,
            "analysis": parsed,
        }

    def paper_wiki(self, paper_id: str) -> dict:
        tree = self.citation_tree(
            root_paper_id=paper_id, depth=2
        )

        # 1. 富化上下文收集（向量搜索 + 引用上下文 + PDF）
        ctx = self.context_gatherer.gather_paper_context(paper_id)
        p_title = ctx["paper"].get("title", "")
        p_abstract = ctx["paper"].get("abstract", "")
        p_arxiv = ctx["paper"].get("arxiv_id", "")
        analysis = ctx["paper"].get("analysis", "")

        # 2. Semantic Scholar 元数据
        scholar_meta: list[dict] = []
        try:
            all_titles = [p_title] + ctx.get("ancestor_titles", [])[:5]
            scholar_meta = self.scholar.fetch_batch_metadata(
                all_titles, max_papers=6
            )
        except Exception as exc:
            logger.warning("Scholar metadata fetch failed: %s", exc)

        # 3. LLM 生成结构化 wiki
        prompt = build_paper_wiki_prompt(
            title=p_title,
            abstract=p_abstract,
            analysis=analysis,
            related_papers=ctx.get("related_papers", [])[:10],
            ancestors=ctx.get("ancestor_titles", []),
            descendants=ctx.get("descendant_titles", []),
        )
        # 注入引用上下文 + PDF + Scholar 到 prompt
        extra_context = self._build_extra_context(
            citation_contexts=ctx.get("citation_contexts", []),
            pdf_excerpt=ctx.get("pdf_excerpt", ""),
            scholar_metadata=scholar_meta,
        )
        full_prompt = prompt + extra_context

        result = self.llm.complete_json(
            full_prompt,
            stage="rag",
            model_override=self.settings.llm_model_deep,
            max_tokens=8192,
        )
        self.llm.trace_result(result, stage="wiki_paper", paper_id=paper_id, prompt_digest=f"paper_wiki:{p_title[:60]}")
        wiki_content = result.parsed_json or {
            "summary": analysis or "暂无分析。",
            "contributions": [],
            "methodology": "",
            "significance": "",
            "limitations": [],
            "related_work_analysis": "",
            "reading_suggestions": [],
        }

        # 注入额外元数据供前端展示
        wiki_content["citation_contexts"] = ctx.get(
            "citation_contexts", []
        )[:20]
        wiki_content["pdf_excerpts"] = (
            [{"title": p_title, "excerpt": ctx.get("pdf_excerpt", "")[:2000]}]
            if ctx.get("pdf_excerpt")
            else []
        )
        wiki_content["scholar_metadata"] = scholar_meta

        # 备用 markdown
        md_parts = [
            f"# {p_title}",
            f"\narXiv: {p_arxiv}",
            f"\n## 摘要\n\n{wiki_content.get('summary', '')}",
        ]
        if wiki_content.get("methodology"):
            md_parts.append(
                f"\n## 方法论\n\n{wiki_content['methodology']}"
            )
        if wiki_content.get("significance"):
            md_parts.append(
                f"\n## 学术意义\n\n{wiki_content['significance']}"
            )
        markdown = "\n".join(md_parts)

        return {
            "paper_id": paper_id,
            "title": p_title,
            "markdown": markdown,
            "wiki_content": wiki_content,
            "graph": tree,
        }

    def topic_wiki(
        self,
        keyword: str,
        limit: int = 120,
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> dict:
        def _progress(pct: float, msg: str):
            if progress_callback:
                progress_callback(pct, msg)

        # Phase 0: 并行收集数据
        _progress(0.05, "收集时间线和综述数据...")
        tl = self.timeline(keyword=keyword, limit=limit)
        survey_data = self.survey(keyword=keyword, limit=limit)

        _progress(0.15, "收集论文上下文和引用关系...")
        # Phase 1: 富化上下文（向量搜索 + 引用上下文 + PDF）
        ctx = self.context_gatherer.gather_topic_context(
            keyword, limit=limit
        )
        paper_contexts = ctx.get("paper_contexts", [])[:25]
        citation_contexts = ctx.get("citation_contexts", [])[:30]
        pdf_excerpts = ctx.get("pdf_excerpts", [])[:5]

        # Phase 2: Semantic Scholar 元数据增强
        scholar_meta: list[dict] = []
        try:
            top_titles = [
                s["title"]
                for s in tl.get("seminal", [])[:8]
                if s.get("title")
            ]
            scholar_meta = self.scholar.fetch_batch_metadata(
                top_titles, max_papers=8
            )
        except Exception as exc:
            logger.warning("Scholar metadata fetch failed: %s", exc)

        _progress(0.25, "生成文章大纲...")
        # Phase 3: 多轮生成 — 先生成大纲
        outline_prompt = build_wiki_outline_prompt(
            keyword=keyword,
            paper_summaries=paper_contexts,
            citation_contexts=citation_contexts,
            scholar_metadata=scholar_meta,
            pdf_excerpts=pdf_excerpts,
        )
        outline_result = self.llm.complete_json(
            outline_prompt,
            stage="rag",
            model_override=self.settings.llm_model_deep,
            max_tokens=8192,
        )
        self.llm.trace_result(outline_result, stage="wiki_outline", prompt_digest=f"outline:{keyword}")
        outline = outline_result.parsed_json or {
            "title": keyword,
            "outline": [],
            "total_sections": 0,
        }

        # Phase 4: 并行章节生成（直接输出 markdown 文本）
        all_sources_text = self._build_all_sources_text(
            paper_contexts,
            citation_contexts,
            scholar_meta,
            pdf_excerpts,
        )
        sec_plans = outline.get("outline", [])[:5]
        _progress(0.35, f"并行生成 {len(sec_plans)} 个章节...")
        sections = self._generate_sections_parallel(
            keyword, sec_plans, all_sources_text,
        )

        _progress(0.75, "生成概述和总结...")
        # Phase 5: 生成概述（直接输出文本）+ 结构化汇总（JSON）
        # 5a: 文本概述
        section_titles = ", ".join(
            s.get("title", "") for s in sections
        )
        survey_overview = (
            survey_data.get("summary", {}).get("overview", "")[:600]
        )
        overview_prompt = (
            "你是世界顶级学术综述作者。"
            f"请为「{keyword}」主题撰写一段 300-500 字的概述，"
            "涵盖该主题的定义、重要性、核心思想和发展脉络。\n"
            "直接输出文本，不要用 JSON 或代码块包裹。\n\n"
            f"已有章节: {section_titles}\n"
            f"参考综述: {survey_overview}\n"
        )
        overview_result = self.llm.summarize_text(
            overview_prompt,
            stage="wiki_overview",
            model_override=self.settings.llm_model_deep,
            max_tokens=2048,
        )
        self.llm.trace_result(
            overview_result, stage="wiki_overview",
            prompt_digest=f"overview:{keyword}",
        )
        overview_text = (overview_result.content or "").strip()
        overview_text = re.sub(
            r'^```(?:markdown)?\s*\n?', '', overview_text
        )
        overview_text = re.sub(r'\n?```\s*$', '', overview_text)

        # 5b: 结构化汇总（key_findings + future_directions）
        summary_prompt = (
            "请只输出单个 JSON 对象，不要代码块。\n"
            f"根据以下「{keyword}」综述内容，提取关键发现和未来方向：\n"
            f"概述: {overview_text[:300]}\n"
            f"章节: {section_titles}\n"
            f"参考: {survey_overview[:300]}\n\n"
            '输出: {"key_findings": ["发现1","发现2","发现3"],'
            ' "future_directions": ["方向1","方向2","方向3"],'
            ' "reading_list": ["论文1","论文2"]}'
        )
        summary_result = self.llm.complete_json(
            summary_prompt,
            stage="wiki_summary",
            model_override=self.settings.llm_model_deep,
            max_tokens=2048,
        )
        self.llm.trace_result(
            summary_result, stage="wiki_summary",
            prompt_digest=f"summary:{keyword}",
        )
        summary_data = summary_result.parsed_json or {}

        # 组装最终 wiki_content
        wiki_content: dict = {
            "overview": overview_text,
            "sections": sections,
            "key_findings": summary_data.get("key_findings", []),
            "methodology_evolution": "",
            "future_directions": summary_data.get(
                "future_directions", []
            ),
            "reading_list": summary_data.get("reading_list", []),
            "citation_contexts": citation_contexts[:20],
            "pdf_excerpts": pdf_excerpts,
            "scholar_metadata": scholar_meta,
        }

        # 备用 markdown
        md_parts = [
            f"# {keyword}\n\n{wiki_content.get('overview', '')}"
        ]
        for sec in sections:
            md_parts.append(
                f"\n## {sec.get('title', '')}\n\n"
                f"{sec.get('content', '')}"
            )
        if wiki_content.get("methodology_evolution"):
            md_parts.append(
                f"\n## 方法论演化\n\n"
                f"{wiki_content['methodology_evolution']}"
            )
        markdown = "\n".join(md_parts)

        _progress(1.0, "Wiki 生成完成")
        return {
            "keyword": keyword,
            "markdown": markdown,
            "wiki_content": wiki_content,
            "timeline": tl,
            "survey": survey_data,
        }

    @staticmethod
    def _build_extra_context(
        *,
        citation_contexts: list[str],
        pdf_excerpt: str,
        scholar_metadata: list[dict],
    ) -> str:
        """拼装额外上下文注入到 paper wiki prompt"""
        parts: list[str] = []
        if citation_contexts:
            parts.append("\n## 引用关系上下文:")
            for i, c in enumerate(citation_contexts[:15], 1):
                parts.append(f"[C{i}] {c}")
        if pdf_excerpt:
            parts.append(
                f"\n## PDF 全文摘录（前 2000 字）:\n"
                f"{pdf_excerpt[:2000]}"
            )
        if scholar_metadata:
            parts.append("\n## Semantic Scholar 外部元数据:")
            for i, s in enumerate(scholar_metadata[:6], 1):
                parts.append(
                    f"[S{i}] {s.get('title', 'N/A')} "
                    f"({s.get('year', '?')}) "
                    f"引用数={s.get('citationCount', 'N/A')} "
                    f"Venue={s.get('venue', 'N/A')}"
                )
                if s.get("tldr"):
                    parts.append(f"  TLDR: {s['tldr'][:200]}")
        return "\n".join(parts)

    def _generate_one_section(
        self, keyword: str, sec_plan: dict, all_sources_text: str,
    ) -> dict:
        """生成单个 wiki 章节"""
        sec_title = sec_plan.get("section_title", "")
        sec_prompt = build_wiki_section_prompt(
            keyword=keyword,
            section_title=sec_title,
            key_points=sec_plan.get("key_points", []),
            source_refs=sec_plan.get("source_refs", []),
            all_sources_text=all_sources_text,
        )
        sec_result = self.llm.summarize_text(
            sec_prompt,
            stage="wiki_section",
            model_override=self.settings.llm_model_deep,
            max_tokens=4096,
        )
        self.llm.trace_result(
            sec_result, stage="wiki_section",
            prompt_digest=f"section:{sec_title[:60]}",
        )
        content = sec_result.content or ""
        content = re.sub(
            r'^```(?:markdown)?\s*\n?', '', content.strip()
        )
        content = re.sub(r'\n?```\s*$', '', content.strip())
        return {
            "title": sec_title,
            "content": content,
            "key_insight": "",
        }

    def _generate_sections_parallel(
        self,
        keyword: str,
        sec_plans: list[dict],
        all_sources_text: str,
        max_workers: int = 3,
    ) -> list[dict]:
        """并行生成多个 wiki 章节"""
        if not sec_plans:
            return []
        sections: list[dict] = [{}] * len(sec_plans)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_to_idx = {
                pool.submit(
                    self._generate_one_section,
                    keyword, plan, all_sources_text,
                ): idx
                for idx, plan in enumerate(sec_plans)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    sections[idx] = future.result()
                    logger.info(
                        "wiki section %d/%d 完成: %s",
                        idx + 1, len(sec_plans),
                        sections[idx].get("title", "")[:40],
                    )
                except Exception as exc:
                    logger.warning("wiki section %d 失败: %s", idx, exc)
                    sections[idx] = {
                        "title": sec_plans[idx].get("section_title", ""),
                        "content": "",
                        "key_insight": "",
                    }
        return sections

    @staticmethod
    def _build_all_sources_text(
        paper_contexts: list[dict],
        citation_contexts: list[str],
        scholar_metadata: list[dict],
        pdf_excerpts: list[dict],
    ) -> str:
        """拼装所有来源文本供逐章节生成使用"""
        parts: list[str] = []
        for i, p in enumerate(paper_contexts[:25], 1):
            parts.append(
                f"[P{i}] {p.get('title', 'N/A')} "
                f"({p.get('year', '?')})\n"
                f"Abstract: {p.get('abstract', '')[:400]}\n"
                f"Analysis: {p.get('analysis', '')[:400]}"
            )
        for i, c in enumerate(citation_contexts[:20], 1):
            parts.append(f"[C{i}] {c}")
        for i, s in enumerate(scholar_metadata[:8], 1):
            line = (
                f"[S{i}] {s.get('title', 'N/A')} "
                f"({s.get('year', '?')}) "
                f"citations={s.get('citationCount', '?')}"
            )
            if s.get("tldr"):
                line += f" TLDR: {s['tldr'][:200]}"
            parts.append(line)
        for i, ex in enumerate(pdf_excerpts[:5], 1):
            parts.append(
                f"[PDF{i}] {ex.get('title', 'N/A')}\n"
                f"Excerpt: {ex.get('excerpt', '')[:500]}"
            )
        return "\n\n".join(parts)

    @staticmethod
    def _normalize_arxiv_id(arxiv_id: str | None) -> str | None:
        """去版本号归一化: '2502.12082v2' -> '2502.12082'"""
        if not arxiv_id:
            return None
        return re.sub(r"v\d+$", "", arxiv_id.strip())

    @staticmethod
    def _title_to_id(title: str) -> str:
        normalized = "".join(
            ch.lower() if ch.isalnum() else "-" for ch in title
        ).strip("-")
        return f"ss-{normalized[:48]}"

    @staticmethod
    def _pagerank(
        nodes: list[str], edges: list
    ) -> dict[str, float]:
        if not nodes:
            return {}
        node_set = set(nodes)
        outgoing: dict[str, list[str]] = defaultdict(list)
        for e in edges:
            if (
                e.source_paper_id in node_set
                and e.target_paper_id in node_set
            ):
                outgoing[e.source_paper_id].append(
                    e.target_paper_id
                )
        n = len(nodes)
        rank = {node: 1.0 / n for node in nodes}
        damping = 0.85
        for _ in range(20):
            next_rank = {
                node: (1.0 - damping) / n for node in nodes
            }
            for node in nodes:
                refs = outgoing.get(node, [])
                if not refs:
                    continue
                share = rank[node] / len(refs)
                for dst in refs:
                    next_rank[dst] += damping * share
            rank = next_rank
        return rank

    @staticmethod
    def _milestones_by_year(
        items: list[dict],
    ) -> list[dict]:
        best_per_year: dict[int, dict] = {}
        for x in items:
            year = x["year"]
            if (
                year not in best_per_year
                or x["seminal_score"]
                > best_per_year[year]["seminal_score"]
            ):
                best_per_year[year] = x
        return [
            best_per_year[y] for y in sorted(best_per_year.keys())
        ]
