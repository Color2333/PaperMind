"""引用同步与引用树/网络服务。"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from packages.ai.graph._common import _normalize_arxiv_id, _title_to_id
from packages.domain.schemas import PaperCreate
from packages.storage.db import session_scope
from packages.storage.repositories import (
    CitationRepository,
    PaperRepository,
    TopicRepository,
)

logger = logging.getLogger(__name__)


class CitationService:
    def __init__(self, settings, citations, scholar) -> None:
        self.settings = settings
        self.citations = citations
        self.scholar = scholar

    def sync_citations_for_paper(self, paper_id: str, limit: int = 8) -> dict:
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            cit_repo = CitationRepository(session)
            source = paper_repo.get_by_id(paper_id)
            edges = self.scholar.fetch_edges_by_title(source.title, limit=limit)
            inserted = 0
            for edge in edges:
                src = paper_repo.upsert_paper(
                    PaperCreate(
                        arxiv_id=_title_to_id(edge.source_title),
                        title=edge.source_title,
                        abstract="",
                        metadata={"source": "semantic_scholar"},
                    )
                )
                dst = paper_repo.upsert_paper(
                    PaperCreate(
                        arxiv_id=_title_to_id(edge.target_title),
                        title=edge.target_title,
                        abstract="",
                        metadata={"source": "semantic_scholar"},
                    )
                )
                cit_repo.upsert_edge(src.id, dst.id, context=edge.context)
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
        with session_scope() as session:
            topic = TopicRepository(session).get_by_id(topic_id)
            if topic is None:
                raise ValueError(f"topic {topic_id} not found")
            papers = PaperRepository(session).list_by_topic(topic_id, limit=paper_limit)
            paper_ids = [p.id for p in papers]

        total_edges = 0
        paper_count = 0
        # 限制并发避免 API 限速和 SQLite 锁竞争
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(self.sync_citations_for_paper, pid, edge_limit_per_paper): pid
                for pid in paper_ids
            }
            for future in as_completed(futures):
                try:
                    result = future.result()
                    total_edges += int(result.get("edges_inserted", 0))
                    paper_count += 1
                except Exception as exc:
                    logger.warning("sync error for %s: %s", futures[future], exc)

        return {
            "topic_id": topic_id,
            "papers_processed": paper_count,
            "edges_inserted": total_edges,
        }

    def auto_link_citations(self, paper_ids: list[str]) -> dict:
        """入库后自动关联引用 — 轻量版，只匹配已在库的论文"""
        norm = _normalize_arxiv_id
        linked = 0
        errors = 0
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            cit_repo = CitationRepository(session)
            all_papers = paper_repo.list_lightweight(limit=50000)
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
                    title,
                    ref_limit=30,
                    cite_limit=30,
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
                                    pid,
                                    target_id,
                                    context="auto-ingest",
                                )
                            else:
                                cit_repo.upsert_edge(
                                    target_id,
                                    pid,
                                    context="auto-ingest",
                                )
                            linked += 1
            except Exception as exc:
                logger.warning("auto_link_citations error for %s: %s", pid, exc)
                errors += 1

        logger.info("auto_link_citations: %d edges, %d errors", linked, errors)
        return {"papers": len(paper_ids), "edges_linked": linked, "errors": errors}

    def sync_incremental(
        self,
        paper_limit: int = 40,
        edge_limit_per_paper: int = 6,
    ) -> dict:
        with session_scope() as session:
            papers = PaperRepository(session).list_latest(limit=paper_limit * 3)
            edges = CitationRepository(session).list_all()
            touched = set()
            for e in edges:
                touched.add(e.source_paper_id)
                touched.add(e.target_paper_id)
            # 在 session 内提取 id，避免 DetachedInstanceError
            target_ids = [p.id for p in papers if p.id not in touched][:paper_limit]
        processed = 0
        inserted = 0
        for pid in target_ids:
            try:
                out = self.sync_citations_for_paper(pid, limit=edge_limit_per_paper)
                processed += 1
                inserted += int(out.get("edges_inserted", 0))
            except Exception as exc:
                logger.warning("sync_incremental skip %s: %s", pid[:8], exc)
        return {
            "processed_papers": processed,
            "edges_inserted": inserted,
            "strategy": "papers_without_existing_citation_edges",
        }

    def citation_tree(self, root_paper_id: str, depth: int = 2) -> dict:
        with session_scope() as session:
            papers = {p.id: p for p in PaperRepository(session).list_lightweight(limit=10000)}
            edges = CitationRepository(session).list_all()
            out_edges: dict[str, list[str]] = defaultdict(list)
            in_edges: dict[str, list[str]] = defaultdict(list)
            for e in edges:
                out_edges[e.source_paper_id].append(e.target_paper_id)
                in_edges[e.target_paper_id].append(e.source_paper_id)

            def bfs(start: str, graph: dict[str, list[str]]) -> list[dict]:
                visited = {start}
                q: deque[tuple[str, int]] = deque([(start, 0)])
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
                    "title": (papers[pid].title if pid in papers else None),
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
            root_title = root_paper.title if root_paper else None
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
                    "paper_id": paper_id,
                    "paper_title": "",
                    "references": [],
                    "cited_by": [],
                    "stats": {
                        "total_references": 0,
                        "total_cited_by": 0,
                        "in_library_references": 0,
                        "in_library_cited_by": 0,
                    },
                }
            source_title = source.title
            source_arxiv_id = source.arxiv_id

            try:
                rich_list = self.scholar.fetch_rich_citations(
                    source_title,
                    ref_limit=50,
                    cite_limit=50,
                    arxiv_id=source_arxiv_id,
                )
            except Exception as exc:
                logger.warning("fetch_rich_citations failed: %s", exc)
                rich_list = []

            norm = _normalize_arxiv_id
            ext_normed = {norm(r.arxiv_id): r.arxiv_id for r in rich_list if r.arxiv_id}
            lib_norm_map: dict[str, str] = {}
            if ext_normed:
                # 只加载轻量字段，减少内存占用
                for p in paper_repo.list_lightweight(limit=50000):
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
                            paper_id,
                            library_paper_id,
                            context="reference",
                        )
                else:
                    cited_by.append(entry)
                    if in_library and library_paper_id:
                        cit_repo.upsert_edge(
                            library_paper_id,
                            paper_id,
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
                "in_library_references": sum(1 for r in references if r["in_library"]),
                "in_library_cited_by": sum(1 for c in cited_by if c["in_library"]),
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
                e
                for e in all_edges
                if e.source_paper_id in paper_ids and e.target_paper_id in paper_ids
            ]

            in_degree: dict[str, int] = defaultdict(int)
            out_degree: dict[str, int] = defaultdict(int)
            for e in internal_edges:
                out_degree[e.source_paper_id] += 1
                in_degree[e.target_paper_id] += 1

            degrees = [in_degree.get(pid, 0) for pid in paper_ids]
            median_deg = sorted(degrees)[len(degrees) // 2] if degrees else 0
            hub_threshold = max(median_deg * 2, 2)

            nodes = []
            for p in papers:
                ind = in_degree.get(p.id, 0)
                outd = out_degree.get(p.id, 0)
                nodes.append(
                    {
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
                    }
                )

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
                topic_id,
                limit=500,
            )
            paper_ids = [p.id for p in papers]
            topic = TopicRepository(session).get_by_id(topic_id)
            if topic is None:
                raise ValueError(f"topic {topic_id} not found")
            topic_name = topic.name

        synced = 0
        with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
            futures = {pool.submit(self.citation_detail, pid): pid for pid in paper_ids}
            for fut in as_completed(futures):
                try:
                    result = fut.result()
                    synced += (
                        result["stats"]["total_references"] + result["stats"]["total_cited_by"]
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
            co_cited_papers = {p.id: p for p in paper_repo.list_by_ids(co_cited_ids)}

            in_degree: dict[str, int] = defaultdict(int)
            out_degree: dict[str, int] = defaultdict(int)
            for e in internal_edges:
                out_degree[e.source_paper_id] += 1
                in_degree[e.target_paper_id] += 1

            all_node_ids = set(topic_ids_set)

            nodes = []
            for p in topic_papers:
                nodes.append(
                    {
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
                    }
                )

            for pid, count in co_cited:
                p = co_cited_papers.get(pid)
                nodes.append(
                    {
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
                    }
                )
                all_node_ids.add(pid)

            edges = [
                {"source": e.source_paper_id, "target": e.target_paper_id} for e in internal_edges
            ]
            for e in external_edges:
                if e.source_paper_id in all_node_ids and e.target_paper_id in all_node_ids:
                    edges.append(
                        {
                            "source": e.source_paper_id,
                            "target": e.target_paper_id,
                        }
                    )

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
