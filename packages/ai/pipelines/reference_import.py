"""
参考文献一键导入引擎 - 将引用详情中的外部论文批量导入到论文库
@author Color2333
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from datetime import date, datetime
from uuid import UUID, uuid4

from packages.config import get_settings
from packages.domain.enums import ActionType
from packages.domain.schemas import PaperCreate
from packages.domain.task_tracker import global_tracker
from packages.integrations.arxiv_client import ArxivClient
from packages.integrations.llm_client import LLMClient
from packages.integrations.semantic_scholar_client import SemanticScholarClient
from packages.storage.db import session_scope
from packages.storage.repositories import (
    ActionRepository,
    CitationRepository,
    PaperRepository,
)

logger = logging.getLogger(__name__)


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

        def _run_import_with_progress(progress_callback=None):
            return self._run_import(
                source_paper_id=source_paper_id,
                source_paper_title=source_paper_title,
                entries=entries,
                topic_ids=topic_ids or [],
                progress_callback=progress_callback,
            )

        return global_tracker.submit(
            task_type="reference_import",
            title=f"参考文献导入：{source_paper_title[:60]}",
            fn=_run_import_with_progress,
            total=len(entries),
            category="collection",
        )

    def _run_import(
        self,
        *,
        source_paper_id: str,
        source_paper_title: str,
        entries: list[dict],
        topic_ids: list[str],
        progress_callback=None,
    ) -> dict:
        """执行导入任务，返回导入结果统计"""
        inserted_ids: list[str] = []
        skipped_count = 0
        imported_count = 0
        failed_count = 0
        results: list[dict] = []

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

            skipped_count = len(skip_entries)
            for e in skip_entries:
                results.append(
                    {
                        "title": e.get("title", ""),
                        "status": "skipped",
                        "reason": "已在库中",
                    }
                )

            # 3) 批量通过 arXiv API 拉取有 arxiv_id 的论文
            if arxiv_entries:
                self._import_arxiv_batch(
                    arxiv_entries,
                    source_paper_id,
                    topic_ids,
                    inserted_ids,
                    existing_norms,
                    results,
                    progress_callback,
                )

            # 4) 无 arxiv_id 的论文用 SS 元数据导入
            if ss_only_entries:
                self._import_ss_batch(
                    ss_only_entries,
                    source_paper_id,
                    topic_ids,
                    inserted_ids,
                    results,
                    progress_callback,
                )

            # 5) 记录 CollectionAction
            if inserted_ids:
                with session_scope() as session:
                    action_repo = ActionRepository(session)
                    action_repo.create_action(
                        action_type=ActionType.reference_import,
                        title=f"参考文献导入：{source_paper_title[:60]}",
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

            return {
                "status": "completed",
                "total": len(entries),
                "imported": imported_count,
                "skipped": skipped_count,
                "failed": failed_count,
                "results": results,
            }

        except Exception as exc:
            logger.exception("Reference import failed: %s", exc)
            return {
                "status": "failed",
                "error": str(exc),
                "results": results,
            }

    def _import_arxiv_batch(
        self,
        entries: list[dict],
        source_paper_id: str,
        topic_ids: list[str],
        inserted_ids: list[str],
        existing_norms: set[str],
        results: list[dict],
        progress_callback=None,
    ) -> None:
        """批量从 arXiv 拉取完整论文数据"""
        arxiv_ids = [e["arxiv_id"] for e in entries]
        imported_count = len(inserted_ids)

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
                    imported_count += 1
                    results.append(
                        {
                            "title": title,
                            "status": "imported",
                            "paper_id": saved.id,
                            "source": "arxiv",
                        }
                    )
            except Exception as exc:
                logger.warning("Import failed for %s: %s", title, exc)
                results.append(
                    {
                        "title": title,
                        "status": "failed",
                        "reason": str(exc)[:100],
                    }
                )

            # 更新进度
            if progress_callback:
                progress_callback(f"正在导入：{title[:50]}", imported_count, len(entries))

    def _import_ss_batch(
        self,
        entries: list[dict],
        source_paper_id: str,
        topic_ids: list[str],
        inserted_ids: list[str],
        results: list[dict],
        progress_callback=None,
    ) -> None:
        """用 Semantic Scholar 元数据导入没有 arXiv ID 的论文"""
        imported_count = len(inserted_ids)
        for entry in entries:
            title = entry.get("title", "Unknown")
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
                    imported_count += 1
                    results.append(
                        {
                            "title": title,
                            "status": "imported",
                            "paper_id": saved.id,
                            "source": "semantic_scholar",
                        }
                    )
            except Exception as exc:
                logger.warning("SS import failed for %s: %s", title, exc)
                results.append(
                    {
                        "title": title,
                        "status": "failed",
                        "reason": str(exc)[:100],
                    }
                )

            # 更新进度
            if progress_callback:
                progress_callback(f"正在导入：{title[:50]}", imported_count, len(entries))

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
            with contextlib.suppress(ValueError, TypeError):
                pub_date = datetime.strptime(
                    detail["publication_date"],
                    "%Y-%m-%d",
                ).date()
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
        from packages.ai.pipelines.paper_pipelines import PaperPipelines

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
