"""论文/主题 Wiki 生成服务。"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

from packages.ai.prompts import (
    build_paper_wiki_prompt,
    build_wiki_outline_prompt,
    build_wiki_section_prompt,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


class WikiService:
    def __init__(
        self,
        citation_svc,
        timeline_svc,
        survey_svc,
        llm,
        context_gatherer,
        scholar,
        settings,
    ) -> None:
        self.citation_svc = citation_svc
        self.timeline_svc = timeline_svc
        self.survey_svc = survey_svc
        self.llm = llm
        self.context_gatherer = context_gatherer
        self.scholar = scholar
        self.settings = settings

    def paper_wiki(self, paper_id: str) -> dict:
        tree = self.citation_svc.citation_tree(root_paper_id=paper_id, depth=2)

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
            scholar_meta = self.scholar.fetch_batch_metadata(all_titles, max_papers=6)
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
        self.llm.trace_result(
            result,
            stage="wiki_paper",
            paper_id=paper_id,
            prompt_digest=f"paper_wiki:{p_title[:60]}",
        )
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
        wiki_content["citation_contexts"] = ctx.get("citation_contexts", [])[:20]
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
            md_parts.append(f"\n## 方法论\n\n{wiki_content['methodology']}")
        if wiki_content.get("significance"):
            md_parts.append(f"\n## 学术意义\n\n{wiki_content['significance']}")
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
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> dict:
        def _progress(pct: float, msg: str):
            if progress_callback:
                progress_callback(msg, int(pct * 100), 100)

        # Phase 0: 并行收集数据
        _progress(0.05, "收集时间线和综述数据...")
        tl = self.timeline_svc.timeline(keyword=keyword, limit=limit)
        survey_data = self.survey_svc.survey(keyword=keyword, limit=limit)

        _progress(0.15, "收集论文上下文和引用关系...")
        # Phase 1: 富化上下文（向量搜索 + 引用上下文 + PDF）
        ctx = self.context_gatherer.gather_topic_context(keyword, limit=limit)
        paper_contexts = ctx.get("paper_contexts", [])[:25]
        citation_contexts = ctx.get("citation_contexts", [])[:30]
        pdf_excerpts = ctx.get("pdf_excerpts", [])[:5]

        # Phase 2: Semantic Scholar 元数据增强
        scholar_meta: list[dict] = []
        try:
            top_titles = [s["title"] for s in tl.get("seminal", [])[:8] if s.get("title")]
            scholar_meta = self.scholar.fetch_batch_metadata(top_titles, max_papers=8)
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
        self.llm.trace_result(
            outline_result, stage="wiki_outline", prompt_digest=f"outline:{keyword}"
        )
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
            keyword,
            sec_plans,
            all_sources_text,
        )

        _progress(0.75, "生成概述和总结...")
        # Phase 5: 生成概述（直接输出文本）+ 结构化汇总（JSON）
        # 5a: 文本概述
        section_titles = ", ".join(s.get("title", "") for s in sections)
        survey_overview = survey_data.get("summary", {}).get("overview", "")[:600]
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
            overview_result,
            stage="wiki_overview",
            prompt_digest=f"overview:{keyword}",
        )
        overview_text = (overview_result.content or "").strip()
        overview_text = re.sub(r"^```(?:markdown)?\s*\n?", "", overview_text)
        overview_text = re.sub(r"\n?```\s*$", "", overview_text)

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
            summary_result,
            stage="wiki_summary",
            prompt_digest=f"summary:{keyword}",
        )
        summary_data = summary_result.parsed_json or {}

        # 组装最终 wiki_content
        wiki_content: dict = {
            "overview": overview_text,
            "sections": sections,
            "key_findings": summary_data.get("key_findings", []),
            "methodology_evolution": "",
            "future_directions": summary_data.get("future_directions", []),
            "reading_list": summary_data.get("reading_list", []),
            "citation_contexts": citation_contexts[:20],
            "pdf_excerpts": pdf_excerpts,
            "scholar_metadata": scholar_meta,
        }

        # 备用 markdown
        md_parts = [f"# {keyword}\n\n{wiki_content.get('overview', '')}"]
        for sec in sections:
            md_parts.append(f"\n## {sec.get('title', '')}\n\n{sec.get('content', '')}")
        if wiki_content.get("methodology_evolution"):
            md_parts.append(f"\n## 方法论演化\n\n{wiki_content['methodology_evolution']}")
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
            parts.append(f"\n## PDF 全文摘录（前 2000 字）:\n{pdf_excerpt[:2000]}")
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
        self,
        keyword: str,
        sec_plan: dict,
        all_sources_text: str,
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
            sec_result,
            stage="wiki_section",
            prompt_digest=f"section:{sec_title[:60]}",
        )
        content = sec_result.content or ""
        content = re.sub(r"^```(?:markdown)?\s*\n?", "", content.strip())
        content = re.sub(r"\n?```\s*$", "", content.strip())
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
                    keyword,
                    plan,
                    all_sources_text,
                ): idx
                for idx, plan in enumerate(sec_plans)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    sections[idx] = future.result()
                    logger.info(
                        "wiki section %d/%d 完成: %s",
                        idx + 1,
                        len(sec_plans),
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
                f"[PDF{i}] {ex.get('title', 'N/A')}\nExcerpt: {ex.get('excerpt', '')[:500]}"
            )
        return "\n\n".join(parts)
