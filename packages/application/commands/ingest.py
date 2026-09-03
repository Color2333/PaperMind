"""论文导入命令（B6；设计② ImportPaper 的 agent 同步语义）

选定论文入库 → 自动建/关联主题 → 后台异步下载 PDF → 论文间/论文内双层并行
embed+skim。进度经 progress(message, current, total) 回调上报（协议层桥接为
ToolProgress）；tracker 为过渡执行追踪（C3 收敛为 durable Job）。
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from collections.abc import Callable

    from packages.domain.schemas import PaperCreate

logger = logging.getLogger(__name__)

# High 3d：PDF 下载后台线程池（有界，避免逐篇同步 90s 阻塞 ingest 主流程）
_pdf_download_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pdf-dl")


def search_arxiv(
    *, query: str, max_results: int = 20, days_back: int = 0, sort_by: str = "relevance"
) -> list[dict]:
    """搜索 arXiv 候选（不入库）；返回候选 canonical 列表"""
    from packages.integrations.arxiv_client import ArxivClient

    papers = ArxivClient().fetch_latest(
        query=query, max_results=max_results, sort_by=sort_by, days_back=days_back
    )
    return [
        {
            # REVIEW P2：候选的序号字段是既有协议的一部分（旧 CLI/UI 按序号展示），保留
            "index": i,
            "arxiv_id": p.arxiv_id,
            "title": p.title,
            "abstract": (p.abstract or "")[:300],
            "publication_date": str(p.publication_date) if p.publication_date else None,
            "categories": (p.metadata or {}).get("categories", []),
            "authors": (p.metadata or {}).get("authors", [])[:5],
        }
        for i, p in enumerate(papers, 1)
    ]


def import_from_arxiv_query(
    *,
    query: str,
    max_results: int = 20,
    topic_id: str | None = None,
    action_type=None,
    sort_by: str = "submittedDate",
    days_back: int = 7,
    progress: Callable[[str, int, int], None] | None = None,
) -> tuple[int, list[str], int]:
    """按关键词从 arXiv 搜索并入库（HTTP /ingest/arxiv 的同步命令）"""
    from packages.ai.pipelines import PaperPipelines
    from packages.domain.enums import ActionType

    if action_type is None:
        # 与 pipelines.ingest_arxiv 的默认一致；显式传 None 会覆盖默认并违反 NOT NULL
        action_type = ActionType.manual_collect

    return PaperPipelines().ingest_arxiv(
        query=query,
        max_results=max_results,
        topic_id=topic_id,
        action_type=action_type,
        sort_by=sort_by,
        days_back=days_back,
        progress_callback=progress,
    )


def import_ieee(
    *, query: str, max_results: int = 20, topic_id: str | None = None
) -> tuple[int, list[str], int]:
    """IEEE 渠道入库（需要 IEEE_API_KEY；未配置抛 RuntimeError）"""
    from packages.ai.pipelines import PaperPipelines
    from packages.domain.enums import ActionType

    return PaperPipelines().ingest_ieee(
        query=query,
        max_results=max_results,
        topic_id=topic_id,
        action_type=ActionType.manual_collect,
    )


def describe_ingested_papers(inserted_ids: list[str], *, limit: int = 50) -> list[dict]:
    """入库后返回论文基本信息（/ingest/arxiv 响应形状）"""
    from packages.storage.db import session_scope
    from packages.storage.repositories import PaperRepository

    papers_info: list[dict] = []
    with session_scope() as session:
        repo = PaperRepository(session)
        for pid in inserted_ids[:limit]:
            try:
                p = repo.get_by_id(UUID(pid))
                papers_info.append(
                    {
                        "id": p.id,
                        "title": p.title,
                        "arxiv_id": p.arxiv_id,
                        "publication_date": p.publication_date.isoformat()
                        if p.publication_date
                        else None,
                    }
                )
            except Exception:
                pass
    return papers_info


def _download_pdf_async(arxiv_client, arxiv_id: str, paper_id: str) -> None:
    """后台异步下载 PDF 并回填路径；失败记录到论文 metadata（deep_dive 可见）。

    独立线程 + 独立 session（与 ingest 主事务隔离）。
    """
    from packages.storage.db import SessionLocal
    from packages.storage.repositories import PaperRepository as _PR

    def _do_download():
        dl_session = SessionLocal()
        try:
            dl_repo = _PR(dl_session)
            try:
                pdf_path = arxiv_client.download_pdf(arxiv_id)
                dl_repo.set_pdf_path(paper_id, pdf_path)
                dl_session.commit()
                logger.info("ingest: PDF 下载完成 %s", arxiv_id)
            except Exception as exc:
                dl_session.rollback()
                try:
                    paper = dl_repo.get_by_id(paper_id)
                    if paper is not None:
                        meta = dict(paper.metadata_json or {})
                        meta["pdf_download_failed"] = str(exc)[:200]
                        paper.metadata_json = meta
                        dl_session.commit()
                except Exception:
                    dl_session.rollback()
                logger.warning("ingest: PDF 下载失败 %s: %s", arxiv_id, exc)
        finally:
            dl_session.close()

    _pdf_download_pool.submit(_do_download)


def import_selected_papers(
    *,
    query: str,
    arxiv_ids: list[str],
    progress: Callable[[str, int, int], None] | None = None,
) -> dict:
    """将用户选定的论文入库 → 主题关联 → 异步 PDF → 并行 embed+skim"""

    def _report(msg: str, cur: int, tot: int) -> None:
        if progress:
            with suppress(Exception):
                progress(msg, cur, tot)

    from packages.ai.pipelines import PaperPipelines
    from packages.domain.enums import ActionType
    from packages.integrations.arxiv_client import ArxivClient
    from packages.storage.db import session_scope
    from packages.storage.repositories import (
        ActionRepository,
        PaperRepository,
        PipelineRunRepository,
        TopicRepository,
    )

    pipelines = PaperPipelines()
    topic_name = query.strip()
    selected_set = set(arxiv_ids)

    # 查找或创建 Topic
    topic_id: str | None = None
    is_new_topic = False
    try:
        with session_scope() as session:
            topic_repo = TopicRepository(session)
            topic = topic_repo.get_by_name(topic_name)
            if not topic:
                topic = topic_repo.upsert_topic(name=topic_name, query=topic_name, enabled=False)
                is_new_topic = True
            topic_id = topic.id
    except Exception as exc:
        logger.warning("Auto-create topic '%s' failed: %s", topic_name, exc)

    arxiv_client = ArxivClient()
    inserted_ids: list[str] = []

    _report(f"正在下载 {len(selected_set)} 篇选中论文...", 0, len(selected_set))

    # 分批搜索获取论文元数据；缺失的按 ID 批量补拉（fetch_by_ids 走 id_list 参数）
    all_papers = arxiv_client.fetch_latest(query=query, max_results=50)
    selected_papers: list[PaperCreate] = [p for p in all_papers if p.arxiv_id in selected_set]
    found_ids = {p.arxiv_id for p in selected_papers}
    missing_ids = selected_set - found_ids
    if missing_ids:
        try:
            selected_papers.extend(arxiv_client.fetch_by_ids(list(missing_ids)))
        except Exception:
            logger.warning("Failed to fetch arxiv papers by ids: %s", list(missing_ids)[:5])

    failed_papers: list[dict] = []
    ingested_papers: list[dict] = []

    with session_scope() as session:
        repo = PaperRepository(session)
        action_repo = ActionRepository(session)
        run_repo = PipelineRunRepository(session)
        note = f"selected {len(arxiv_ids)} from query={query}"
        run = run_repo.start("ingest_arxiv", decision_note=note)
        try:
            for idx, paper in enumerate(selected_papers, 1):
                try:
                    saved = repo.upsert_paper(paper)
                    if topic_id:
                        repo.link_to_topic(saved.id, topic_id)
                    inserted_ids.append(saved.id)
                    _download_pdf_async(arxiv_client, paper.arxiv_id, saved.id)
                    ingested_papers.append(
                        {
                            "arxiv_id": paper.arxiv_id,
                            "title": (paper.title or "")[:80],
                            "status": "ok",
                        }
                    )
                except Exception as exc:
                    logger.warning("Ingest paper %s failed: %s", paper.arxiv_id, exc)
                    failed_papers.append(
                        {
                            "arxiv_id": paper.arxiv_id,
                            "title": (paper.title or "")[:80],
                            "error": str(exc)[:120],
                            "status": "failed",
                        }
                    )
                msg = f"入库 {idx}/{len(selected_papers)}: {(paper.title or '')[:40]}"
                _report(msg, idx, len(selected_papers))

            if inserted_ids:
                action_repo.create_action(
                    action_type=ActionType.agent_collect,
                    title=f"Agent 收集: {query[:80]}",
                    paper_ids=inserted_ids,
                    query=query,
                    topic_id=topic_id,
                )
            run_repo.finish(run.id)
        except Exception as exc:
            run_repo.fail(run.id, str(exc))
            raise

    if not inserted_ids:
        # REVIEW P1-2：完全失败必须有稳定的失败语义（协议层据此返回 success=False）
        return {
            "status": "failed",
            "total": 0,
            "embedded": 0,
            "skimmed": 0,
            "query": query,
            "topic": topic_name,
            "paper_ids": [],
            "suggest_subscribe": False,
            "ingested": ingested_papers,
            "failed": failed_papers,
            "note": (
                f"{len(failed_papers)} 篇写库失败"
                if failed_papers
                else "选中的 ID 未从 arXiv 返回（元数据获取失败或 ID 无效）"
            ),
        }

    total = len(inserted_ids)
    msg = f"入库 {total} 篇，开始向量化和粗读..."
    _report(msg, 0, total)

    # 向量化 + 粗读（论文间 3 并发；每篇内 embed ∥ skim 双并行 → 最多 6 并发）
    PAPER_CONCURRENCY = 3

    paper_titles: dict[str, str] = {}
    with session_scope() as sess:
        for pid_str in inserted_ids:
            try:
                p = PaperRepository(sess).get_by_id(UUID(pid_str))
                paper_titles[pid_str] = (p.title or "")[:40]
            except Exception:
                paper_titles[pid_str] = pid_str[:8]

    def _process_one(pid_str: str) -> tuple[bool, bool]:
        pid = UUID(pid_str)
        e_ok, s_ok = False, False
        with ThreadPoolExecutor(max_workers=2) as inner:
            fe = inner.submit(pipelines.embed_paper, pid)
            fs = inner.submit(pipelines.skim, pid)
            for fut in as_completed([fe, fs]):
                try:
                    fut.result()
                    if fut is fe:
                        e_ok = True
                    else:
                        s_ok = True
                except Exception as exc:
                    label = "embed" if fut is fe else "skim"
                    logger.warning("%s %s failed: %s", label, pid_str[:8], exc)
        return e_ok, s_ok

    embed_ok, skim_ok, done = 0, 0, 0
    with ThreadPoolExecutor(max_workers=PAPER_CONCURRENCY) as pool:
        future_map = {pool.submit(_process_one, pid_str): pid_str for pid_str in inserted_ids}
        for fut in as_completed(future_map):
            pid_str = future_map[fut]
            done += 1
            title = paper_titles.get(pid_str, pid_str[:8])
            try:
                e_ok_i, s_ok_i = fut.result()
                embed_ok += int(e_ok_i)
                skim_ok += int(s_ok_i)
            except Exception as exc:
                logger.warning("paper %s failed: %s", pid_str[:8], exc)
            msg = f"完成 {done}/{total}: {title}"
            _report(msg, done, total)

    return {
        "status": "partial" if failed_papers else "succeeded",
        "total": total,
        "embedded": embed_ok,
        "skimmed": skim_ok,
        "query": query,
        "topic": topic_name,
        "paper_ids": inserted_ids[:10],
        "suggest_subscribe": is_new_topic,
        "ingested": ingested_papers,
        "failed": failed_papers,
    }
