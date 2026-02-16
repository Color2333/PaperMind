"""
图谱分析服务 - 引用树、时间线、质量评估、演化分析、综述生成
@author Bamzc
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import date

from packages.ai.prompts import (
    build_evolution_prompt,
    build_survey_prompt,
)
from packages.config import get_settings
from packages.domain.schemas import PaperCreate
from packages.integrations.llm_client import LLMClient
from packages.integrations.semantic_scholar_client import (
    SemanticScholarClient,
)
from packages.storage.db import session_scope
from packages.storage.repositories import (
    AnalysisRepository,
    CitationRepository,
    PaperRepository,
    TopicRepository,
)


class GraphService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.scholar = SemanticScholarClient(
            api_key=self.settings.semantic_scholar_api_key
        )
        self.llm = LLMClient()

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

    def paper_wiki(self, paper_id: str) -> dict:
        tree = self.citation_tree(
            root_paper_id=paper_id, depth=2
        )
        with session_scope() as session:
            paper = PaperRepository(session).get_by_id(paper_id)
            analysis = (
                AnalysisRepository(session)
                .contexts_for_papers([paper_id])
                .get(paper_id, "")
            )
            p_title = paper.title
            p_id = paper.id
            p_arxiv = paper.arxiv_id
            p_status = paper.read_status.value
        md = [
            f"# {p_title}",
            "",
            f"- Paper ID: {p_id}",
            f"- ArXiv ID: {p_arxiv}",
            f"- Read Status: {p_status}",
            "",
            "## Summary",
            analysis or "暂无分析内容。",
            "",
            "## Ancestor Papers (Depth<=2)",
        ]
        for e in tree["ancestors"][:20]:
            md.append(
                f"- {tree['root']} -> {e['target']} "
                f"(depth={e['depth']})"
            )
        md.append("")
        md.append("## Descendant Papers (Depth<=2)")
        for e in tree["descendants"][:20]:
            md.append(
                f"- {e['source']} -> {tree['root']} "
                f"(depth={e['depth']})"
            )
        return {
            "paper_id": paper_id,
            "markdown": "\n".join(md),
            "graph": tree,
        }

    def topic_wiki(
        self, keyword: str, limit: int = 120
    ) -> dict:
        tl = self.timeline(keyword=keyword, limit=limit)
        survey = self.survey(keyword=keyword, limit=limit)
        md = [
            f"# Topic Wiki: {keyword}",
            "",
            "## Seminal Papers",
        ]
        for s in tl["seminal"][:10]:
            md.append(
                f"- {s['year']} | {s['title']} "
                f"| score={s['seminal_score']:.3f}"
            )
        md.append("")
        md.append("## Milestones")
        for m in tl["milestones"][:12]:
            md.append(
                f"- {m['year']} | {m['title']} "
                f"| score={m['seminal_score']:.3f}"
            )
        md.append("")
        md.append("## Survey")
        md.append(str(survey["summary"]))
        return {
            "keyword": keyword,
            "markdown": "\n".join(md),
            "timeline": tl,
            "survey": survey,
        }

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
