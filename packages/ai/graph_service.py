"""
图谱分析服务 - 引用树、时间线、质量评估、演化分析、综述生成
@author Bamzc
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
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
    SemanticScholarClient,
)
from packages.storage.db import session_scope
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
            max_tokens=4096,
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
            max_tokens=4096,
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
        self, keyword: str, limit: int = 120
    ) -> dict:
        # Phase 0: 并行收集数据
        tl = self.timeline(keyword=keyword, limit=limit)
        survey_data = self.survey(keyword=keyword, limit=limit)

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
            max_tokens=2048,
        )
        self.llm.trace_result(outline_result, stage="wiki_outline", prompt_digest=f"outline:{keyword}")
        outline = outline_result.parsed_json or {
            "title": keyword,
            "outline": [],
            "total_sections": 0,
        }

        # Phase 4: 逐章节生成
        all_sources_text = self._build_all_sources_text(
            paper_contexts,
            citation_contexts,
            scholar_meta,
            pdf_excerpts,
        )
        sections: list[dict] = []
        for sec_plan in outline.get("outline", [])[:8]:
            sec_prompt = build_wiki_section_prompt(
                keyword=keyword,
                section_title=sec_plan.get("section_title", ""),
                key_points=sec_plan.get("key_points", []),
                source_refs=sec_plan.get("source_refs", []),
                all_sources_text=all_sources_text,
            )
            sec_result = self.llm.complete_json(
                sec_prompt,
                stage="rag",
                model_override=self.settings.llm_model_deep,
                max_tokens=2048,
            )
            self.llm.trace_result(sec_result, stage="wiki_section", prompt_digest=f"section:{sec_plan.get('section_title','')[:60]}")
            sec_content = sec_result.parsed_json or {
                "title": sec_plan.get("section_title", ""),
                "content": "",
                "key_insight": "",
            }
            sections.append(sec_content)

        # Phase 5: 生成概述 + 汇总（使用旧 prompt 作为补充）
        overview_prompt = build_topic_wiki_prompt(
            keyword=keyword,
            paper_contexts=paper_contexts,
            milestones=tl["milestones"],
            seminal=tl["seminal"],
            survey_summary=survey_data.get("summary"),
        )
        overview_result = self.llm.complete_json(
            overview_prompt,
            stage="rag",
            model_override=self.settings.llm_model_deep,
            max_tokens=4096,
        )
        self.llm.trace_result(overview_result, stage="wiki_overview", prompt_digest=f"overview:{keyword}")
        overview_data = overview_result.parsed_json or {}

        # 组装最终 wiki_content
        wiki_content: dict = {
            "overview": overview_data.get("overview", ""),
            "sections": sections,
            "key_findings": overview_data.get(
                "key_findings", []
            ),
            "methodology_evolution": overview_data.get(
                "methodology_evolution", ""
            ),
            "future_directions": overview_data.get(
                "future_directions", []
            ),
            "reading_list": overview_data.get(
                "reading_list", []
            ),
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
