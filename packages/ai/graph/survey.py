"""综述与演化分析服务。"""

from __future__ import annotations

import logging
from collections import defaultdict

from packages.ai.prompts import (
    build_evolution_prompt,
    build_research_gaps_prompt,
    build_survey_prompt,
)
from packages.storage.db import session_scope
from packages.storage.repositories import PaperRepository

logger = logging.getLogger(__name__)


class SurveyService:
    def __init__(self, timeline_svc, llm, settings) -> None:
        self.timeline_svc = timeline_svc
        self.llm = llm
        self.settings = settings

    def weekly_evolution(self, keyword: str, limit: int = 160) -> dict:
        tl = self.timeline_svc.timeline(keyword=keyword, limit=limit)
        by_year: dict[int, list[dict]] = defaultdict(list)
        for item in tl["timeline"]:
            by_year[item["year"]].append(item)
        year_buckets = []
        for year in sorted(by_year.keys())[-6:]:
            group = by_year[year]
            avg = sum(x["seminal_score"] for x in group) / max(len(group), 1)
            top_titles = [x["title"] for x in sorted(group, key=lambda t: -t["seminal_score"])[:3]]
            year_buckets.append(
                {
                    "year": year,
                    "paper_count": len(group),
                    "avg_seminal_score": avg,
                    "top_titles": top_titles,
                }
            )
        prompt = build_evolution_prompt(keyword=keyword, year_buckets=year_buckets)
        llm_result = self.llm.complete_json(
            prompt,
            stage="rag",
            model_override=self.settings.llm_model_skim,
        )
        self.llm.trace_result(
            llm_result, stage="graph_evolution", prompt_digest=f"evolution:{keyword}"
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
        base = self.timeline_svc.timeline(keyword=keyword, limit=limit)
        prompt = build_survey_prompt(keyword, base["milestones"], base["seminal"])
        result = self.llm.complete_json(
            prompt,
            stage="rag",
            model_override=self.settings.llm_model_skim,
        )
        self.llm.trace_result(result, stage="graph_survey", prompt_digest=f"survey:{keyword}")
        survey_obj = result.parsed_json or {
            "overview": "当前样本不足以生成高质量综述。",
            "stages": [],
            "reading_list": [x["title"] for x in base["seminal"][:5]],
            "open_questions": [],
        }
        return {
            "keyword": keyword,
            "summary": survey_obj,
            "milestones": base["milestones"],
            "seminal": base["seminal"],
        }

    def detect_research_gaps(
        self,
        keyword: str,
        limit: int = 120,
    ) -> dict:
        """分析引用网络的稀疏区域，识别研究空白"""
        tl = self.timeline_svc.timeline(keyword=keyword, limit=limit)
        quality = self.timeline_svc.quality_metrics(keyword=keyword, limit=limit)

        # 构造论文数据（含 indegree/outdegree/keywords）
        papers_data = []
        for item in tl["timeline"]:
            papers_data.append(
                {
                    "title": item["title"],
                    "year": item["year"],
                    "indegree": item["indegree"],
                    "outdegree": item["outdegree"],
                    "seminal_score": item["seminal_score"],
                    "keywords": [],
                    "abstract": "",
                }
            )

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
            1 for item in tl["timeline"] if item["indegree"] == 0 and item["outdegree"] == 0
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
            "method_comparison": {
                "dimensions": [],
                "methods": [],
                "underexplored_combinations": [],
            },
            "trend_analysis": {
                "hot_directions": [],
                "declining_areas": [],
                "emerging_opportunities": [],
            },
            "overall_summary": "数据不足，无法完成分析。",
        }

        return {
            "keyword": keyword,
            "network_stats": network_stats,
            "analysis": parsed,
        }
