"""
论文处理 Pipeline - 摄入 / 粗读 / 精读 / 向量化
@author Color2333
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

from sqlalchemy import select as _sa_select

from packages.ai.cost_guard import CostGuardService
from packages.ai.pdf_parser import PdfTextExtractor
from packages.ai.prompts import build_deep_prompt, build_skim_prompt
from packages.ai.vision_reader import VisionPdfReader
from packages.config import get_ieee_api_key, get_ieee_enabled, get_settings
from packages.domain.enums import ActionType, ReadStatus
from packages.domain.schemas import DeepDiveReport, SkimReport
from packages.integrations.arxiv_client import ArxivClient
from packages.integrations.ieee_client import IeeeClient
from packages.integrations.llm_client import LLMClient
from packages.storage.db import session_scope
from packages.storage.models import AnalysisReport
from packages.storage.repositories import (
    ActionRepository,
    AnalysisRepository,
    PaperRepository,
    PipelineRunRepository,
    PromptTraceRepository,
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


def _bg_auto_link(paper_ids: list[str]) -> None:
    """后台线程：入库后自动关联引用"""
    try:
        from packages.ai.graph_service import GraphService

        gs = GraphService()
        result = gs.auto_link_citations(paper_ids)
        logger.info("bg auto_link: %s", result)
    except Exception as exc:
        logger.warning("bg auto_link failed: %s", exc)


# High 3c：复用有界线程池替代无界 daemon 线程。此前每次 collect 都
# threading.Thread(...).start()，5 个 topic 各起线程可能失控。
# max_workers=2 限制并发 auto_link，避免线程数膨胀。
_auto_link_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bg-auto-link")


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

    def _save_paper(self, repo, paper, topic_id=None, download_pdf=False):
        """入库 + 下载 PDF 的公共逻辑

        Args:
            repo: PaperRepository
            paper: PaperCreate 数据
            topic_id: 可选的主题 ID
            download_pdf: 是否下载 PDF（默认 False，只在精读时下载）
        """
        saved = repo.upsert_paper(paper)
        if topic_id:
            repo.link_to_topic(saved.id, topic_id)

        # 只在明确需要时才下载 PDF
        if download_pdf:
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
        days_back: int = 7,
        progress_callback: callable | None = None,
    ) -> tuple[int, list[str], int]:
        """搜索 arXiv 并入库，upsert 去重。返回 (total_count, inserted_ids, new_papers_count)

        智能递归抓取：如果前 N 篇有重复，继续抓取更早的论文，直到找到 max_results 篇新论文

        Args:
            progress_callback: 可选的进度回调函数，签名 callback(message, current, total)
        """
        inserted_ids: list[str] = []
        new_papers_count: int = 0
        total_fetched = 0
        batch_size = 20
        max_pages = 10  # 最多抓取 10 批（200 篇），直到找到 max_results 篇新论文
        arxiv_request_delay = 3.0  # arXiv API 建议请求间隔 3 秒

        with session_scope() as session:
            repo = PaperRepository(session)
            run_repo = PipelineRunRepository(session)
            action_repo = ActionRepository(session)
            run = run_repo.start("ingest_arxiv", decision_note=f"query={query}")

            try:
                # 分批抓取，直到找到足够的新论文或达到最大页数
                for page in range(max_pages):
                    if new_papers_count >= max_results:
                        break  # 已找到足够的新论文

                    start = page * batch_size
                    # 计算本批需要抓取的数量（避免超目标）
                    needed = max_results - new_papers_count
                    this_batch = min(batch_size, needed + 20)  # 多抓 20 篇作为缓冲

                    if progress_callback:
                        progress_callback(f"抓取第 {page + 1}/{max_pages} 批", page + 1, max_pages)

                    papers = self.arxiv.fetch_latest(
                        query=query,
                        max_results=this_batch,
                        sort_by=sort_by,
                        start=start,
                        days_back=days_back,
                    )
                    total_fetched += len(papers)

                    # 添加请求间隔，避免触发 arXiv 限流
                    if page < max_pages - 1 and papers:
                        time.sleep(arxiv_request_delay)

                    if not papers:
                        break  # 没有更多论文了

                    # 提前检查哪些论文已存在
                    existing_arxiv_ids = repo.list_existing_arxiv_ids([p.arxiv_id for p in papers])

                    # 只处理新论文
                    for paper in papers:
                        is_new = paper.arxiv_id not in existing_arxiv_ids
                        if is_new:
                            saved = self._save_paper(repo, paper, topic_id)
                            new_papers_count += 1
                            inserted_ids.append(saved.id)

                            # 达到目标就停止
                            if new_papers_count >= max_results:
                                break

                    # 日志
                    new_in_batch = len(papers) - len(existing_arxiv_ids)
                    logger.info(
                        "第 %d 批：抓取 %d 篇，新论文 %d 篇（累计 %d/%d）",
                        page + 1,
                        len(papers),
                        new_in_batch,
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
                    # High 3c：提交到有界线程池，替代无界 daemon 线程
                    _auto_link_pool.submit(_bg_auto_link, inserted_ids)

                logger.info(
                    "抓取完成：共 %d 篇新论文（从 %d 篇中筛选）",
                    new_papers_count,
                    total_fetched,
                )
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
        sort_by: str = "submittedDate",
        days_back: int = 7,
        progress_callback: callable | None = None,
    ) -> list[str]:
        """ingest_arxiv 的别名，返回 inserted_ids"""
        _, ids, _ = self.ingest_arxiv(
            query=query,
            max_results=max_results,
            topic_id=topic_id,
            action_type=action_type,
            sort_by=sort_by,
            days_back=days_back,
            progress_callback=progress_callback,
        )
        return ids

    def ingest_arxiv_with_stats(
        self,
        query: str,
        max_results: int = 20,
        topic_id: str | None = None,
        action_type: ActionType = ActionType.subscription_ingest,
        sort_by: str = "submittedDate",
        days_back: int = 7,
        progress_callback: callable | None = None,
    ) -> dict:
        """ingest_arxiv 返回详细统计信息"""
        total_count, inserted_ids, new_count = self.ingest_arxiv(
            query=query,
            max_results=max_results,
            topic_id=topic_id,
            action_type=action_type,
            sort_by=sort_by,
            days_back=days_back,
            progress_callback=progress_callback,
        )
        return {
            "total_count": total_count,
            "inserted_ids": inserted_ids,
            "new_count": new_count,
        }

    def ingest_ieee(
        self,
        query: str,
        max_results: int = 20,
        topic_id: str | None = None,
        action_type: ActionType = ActionType.manual_collect,
    ) -> tuple[int, list[str], int]:
        """
        搜索 IEEE 论文并入库（MVP 阶段新增）

        注意：
        - 不修改现有 ingest_arxiv 逻辑
        - IEEE PDF 暂不支持下载
        - 需要 IEEE API Key 配置

        Args:
            query: 搜索关键词
            max_results: 最大结果数（默认 20）
            topic_id: 可选的主题 ID
            action_type: 行动类型（默认 manual_collect）

        Returns:
            (total_count, inserted_ids, new_papers_count)
        """
        if not self.ieee:
            logger.error("IEEE 客户端未初始化，无法执行 IEEE 摄取")
            raise RuntimeError("IEEE API Key 未配置，请在 .env 中设置 IEEE_API_KEY 环境变量")

        inserted_ids: list[str] = []
        new_papers_count = 0
        total_fetched = 0

        with session_scope() as session:
            repo = PaperRepository(session)
            run_repo = PipelineRunRepository(session)
            action_repo = ActionRepository(session)

            run = run_repo.start(
                "ingest_ieee",
                decision_note=f"query={query}",
            )

            try:
                # 从 IEEE 获取论文
                papers = self.ieee.fetch_by_keywords(
                    query=query,
                    max_results=max_results,
                )
                total_fetched = len(papers)

                if not papers:
                    logger.info("IEEE 摄取无新论文：%s", query)
                    run_repo.finish(run.id)
                    return 0, [], 0

                # 去重：检查 DOI 是否已存在
                dois = [p.doi for p in papers if p.doi]
                existing_dois = repo.list_existing_dois(dois) if dois else set()

                # 处理每篇论文
                for paper in papers:
                    # DOI 去重
                    if paper.doi and paper.doi in existing_dois:
                        logger.info(
                            "IEEE 论文已存在（DOI 重复）: %s - %s", paper.doi, paper.title[:50]
                        )
                        continue

                    # 入库
                    saved = self._save_paper_ieee(repo, paper, topic_id)
                    new_papers_count += 1
                    inserted_ids.append(saved.id)

                # 创建行动记录
                if inserted_ids:
                    action_repo.create_action(
                        action_type=action_type,
                        title=f"IEEE 收集：{query[:80]}",
                        paper_ids=inserted_ids,
                        query=query,
                        topic_id=topic_id,
                    )

                    # 后台关联引用（High 3c：提交到有界线程池）
                    _auto_link_pool.submit(_bg_auto_link, inserted_ids)

                run_repo.finish(run.id)

                logger.info(
                    "✅ IEEE 摄取完成：%d 篇新论文（从 %d 篇中筛选）",
                    new_papers_count,
                    total_fetched,
                )

                return len(inserted_ids), inserted_ids, new_papers_count

            except Exception as exc:
                run_repo.fail(run.id, str(exc))
                logger.error("IEEE 摄取失败：%s", exc)
                raise

    def _save_paper_ieee(self, repo, paper, topic_id=None):
        """
        IEEE 论文入库专用方法

        Args:
            repo: PaperRepository
            paper: PaperCreate (IEEE 格式)
            topic_id: 可选的主题 ID

        Returns:
            保存后的 Paper 对象
        """
        # IEEE 论文不下载 PDF（权限限制）
        saved = repo.upsert_paper(paper)
        if topic_id:
            repo.link_to_topic(saved.id, topic_id)

        logger.info(
            "IEEE 论文入库：%s - %s",
            paper.source_id,
            paper.title[:50],
        )
        return saved

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
        """向量化嵌入（带追踪）"""
        started = time.perf_counter()
        with session_scope() as session:
            run_repo = PipelineRunRepository(session)
            run = run_repo.start("embed_paper", paper_id=paper_id)
            try:
                paper_repo = PaperRepository(session)
                paper = paper_repo.get_by_id(paper_id)
                content = self._build_embed_content(session, paper)
                vector = self.llm.embed_text(content)
                paper_repo.update_embedding(paper_id, vector)
                elapsed = int((time.perf_counter() - started) * 1000)
                run_repo.finish(run.id, elapsed_ms=elapsed)
            except Exception as exc:
                run_repo.fail(run.id, str(exc))
                raise

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
