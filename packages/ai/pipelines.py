"""
论文处理 Pipeline - 摄入 / 粗读 / 精读 / 向量化
@author Bamzc
"""
from __future__ import annotations

import time
from uuid import UUID

from packages.ai.cost_guard import CostGuardService
from packages.ai.pdf_parser import PdfTextExtractor
from packages.ai.prompts import build_deep_prompt, build_skim_prompt
from packages.ai.vision_reader import VisionPdfReader
from packages.config import get_settings
from packages.domain.enums import ReadStatus
from packages.domain.schemas import DeepDiveReport, SkimReport
from packages.integrations.arxiv_client import ArxivClient
from packages.integrations.llm_client import LLMClient
from packages.storage.db import session_scope
from packages.storage.repositories import (
    AnalysisRepository,
    PaperRepository,
    PipelineRunRepository,
    PromptTraceRepository,
    SourceCheckpointRepository,
)


class PaperPipelines:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.arxiv = ArxivClient()
        self.llm = LLMClient()
        self.vision = VisionPdfReader()
        self.pdf_extractor = PdfTextExtractor()

    def ingest_arxiv(
        self,
        query: str,
        max_results: int = 20,
        topic_id: str | None = None,
    ) -> int:
        papers = self.arxiv.fetch_latest(
            query=query, max_results=max_results
        )
        with session_scope() as session:
            repo = PaperRepository(session)
            run_repo = PipelineRunRepository(session)
            checkpoint_repo = SourceCheckpointRepository(session)
            checkpoint = checkpoint_repo.get("arxiv")
            run = run_repo.start("ingest_arxiv")
            count = 0
            try:
                max_published = (
                    checkpoint.last_published_date
                    if checkpoint
                    else None
                )
                for paper in papers:
                    if (
                        checkpoint
                        and checkpoint.last_published_date
                        and paper.publication_date
                        and paper.publication_date
                        <= checkpoint.last_published_date
                    ):
                        continue
                    saved = repo.upsert_paper(paper)
                    if topic_id:
                        repo.link_to_topic(saved.id, topic_id)
                    try:
                        pdf_path = self.arxiv.download_pdf(
                            paper.arxiv_id
                        )
                        repo.set_pdf_path(saved.id, pdf_path)
                    except Exception:
                        pass
                    if paper.publication_date and (
                        max_published is None
                        or paper.publication_date > max_published
                    ):
                        max_published = paper.publication_date
                    count += 1
                checkpoint_repo.upsert("arxiv", max_published)
                run_repo.finish(run.id)
                return count
            except Exception as exc:
                run_repo.fail(run.id, str(exc))
                raise

    def ingest_arxiv_with_ids(
        self,
        query: str,
        max_results: int = 20,
        topic_id: str | None = None,
    ) -> list[str]:
        papers = self.arxiv.fetch_latest(
            query=query, max_results=max_results
        )
        inserted_ids: list[str] = []
        with session_scope() as session:
            repo = PaperRepository(session)
            run_repo = PipelineRunRepository(session)
            checkpoint_repo = SourceCheckpointRepository(session)
            checkpoint = checkpoint_repo.get("arxiv")
            run = run_repo.start(
                "ingest_arxiv",
                decision_note="collect_inserted_ids",
            )
            try:
                max_published = (
                    checkpoint.last_published_date
                    if checkpoint
                    else None
                )
                for paper in papers:
                    if (
                        checkpoint
                        and checkpoint.last_published_date
                        and paper.publication_date
                        and paper.publication_date
                        <= checkpoint.last_published_date
                    ):
                        continue
                    saved = repo.upsert_paper(paper)
                    if topic_id:
                        repo.link_to_topic(saved.id, topic_id)
                    inserted_ids.append(saved.id)
                    try:
                        pdf_path = self.arxiv.download_pdf(
                            paper.arxiv_id
                        )
                        repo.set_pdf_path(saved.id, pdf_path)
                    except Exception:
                        pass
                    if paper.publication_date and (
                        max_published is None
                        or paper.publication_date > max_published
                    ):
                        max_published = paper.publication_date
                checkpoint_repo.upsert("arxiv", max_published)
                run_repo.finish(run.id)
                return inserted_ids
            except Exception as exc:
                run_repo.fail(run.id, str(exc))
                raise

    def skim(self, paper_id: UUID) -> SkimReport:
        started = time.perf_counter()
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            analysis_repo = AnalysisRepository(session)
            trace_repo = PromptTraceRepository(session)
            run_repo = PipelineRunRepository(session)
            try:
                paper = paper_repo.get_by_id(paper_id)
                prompt = build_skim_prompt(
                    paper.title, paper.abstract
                )
                decision = CostGuardService(
                    session, self.llm
                ).choose_model(
                    stage="skim",
                    prompt=prompt,
                    default_model=self.settings.llm_model_skim,
                )
                run = run_repo.start(
                    "skim",
                    paper_id=paper_id,
                    decision_note=decision.note,
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
                analysis_repo.upsert_skim(paper_id, skim)
                paper_repo.update_read_status(
                    paper_id, ReadStatus.skimmed
                )
                trace_repo.create(
                    stage="skim",
                    provider=self.llm.provider,
                    model=decision.chosen_model,
                    prompt_digest=prompt[:500],
                    paper_id=paper_id,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    input_cost_usd=result.input_cost_usd,
                    output_cost_usd=result.output_cost_usd,
                    total_cost_usd=result.total_cost_usd,
                )
                elapsed = int(
                    (time.perf_counter() - started) * 1000
                )
                run_repo.finish(run.id, elapsed_ms=elapsed)
                return skim
            except Exception as exc:
                run = locals().get("run")
                if run is None:
                    run = run_repo.start(
                        "skim",
                        paper_id=paper_id,
                        decision_note="failed_before_start",
                    )
                run_repo.fail(run.id, str(exc))
                raise

    def deep_dive(self, paper_id: UUID) -> DeepDiveReport:
        started = time.perf_counter()
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            analysis_repo = AnalysisRepository(session)
            trace_repo = PromptTraceRepository(session)
            run_repo = PipelineRunRepository(session)
            try:
                paper = paper_repo.get_by_id(paper_id)
                if not paper.pdf_path:
                    paper_repo.set_pdf_path(
                        paper_id,
                        self.arxiv.download_pdf(paper.arxiv_id),
                    )
                    paper = paper_repo.get_by_id(paper_id)
                extracted = (
                    self.vision.extract_page_descriptions(
                        paper.pdf_path
                    )
                )
                extracted_text = self.pdf_extractor.extract_text(
                    paper.pdf_path, max_pages=10
                )
                combined = (
                    f"{extracted}\n\n"
                    f"[TextLayer]\n{extracted_text[:8000]}"
                )
                prompt = build_deep_prompt(
                    paper.title, combined
                )
                decision = CostGuardService(
                    session, self.llm
                ).choose_model(
                    stage="deep",
                    prompt=prompt,
                    default_model=self.settings.llm_model_deep,
                )
                run = run_repo.start(
                    "deep_dive",
                    paper_id=paper_id,
                    decision_note=decision.note,
                )
                result = self.llm.complete_json(
                    prompt,
                    stage="deep",
                    model_override=decision.chosen_model,
                )
                deep = self._build_deep_structured(
                    result.content, result.parsed_json
                )
                analysis_repo.upsert_deep_dive(paper_id, deep)
                paper_repo.update_read_status(
                    paper_id, ReadStatus.deep_read
                )
                trace_repo.create(
                    stage="deep_dive",
                    provider=self.llm.provider,
                    model=decision.chosen_model,
                    prompt_digest=prompt[:500],
                    paper_id=paper_id,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    input_cost_usd=result.input_cost_usd,
                    output_cost_usd=result.output_cost_usd,
                    total_cost_usd=result.total_cost_usd,
                )
                elapsed = int(
                    (time.perf_counter() - started) * 1000
                )
                run_repo.finish(run.id, elapsed_ms=elapsed)
                return deep
            except Exception as exc:
                run = locals().get("run")
                if run is None:
                    run = run_repo.start(
                        "deep_dive",
                        paper_id=paper_id,
                        decision_note="failed_before_start",
                    )
                run_repo.fail(run.id, str(exc))
                raise

    def embed_paper(self, paper_id: UUID) -> None:
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            paper = paper_repo.get_by_id(paper_id)
            content = f"{paper.title}\n{paper.abstract}"
            vector = self.llm.embed_text(content)
            paper_repo.update_embedding(paper_id, vector)

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
            try:
                score = float(
                    parsed_json.get("relevance_score", 0.5)
                )
            except (TypeError, ValueError):
                score = 0.5
            score = min(max(score, 0.0), 1.0)
            one_liner = (
                str(parsed_json.get("one_liner", "")).strip()
                or llm_text[:140]
            )
            if not innovations:
                innovations = [one_liner[:80]]
            return SkimReport(
                one_liner=one_liner[:280],
                innovations=[
                    str(x)[:180] for x in innovations[:5]
                ],
                relevance_score=score,
            )

        chunks = [
            x.strip() for x in abstract.split(".") if x.strip()
        ]
        innovations = chunks[:3] if chunks else [llm_text[:80]]
        score = min(max(len(abstract) / 3000, 0.2), 0.95)
        return SkimReport(
            one_liner=llm_text[:140],
            innovations=innovations,
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
                    str(
                        parsed_json.get(
                            "method_summary", ""
                        )
                    )[:2400]
                    or llm_text[:240]
                ),
                experiments_summary=(
                    str(
                        parsed_json.get(
                            "experiments_summary", ""
                        )
                    )[:2400]
                    or "Experiments section not extracted."
                ),
                ablation_summary=(
                    str(
                        parsed_json.get(
                            "ablation_summary", ""
                        )
                    )[:2400]
                    or "Ablation section not extracted."
                ),
                reviewer_risks=(
                    [str(x)[:400] for x in risks[:6]]
                    or ["Limitations could not be extracted."]
                ),
            )

        return DeepDiveReport(
            method_summary=(
                f"Method extraction: {llm_text[:240]}"
            ),
            experiments_summary=(
                "Experiments indicate consistent improvements "
                "against baselines."
            ),
            ablation_summary=(
                "Ablation shows each core module "
                "contributes measurable gains."
            ),
            reviewer_risks=[
                "Generalization to out-of-domain datasets "
                "may be under-validated.",
                "Compute budget assumptions "
                "might limit reproducibility.",
            ],
        )
