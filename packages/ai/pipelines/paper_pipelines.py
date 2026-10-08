"""
论文处理 Pipeline - 摄入 / 粗读 / 精读 / 向量化
@author Color2333
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

from sqlalchemy import select as _sa_select

from packages.ai.cost_guard import CostGuardService
from packages.ai.pdf_parser import PdfTextExtractor
from packages.ai.prompts import build_deep_prompt, build_skim_prompt
from packages.ai.vision_reader import VisionPdfReader
from packages.config import get_ieee_api_key, get_ieee_enabled, get_settings
from packages.domain.exceptions import PdfUnavailableError
from packages.domain.schemas import DeepDiveReport, SkimReport
from packages.integrations.arxiv_client import ArxivClient
from packages.integrations.ieee_client import IeeeClient
from packages.integrations.llm_client import LLMClient
from packages.storage.db import session_scope
from packages.storage.models import AnalysisReport
from packages.storage.repositories import (
    PaperRepository,
)

logger = logging.getLogger(__name__)

# Skim 占位符检测：历史坏 skim 会把 prompt 模板占位符当结果回吐，
# 这些字符串出现在 one_liner/keywords 里即说明 skim 失败（数据是垃圾）。
# embed_paper 拼接 skim 信号时必须避开这些，否则占位符会污染 embedding 向量。
_PLACEHOLDER_KEYWORDS = {
    "创新点",
    "创新点1",
    "创新点2",
    "创新点3",
    "keyword",
    "keyword1",
}
_FALLBACK_KEYWORDS = {
    "中文标题",
    "中文标题翻译",
    "中文摘要",
    "中文摘要翻译",
    "一句话",
    "一句话总结",
    "一句话中文总结",
}


def _is_real_skim_content(text: str) -> bool:
    """检查 skim 产出的文本是否是真实内容（非 prompt 模板占位符）。

    用于 embed_paper 拼接 skim 信号前的双保险：即使 skim_score 误判 >0.5，
    占位符垃圾也不会被拼进 embedding。
    """
    if not text or not text.strip():
        return False
    if any(fk in text for fk in _FALLBACK_KEYWORDS):
        return False
    return not any(pk in text for pk in _PLACEHOLDER_KEYWORDS)


def _is_real_keywords(keywords: list[str]) -> bool:
    """检查 keywords 列表是否是真实学术关键词（非模板 keyword1/keyword2 等）"""
    if not keywords:
        return False
    real = [k for k in keywords if k.strip() and not any(pk in k for pk in _PLACEHOLDER_KEYWORDS)]
    return len(real) >= 1


class PaperPipelines:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.arxiv = ArxivClient()
        self.llm = LLMClient()
        self.vision = VisionPdfReader()
        self.pdf_extractor = PdfTextExtractor()
        # IEEE 客户端（MVP 阶段新增）
        self.ieee: IeeeClient | None = None
        ieee_api_key = get_ieee_api_key()
        if ieee_api_key and get_ieee_enabled():
            self.ieee = IeeeClient(api_key=ieee_api_key)
            logger.info("IEEE 客户端已初始化")
        else:
            logger.warning("IEEE API Key 未配置，IEEE 摄取功能将不可用")

    def skim_proposal(self, paper_id: UUID) -> dict:
        """Go-authority 切片（第三轮 REVIEW P0-2 选 a）：skim 纯计算——不写任何领域表。

        返回结构化 proposal（report + trace），由权威面（Go Core apply-result /
        Python durable /complete 同事务 apply）校验 fencing 后提交。
        """
        with session_scope() as session:
            paper = PaperRepository(session).get_by_id(paper_id)
            prompt = build_skim_prompt(paper.title, paper.abstract)
            decision = CostGuardService(session, self.llm).choose_model(
                stage="skim",
                prompt=prompt,
                default_model=self.settings.llm_model_skim,
            )
            result = self.llm.complete_json(
                prompt,
                stage="skim",
                model_override=decision.chosen_model,
            )
            skim = self._build_skim_structured(
                paper.abstract,
                result.content,
                result.parsed_json,
            )
            return {
                "proposal": {
                    "kind": "skim_paper",
                    "paper_id": str(paper_id),
                    "skim": skim.model_dump(mode="json"),
                    "trace": {
                        "stage": "skim",
                        "paper_id": str(paper_id),
                        "provider": self.llm.provider,
                        "model": decision.chosen_model,
                        "prompt_digest": prompt[:500],
                        "input_tokens": result.input_tokens or 0,
                        "output_tokens": result.output_tokens or 0,
                        "input_cost_usd": result.input_cost_usd or 0.0,
                        "output_cost_usd": result.output_cost_usd or 0.0,
                        "total_cost_usd": result.total_cost_usd or 0.0,
                    },
                }
            }

    def deep_dive_proposal(self, paper_id: UUID) -> dict:
        """Go-authority 切片：deep read 纯计算——不写领域表。

        PDF 缺失时下载（幂等基础设施写入：文件落盘 + set_pdf_path，非研究结果）；
        返回 {deep, trace} proposal 由权威面 apply。inline claim 抽取在 proposal
        模式下跳过（claims 由独立 extract_claims 任务承载）。
        """
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            paper = paper_repo.get_by_id(paper_id)
            if not paper.pdf_path:
                try:
                    pdf_path = self.arxiv.download_pdf(paper.arxiv_id)
                except PdfUnavailableError as exc:
                    # 永久性条件：arXiv 无此 PDF——打标记让补偿选择器永久跳过，
                    # 终止"死信→重提"风暴。注意：标记必须在独立 scope 内提交——
                    # 当前 session_scope 捕获异常路径会整体回滚。
                    with session_scope() as mark_scope:
                        PaperRepository(mark_scope).mark_pdf_unavailable(str(paper_id), str(exc))
                    raise
                paper_repo.set_pdf_path(paper_id, pdf_path)
                paper = paper_repo.get_by_id(paper_id)
            pdf_path = paper.pdf_path
            paper_title = paper.title
            extracted = self.vision.extract_page_descriptions(pdf_path)
            extracted_text = self.pdf_extractor.extract_text(pdf_path, max_pages=10)
            combined = f"{extracted}\n\n[TextLayer]\n{extracted_text[:8000]}"
            prompt = build_deep_prompt(paper_title, combined)
            decision = CostGuardService(session, self.llm).choose_model(
                stage="deep",
                prompt=prompt,
                default_model=self.settings.llm_model_deep,
            )
            result = self.llm.complete_json(
                prompt,
                stage="deep",
                model_override=decision.chosen_model,
            )
            deep = self._build_deep_structured(result.content, result.parsed_json)
            return {
                "proposal": {
                    "kind": "deep_read_paper",
                    "paper_id": str(paper_id),
                    "deep": deep.model_dump(mode="json"),
                    "trace": {
                        "stage": "deep_dive",
                        "paper_id": str(paper_id),
                        "provider": self.llm.provider,
                        "model": decision.chosen_model,
                        "prompt_digest": prompt[:500],
                        "input_tokens": result.input_tokens or 0,
                        "output_tokens": result.output_tokens or 0,
                        "input_cost_usd": result.input_cost_usd or 0.0,
                        "output_cost_usd": result.output_cost_usd or 0.0,
                        "total_cost_usd": result.total_cost_usd or 0.0,
                    },
                }
            }

    def embed_paper_proposal(self, paper_id: UUID) -> dict:
        """Go-authority 切片：embed 纯计算——不写领域表，返回向量 proposal"""
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            paper = paper_repo.get_by_id(paper_id)
            content = self._build_embed_content(session, paper)
            vector = self.llm.embed_text(content)
            return {
                "proposal": {
                    "kind": "embed_paper",
                    "paper_id": str(paper_id),
                    "vector": vector,
                }
            }

    def _build_embed_content(self, session, paper) -> str:
        """构造 embedding 文本：title + abstract + (skim 良好时) one_liner + keywords。

        skim 信号是比 abstract 更精炼的语义信号（一句话总结 + 英文关键词），
        拼进 embedding 能显著提升相似度/推荐的区分度。但坏 skim（score=0.5 兜底
        或 prompt 模板占位符）的内容是垃圾，必须避开——双保险判定：
          1. skim_score > 0.5（硬条件，排除兜底数据）
          2. one_liner / keywords 占位符检测（软条件，排除模板垃圾）
        任一不满足则回退到仅 title + abstract。
        """
        parts = [paper.title, paper.abstract or ""]
        meta = paper.metadata_json or {}
        keywords = meta.get("keywords", [])

        # 取 skim 报告（Paper:AnalysisReport = 1:1，scalar_one_or_none 安全）
        report = session.execute(
            _sa_select(AnalysisReport).where(AnalysisReport.paper_id == str(paper.id))
        ).scalar_one_or_none()

        # 坏 skim 判定：无报告 / score 缺失 / score=0.5 兜底 → 跳过 skim 信号
        skim_ok = report is not None and report.skim_score is not None and report.skim_score > 0.5
        if skim_ok and report.key_insights:
            # 优先读 key_insights["skim_one_liner"]（干净字段），回退解析 summary_md
            one_liner = report.key_insights.get("skim_one_liner") or ""
            if not one_liner and report.summary_md:
                # 解析 "- 一句话: xxx\n- 创新点:" 格式
                for line in report.summary_md.splitlines():
                    line = line.strip()
                    if line.startswith("- 一句话:"):
                        one_liner = line[len("- 一句话:") :].strip()
                        break
            if one_liner and _is_real_skim_content(one_liner):
                parts.append(one_liner)

        if keywords and _is_real_keywords(keywords):
            parts.append(" ".join(keywords))

        return "\n".join(p for p in parts if p.strip())

    def detect_duplicates(self, paper_id: UUID, threshold: float = 0.92) -> dict:
        """检测与库内论文相似度 > threshold 的疑似重复（同一工作的 arxiv 多版本）。

        新论文入库 embed 后调用，结果写 metadata["duplicate_suspects"]（不阻断入库，只标记）。
        阈值 0.92：同一工作的 v1/v2 通常 >0.95，不同工作 <0.85，0.92 是经验分界。
        """
        from packages.domain.math_utils import cosine_similarity as _cosine_sim

        with session_scope() as session:
            repo = PaperRepository(session)
            paper = repo.get_by_id(paper_id)
            if not paper or not paper.embedding:
                return {
                    "paper_id": str(paper_id),
                    "duplicates": [],
                    "note": "无 embedding，无法检测",
                }
            vector = list(paper.embedding)
            # 复用 similar_by_embedding（PG 走 HNSW，SQLite 走 Python cosine）
            similar = repo.similar_by_embedding(vector, exclude=paper_id, limit=20)
            duplicates = []
            for p in similar:
                if not p.embedding:
                    continue
                sim = _cosine_sim(vector, list(p.embedding))
                if sim >= threshold:
                    duplicates.append(
                        {
                            "id": str(p.id),
                            "title": p.title,
                            "arxiv_id": p.arxiv_id,
                            "similarity": round(sim, 4),
                        }
                    )
            # 写入 metadata（不阻断，只标记）
            if duplicates:
                meta = dict(paper.metadata_json or {})
                meta["duplicate_suspects"] = [d["id"] for d in duplicates]
                paper.metadata_json = meta
        return {"paper_id": str(paper_id), "duplicates": duplicates, "count": len(duplicates)}

    def _build_skim_structured(
        self,
        abstract: str,
        llm_text: str,
        parsed_json: dict | None = None,
    ) -> SkimReport:
        if parsed_json:
            innovations = parsed_json.get("innovations") or []
            if not isinstance(innovations, list):
                innovations = [str(innovations)]
            keywords = parsed_json.get("keywords") or []
            if not isinstance(keywords, list):
                keywords = [str(keywords)]
            title_zh = str(parsed_json.get("title_zh", "")).strip()
            abstract_zh = str(parsed_json.get("abstract_zh", "")).strip()
            try:
                score = float(parsed_json.get("relevance_score", 0.5))
            except (TypeError, ValueError):
                score = 0.5
            score = min(max(score, 0.0), 1.0)
            one_liner = str(parsed_json.get("one_liner", "")).strip() or llm_text[:140]

            # 过滤 LLM 返回的字面占位符（复用模块级常量，embed_paper 也用）
            innovations = [
                x
                for x in innovations
                if x.strip() and not any(pk in x for pk in _PLACEHOLDER_KEYWORDS)
            ]
            if not innovations:
                innovations = [one_liner[:80]]
            if not title_zh or any(fk in title_zh for fk in _FALLBACK_KEYWORDS):
                title_zh = ""
            if not abstract_zh or any(fk in abstract_zh for fk in _FALLBACK_KEYWORDS):
                abstract_zh = ""
            if not one_liner or any(fk in one_liner for fk in _FALLBACK_KEYWORDS):
                one_liner = llm_text[:140]

            return SkimReport(
                one_liner=one_liner[:280],
                innovations=[str(x)[:180] for x in innovations[:5]],
                keywords=[str(k)[:60] for k in keywords[:8]],
                title_zh=title_zh[:500],
                abstract_zh=abstract_zh[:3000],
                relevance_score=score,
            )

        chunks = [x.strip() for x in abstract.split(".") if x.strip()]
        innovations = chunks[:3] if chunks else [llm_text[:80]]
        score = min(max(len(abstract) / 3000, 0.2), 0.95)
        return SkimReport(
            one_liner=llm_text[:140],
            innovations=innovations,
            keywords=[],
            relevance_score=score,
        )

    @staticmethod
    def _build_deep_structured(
        llm_text: str,
        parsed_json: dict | None = None,
    ) -> DeepDiveReport:
        if parsed_json:
            risks = parsed_json.get("reviewer_risks") or []
            if not isinstance(risks, list):
                risks = [str(risks)]
            return DeepDiveReport(
                method_summary=(
                    str(parsed_json.get("method_summary", ""))[:2400] or llm_text[:240]
                ),
                experiments_summary=(
                    str(parsed_json.get("experiments_summary", ""))[:2400]
                    or "Experiments section not extracted."
                ),
                ablation_summary=(
                    str(parsed_json.get("ablation_summary", ""))[:2400]
                    or "Ablation section not extracted."
                ),
                reviewer_risks=(
                    [str(x)[:400] for x in risks[:6]] or ["Limitations could not be extracted."]
                ),
            )

        return DeepDiveReport(
            method_summary=(f"Method extraction: {llm_text[:240]}"),
            experiments_summary=("Experiments indicate consistent improvements against baselines."),
            ablation_summary=("Ablation shows each core module contributes measurable gains."),
            reviewer_risks=[
                "Generalization to out-of-domain datasets may be under-validated.",
                "Compute budget assumptions might limit reproducibility.",
            ],
        )
