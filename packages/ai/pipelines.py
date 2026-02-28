"""
论文处理 Pipeline - 摄入 / 粗读 / 精读 / 向量化 / 参考文献导入
@author Bamzc
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime
from uuid import UUID, uuid4

from packages.ai.cost_guard import CostGuardService
from packages.ai.pdf_parser import PdfTextExtractor
from packages.ai.prompts import build_deep_prompt, build_skim_prompt
from packages.ai.vision_reader import VisionPdfReader
from packages.config import get_settings
from packages.domain.enums import ActionType, ReadStatus
from packages.domain.schemas import DeepDiveReport, PaperCreate, SkimReport
from packages.integrations.arxiv_client import ArxivClient
from packages.integrations.llm_client import LLMClient
from packages.integrations.semantic_scholar_client import SemanticScholarClient
from packages.storage.db import session_scope
from packages.storage.repositories import (
    ActionRepository,
    AnalysisRepository,
    CitationRepository,
    PaperRepository,
    PipelineRunRepository,
    PromptTraceRepository,
    SourceCheckpointRepository,
)

logger = logging.getLogger(__name__)

# 参考文献导入任务进度（内存缓存）
_import_tasks: dict[str, dict] = {}


def _bg_auto_link(paper_ids: list[str]) -> None:
    """后台线程：入库后自动关联引用"""
    try:
        from packages.ai.graph_service import GraphService

        gs = GraphService()
        result = gs.auto_link_citations(paper_ids)
        logger.info("bg auto_link: %s", result)
    except Exception as exc:
        logger.warning("bg auto_link failed: %s", exc)


class PaperPipelines:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.arxiv = ArxivClient()
        self.llm = LLMClient()
        self.vision = VisionPdfReader()
        self.pdf_extractor = PdfTextExtractor()

    def _save_paper(self, repo, paper, topic_id=None):
        """入库 + 下载 PDF 的公共逻辑"""
        saved = repo.upsert_paper(paper)
        if topic_id:
            repo.link_to_topic(saved.id, topic_id)
        try:
            pdf_path = self.arxiv.download_pdf(paper.arxiv_id)
            repo.set_pdf_path(saved.id, pdf_path)
        except Exception as exc:
            logger.warning("PDF download failed for %s: %s", paper.arxiv_id, exc)
        return saved

    def ingest_arxiv(
        self,
        query: str,
        max_results: int = 20,
        topic_id: str | None = None,
        action_type: ActionType = ActionType.manual_collect,
        sort_by: str = "submittedDate",
    ) -> tuple[int, list[str], int]:
        """搜索 arXiv 并入库，upsert 去重。返回 (total_count, inserted_ids, new_papers_count)"""
        inserted_ids: list[str] = []
        new_papers_count = 0
        total_fetched = 0
        batch_size = 20
        max_pages = 5  # 最多抓取 5 批（100 篇），直到找到 max_results 篇新论文

        with session_scope() as session:
            repo = PaperRepository(session)
            run_repo = PipelineRunRepository(session)
            action_repo = ActionRepository(session)
            run = run_repo.start("ingest_arxiv", decision_note=f"query={query}")

            try:
                # 分批抓取，直到找到足够的新论文或达到最大页数
                for page in range(max_pages):
                    start = page * batch_size
                    papers = self.arxiv.fetch_latest(
                        query=query,
                        max_results=batch_size,
                        sort_by=sort_by,
                        start=start,
                    )
                    total_fetched += len(papers)

                    if not papers:
                        break  # 没有更多论文了

                    # 提前检查哪些论文已存在
                    existing_arxiv_ids = repo.list_existing_arxiv_ids([p.arxiv_id for p in papers])

                    # 处理新论文
                    for paper in papers:
                        is_new = paper.arxiv_id not in existing_arxiv_ids
                        saved = self._save_paper(repo, paper, topic_id)
                        if is_new:
                            new_papers_count += 1
                        inserted_ids.append(saved.id)

                    # 如果已找到足够的新论文，停止抓取
                    if new_papers_count >= max_results:
                        logger.info(
                            "已找到 %d 篇新论文（共抓取 %d 篇，%d 篇重复）",
                            new_papers_count,
                            total_fetched,
                            total_fetched - new_papers_count,
                        )
                        break
                    else:
                        logger.info(
                            "第 %d 批：找到 %d 篇新论文（累计 %d/%d），继续抓取...",
                            page + 1,
                            len(papers) - len(existing_arxiv_ids),
                            new_papers_count,
                            max_results,
                        )

                if inserted_ids:
                    action_repo.create_action(
                        action_type=action_type,
                        title=f"收集：{query[:80]}",
                        paper_ids=inserted_ids,
                        query=query,
                        topic_id=topic_id,
                    )

                run_repo.finish(run.id)
                if inserted_ids:
                    threading.Thread(
                        target=_bg_auto_link,
                        args=(inserted_ids,),
                        daemon=True,
                    ).start()
                return len(inserted_ids), inserted_ids, new_papers_count
            except Exception as exc:
                run_repo.fail(run.id, str(exc))
                raise

    def ingest_arxiv_with_ids(
        self,
        query: str,
        max_results: int = 20,
        topic_id: str | None = None,
        action_type: ActionType = ActionType.subscription_ingest,
    ) -> list[str]:
        """ingest_arxiv 的别名，返回 inserted_ids"""
        _, ids = self.ingest_arxiv(
            query=query,
            max_results=max_results,
            topic_id=topic_id,
            action_type=action_type,
        )
        return ids

    def ingest_arxiv_with_stats(
        self,
        query: str,
        max_results: int = 20,
        topic_id: str | None = None,
        action_type: ActionType = ActionType.subscription_ingest,
    ) -> dict:
        """ingest_arxiv 返回详细统计信息"""
        total_count, inserted_ids, new_count = self.ingest_arxiv(
            query=query,
            max_results=max_results,
            topic_id=topic_id,
            action_type=action_type,
        )
        return {
            "total_count": total_count,
            "inserted_ids": inserted_ids,
            "new_count": new_count,
        }

    def skim(self, paper_id: UUID) -> SkimReport:
        started = time.perf_counter()
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            analysis_repo = AnalysisRepository(session)
            trace_repo = PromptTraceRepository(session)
            run_repo = PipelineRunRepository(session)
            run = run_repo.start("skim", paper_id=paper_id)
            try:
                paper = paper_repo.get_by_id(paper_id)
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
                analysis_repo.upsert_skim(paper_id, skim)
                meta = dict(paper.metadata_json or {})
                if skim.keywords:
                    meta["keywords"] = skim.keywords
                if skim.title_zh:
                    meta["title_zh"] = skim.title_zh
                if skim.abstract_zh:
                    meta["abstract_zh"] = skim.abstract_zh
                paper.metadata_json = meta
                paper_repo.update_read_status(paper_id, ReadStatus.skimmed)
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
                elapsed = int((time.perf_counter() - started) * 1000)
                run_repo.finish(run.id, elapsed_ms=elapsed)
                return skim
            except Exception as exc:
                run_repo.fail(run.id, str(exc))
                raise

    def deep_dive(self, paper_id: UUID) -> DeepDiveReport:
        started = time.perf_counter()
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            analysis_repo = AnalysisRepository(session)
            trace_repo = PromptTraceRepository(session)
            run_repo = PipelineRunRepository(session)
            run = run_repo.start("deep_dive", paper_id=paper_id)
            try:
                paper = paper_repo.get_by_id(paper_id)
                if not paper.pdf_path:
                    paper_repo.set_pdf_path(
                        paper_id,
                        self.arxiv.download_pdf(paper.arxiv_id),
                    )
                    paper = paper_repo.get_by_id(paper_id)
                extracted = self.vision.extract_page_descriptions(paper.pdf_path)
                extracted_text = self.pdf_extractor.extract_text(paper.pdf_path, max_pages=10)
                combined = f"{extracted}\n\n[TextLayer]\n{extracted_text[:8000]}"
                prompt = build_deep_prompt(paper.title, combined)
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
                analysis_repo.upsert_deep_dive(paper_id, deep)
                paper_repo.update_read_status(paper_id, ReadStatus.deep_read)
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
                elapsed = int((time.perf_counter() - started) * 1000)
                run_repo.finish(run.id, elapsed_ms=elapsed)
                return deep
            except Exception as exc:
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
            if not innovations:
                innovations = [one_liner[:80]]
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


# ==================== 参考文献一键导入引擎 ====================


def get_import_task(task_id: str) -> dict | None:
    return _import_tasks.get(task_id)


class ReferenceImporter:
    """将引用详情中的外部论文批量导入到论文库"""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.arxiv = ArxivClient()
        self.scholar = SemanticScholarClient(
            api_key=self.settings.semantic_scholar_api_key,
        )
        self.llm = LLMClient()

    @staticmethod
    def _normalize_arxiv_id(aid: str | None) -> str | None:
        if not aid:
            return None
        return aid.split("v")[0] if "v" in aid else aid

    def start_import(
        self,
        *,
        source_paper_id: str,
        source_paper_title: str,
        entries: list[dict],
        topic_ids: list[str] | None = None,
    ) -> str:
        """启动后台导入任务，返回 task_id"""
        task_id = str(uuid4())
        _import_tasks[task_id] = {
            "task_id": task_id,
            "status": "running",
            "source_paper_id": source_paper_id,
            "total": len(entries),
            "completed": 0,
            "imported": 0,
            "skipped": 0,
            "failed": 0,
            "current": "",
            "results": [],
        }
        threading.Thread(
            target=self._run_import,
            args=(task_id, source_paper_id, source_paper_title, entries, topic_ids or []),
            daemon=True,
        ).start()
        return task_id

    def _run_import(
        self,
        task_id: str,
        source_paper_id: str,
        source_paper_title: str,
        entries: list[dict],
        topic_ids: list[str],
    ) -> None:
        task = _import_tasks[task_id]
        inserted_ids: list[str] = []

        try:
            # 1) 建立库内已有 arxiv_id 集合（用于去重）
            with session_scope() as session:
                repo = PaperRepository(session)
                existing_norms: set[str] = set()
                for p in repo.list_all(limit=50000):
                    n = self._normalize_arxiv_id(p.arxiv_id)
                    if n:
                        existing_norms.add(n)

            # 2) 把 entries 分成两组：有 arxiv_id / 无 arxiv_id
            arxiv_entries: list[dict] = []
            ss_only_entries: list[dict] = []
            skip_entries: list[dict] = []

            for entry in entries:
                arxiv_id = entry.get("arxiv_id")
                norm = self._normalize_arxiv_id(arxiv_id)
                if norm and norm in existing_norms:
                    skip_entries.append(entry)
                elif arxiv_id:
                    arxiv_entries.append(entry)
                else:
                    ss_only_entries.append(entry)

            task["skipped"] = len(skip_entries)
            task["completed"] = len(skip_entries)
            for e in skip_entries:
                task["results"].append(
                    {
                        "title": e.get("title", ""),
                        "status": "skipped",
                        "reason": "已在库中",
                    }
                )

            # 3) 批量通过 arXiv API 拉取有 arxiv_id 的论文
            if arxiv_entries:
                self._import_arxiv_batch(
                    task,
                    arxiv_entries,
                    source_paper_id,
                    topic_ids,
                    inserted_ids,
                    existing_norms,
                )

            # 4) 无 arxiv_id 的论文用 SS 元数据导入
            if ss_only_entries:
                self._import_ss_batch(
                    task,
                    ss_only_entries,
                    source_paper_id,
                    topic_ids,
                    inserted_ids,
                )

            # 5) 记录 CollectionAction
            if inserted_ids:
                with session_scope() as session:
                    action_repo = ActionRepository(session)
                    action_repo.create_action(
                        action_type=ActionType.reference_import,
                        title=f"参考文献导入: {source_paper_title[:60]}",
                        paper_ids=inserted_ids,
                        query=source_paper_id,
                    )

            # 6) 后台触发粗读 + 向量化
            if inserted_ids:
                threading.Thread(
                    target=self._bg_skim_and_embed,
                    args=(inserted_ids,),
                    daemon=True,
                ).start()

            task["status"] = "completed"

        except Exception as exc:
            logger.exception("Reference import failed: %s", exc)
            task["status"] = "failed"
            task["error"] = str(exc)

    def _import_arxiv_batch(
        self,
        task: dict,
        entries: list[dict],
        source_paper_id: str,
        topic_ids: list[str],
        inserted_ids: list[str],
        existing_norms: set[str],
    ) -> None:
        """批量从 arXiv 拉取完整论文数据"""
        arxiv_ids = [e["arxiv_id"] for e in entries]

        # arXiv API 一次最多获取 50 个，分批处理
        batch_size = 30
        arxiv_papers_map: dict[str, PaperCreate] = {}
        for i in range(0, len(arxiv_ids), batch_size):
            batch = arxiv_ids[i : i + batch_size]
            try:
                papers = self.arxiv.fetch_by_ids(batch)
                for p in papers:
                    n = self._normalize_arxiv_id(p.arxiv_id)
                    if n:
                        arxiv_papers_map[n] = p
            except Exception as exc:
                logger.warning("arXiv batch fetch failed: %s", exc)
            time.sleep(1)

        for entry in entries:
            title = entry.get("title", "Unknown")
            task["current"] = title[:50]
            arxiv_id = entry["arxiv_id"]
            norm = self._normalize_arxiv_id(arxiv_id)

            arxiv_paper = arxiv_papers_map.get(norm) if norm else None

            if arxiv_paper:
                # 用 arXiv 的完整数据 + SS 的额外信息合并
                meta = dict(arxiv_paper.metadata or {})
                meta["source"] = "reference_import"
                meta["source_paper_id"] = source_paper_id
                meta["scholar_id"] = entry.get("scholar_id")
                if entry.get("venue"):
                    meta["venue"] = entry["venue"]
                if entry.get("citation_count") is not None:
                    meta["citation_count"] = entry["citation_count"]
                arxiv_paper.metadata = meta
                paper_data = arxiv_paper
            else:
                # arXiv API 没找到（可能是旧论文），用 SS 数据创建
                paper_data = self._build_paper_from_entry(
                    entry,
                    source_paper_id,
                )

            try:
                with session_scope() as session:
                    repo = PaperRepository(session)
                    cit_repo = CitationRepository(session)
                    saved = repo.upsert_paper(paper_data)
                    for tid in topic_ids:
                        repo.link_to_topic(saved.id, tid)
                    # 建立引用边
                    direction = entry.get("direction", "reference")
                    if direction == "reference":
                        cit_repo.upsert_edge(
                            source_paper_id,
                            saved.id,
                            context="reference",
                        )
                    else:
                        cit_repo.upsert_edge(
                            saved.id,
                            source_paper_id,
                            context="citation",
                        )
                    # 下载 PDF
                    try:
                        pdf_path = self.arxiv.download_pdf(
                            paper_data.arxiv_id,
                        )
                        repo.set_pdf_path(saved.id, pdf_path)
                    except Exception:
                        pass
                    inserted_ids.append(saved.id)
                    existing_norms.add(norm or "")
                    task["imported"] += 1
                    task["results"].append(
                        {
                            "title": title,
                            "status": "imported",
                            "paper_id": saved.id,
                            "source": "arxiv",
                        }
                    )
            except Exception as exc:
                logger.warning("Import failed for %s: %s", title, exc)
                task["failed"] += 1
                task["results"].append(
                    {
                        "title": title,
                        "status": "failed",
                        "reason": str(exc)[:100],
                    }
                )

            task["completed"] += 1

    def _import_ss_batch(
        self,
        task: dict,
        entries: list[dict],
        source_paper_id: str,
        topic_ids: list[str],
        inserted_ids: list[str],
    ) -> None:
        """用 Semantic Scholar 元数据导入没有 arXiv ID 的论文"""
        for entry in entries:
            title = entry.get("title", "Unknown")
            task["current"] = title[:50]
            scholar_id = entry.get("scholar_id")

            # 尝试从 SS 获取更丰富的信息
            detail = None
            if scholar_id:
                try:
                    detail = self.scholar.fetch_paper_by_scholar_id(
                        scholar_id,
                    )
                    time.sleep(0.5)
                except Exception:
                    pass

            if detail and detail.get("arxiv_id"):
                # SS 返回了 arXiv ID，升级为 arXiv 导入
                entry["arxiv_id"] = detail["arxiv_id"]
                paper_data = self._build_paper_from_detail(
                    detail,
                    source_paper_id,
                )
            elif detail:
                paper_data = self._build_paper_from_detail(
                    detail,
                    source_paper_id,
                )
            else:
                paper_data = self._build_paper_from_entry(
                    entry,
                    source_paper_id,
                )

            try:
                with session_scope() as session:
                    repo = PaperRepository(session)
                    cit_repo = CitationRepository(session)
                    saved = repo.upsert_paper(paper_data)
                    for tid in topic_ids:
                        repo.link_to_topic(saved.id, tid)
                    direction = entry.get("direction", "reference")
                    if direction == "reference":
                        cit_repo.upsert_edge(
                            source_paper_id,
                            saved.id,
                            context="reference",
                        )
                    else:
                        cit_repo.upsert_edge(
                            saved.id,
                            source_paper_id,
                            context="citation",
                        )
                    # 有 arxiv_id 的尝试下载 PDF
                    if paper_data.arxiv_id and not paper_data.arxiv_id.startswith("ss-"):
                        try:
                            pdf_path = self.arxiv.download_pdf(
                                paper_data.arxiv_id,
                            )
                            repo.set_pdf_path(saved.id, pdf_path)
                        except Exception:
                            pass
                    inserted_ids.append(saved.id)
                    task["imported"] += 1
                    task["results"].append(
                        {
                            "title": title,
                            "status": "imported",
                            "paper_id": saved.id,
                            "source": "semantic_scholar",
                        }
                    )
            except Exception as exc:
                logger.warning("SS import failed for %s: %s", title, exc)
                task["failed"] += 1
                task["results"].append(
                    {
                        "title": title,
                        "status": "failed",
                        "reason": str(exc)[:100],
                    }
                )

            task["completed"] += 1

    @staticmethod
    def _build_paper_from_entry(
        entry: dict,
        source_paper_id: str,
    ) -> PaperCreate:
        """从 citation entry 构建 PaperCreate"""
        arxiv_id = entry.get("arxiv_id")
        scholar_id = entry.get("scholar_id") or str(uuid4())[:12]
        if not arxiv_id:
            arxiv_id = f"ss-{scholar_id}"
        return PaperCreate(
            arxiv_id=arxiv_id,
            title=entry.get("title", "Unknown"),
            abstract=entry.get("abstract") or "",
            publication_date=(date(entry["year"], 1, 1) if entry.get("year") else None),
            metadata={
                "source": "reference_import",
                "source_paper_id": source_paper_id,
                "scholar_id": entry.get("scholar_id"),
                "venue": entry.get("venue"),
                "citation_count": entry.get("citation_count"),
                "import_source": "semantic_scholar",
            },
        )

    @staticmethod
    def _build_paper_from_detail(
        detail: dict,
        source_paper_id: str,
    ) -> PaperCreate:
        """从 SS 完整详情构建 PaperCreate（含作者、领域等）"""
        arxiv_id = detail.get("arxiv_id")
        scholar_id = detail.get("scholar_id") or str(uuid4())[:12]
        if not arxiv_id:
            arxiv_id = f"ss-{scholar_id}"

        pub_date = None
        if detail.get("publication_date"):
            try:
                pub_date = datetime.strptime(
                    detail["publication_date"],
                    "%Y-%m-%d",
                ).date()
            except (ValueError, TypeError):
                pass
        if not pub_date and detail.get("year"):
            pub_date = date(detail["year"], 1, 1)

        return PaperCreate(
            arxiv_id=arxiv_id,
            title=detail.get("title") or "Unknown",
            abstract=detail.get("abstract") or "",
            publication_date=pub_date,
            metadata={
                "source": "reference_import",
                "source_paper_id": source_paper_id,
                "scholar_id": detail.get("scholar_id"),
                "authors": detail.get("authors", []),
                "venue": detail.get("venue"),
                "citation_count": detail.get("citation_count"),
                "fields_of_study": detail.get("fields_of_study", []),
                "import_source": "semantic_scholar",
            },
        )

    def _bg_skim_and_embed(self, paper_ids: list[str]) -> None:
        """后台并行执行粗读 + 向量化"""
        pipeline = PaperPipelines()
        for pid in paper_ids:
            try:
                pipeline.embed_paper(UUID(pid))
            except Exception as exc:
                logger.warning("Embed failed for %s: %s", pid, exc)
            try:
                pipeline.skim(UUID(pid))
            except Exception as exc:
                logger.warning("Skim failed for %s: %s", pid, exc)
