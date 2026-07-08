"""arXiv 搜索与入库。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from packages.ai.pipelines import PaperPipelines
from packages.ai.tools.types import ToolProgress, ToolResult
from packages.storage.db import session_scope
from packages.storage.repositories import PaperRepository, TopicRepository

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)


def _search_arxiv(
    query: str,
    max_results: int = 20,
    days_back: int = 0,
    sort_by: str = "relevance",
) -> ToolResult:
    """搜索 arXiv，返回候选论文列表（不入库）

    days_back=0（默认）不限日期，适合按关键词检索经典/全时间段论文。
    想要最新增量时传 days_back=7/30。
    """
    from packages.integrations.arxiv_client import ArxivClient

    try:
        papers = ArxivClient().fetch_latest(
            query=query,
            max_results=max_results,
            sort_by=sort_by,
            days_back=days_back,
        )
    except Exception as exc:
        logger.exception("ArXiv search failed: %s", exc)
        return ToolResult(success=False, summary=f"ArXiv 搜索失败: {exc!s}")

    if not papers:
        return ToolResult(
            success=True,
            data={"candidates": [], "count": 0, "query": query},
            summary="未找到相关论文",
        )

    candidates = []
    for i, p in enumerate(papers, 1):
        candidates.append(
            {
                "index": i,
                "arxiv_id": p.arxiv_id,
                "title": p.title,
                "abstract": (p.abstract or "")[:300],
                "publication_date": str(p.publication_date) if p.publication_date else None,
                "categories": (p.metadata_json or {}).get("categories", []),
                "authors": (p.metadata_json or {}).get("authors", [])[:5],
            }
        )

    return ToolResult(
        success=True,
        data={"candidates": candidates, "count": len(candidates), "query": query},
        summary=f"从 arXiv 搜索到 {len(candidates)} 篇候选论文",
    )


def _ingest_arxiv(
    query: str,
    arxiv_ids: list[str] | None = None,
) -> Iterator[ToolProgress | ToolResult]:
    """将用户选定的论文入库 → 自动分配主题 → 自动向量化 → 自动粗读"""
    from packages.domain.task_tracker import global_tracker
    from packages.integrations.arxiv_client import ArxivClient

    pipelines = PaperPipelines()
    topic_name = query.strip()
    _task_id = f"ingest_{uuid4().hex[:8]}"

    if not arxiv_ids:
        yield ToolResult(
            success=False,
            summary="请先用 search_arxiv 搜索，再提供要入库的 arxiv_ids 列表",
        )
        return

    yield ToolProgress(message="正在准备入库...", current=0, total=0)

    # 查找或创建 Topic
    topic_id: str | None = None
    is_new_topic = False
    try:
        with session_scope() as session:
            topic_repo = TopicRepository(session)
            topic = topic_repo.get_by_name(topic_name)
            if not topic:
                topic = topic_repo.upsert_topic(
                    name=topic_name,
                    query=topic_name,
                    enabled=False,
                )
                is_new_topic = True
            topic_id = topic.id
    except Exception as exc:
        logger.warning("Auto-create topic '%s' failed: %s", topic_name, exc)

    # 从 arXiv 拉取选中论文的完整信息并入库
    arxiv_client = ArxivClient()
    selected_set = set(arxiv_ids)
    inserted_ids: list[str] = []

    global_tracker.start(
        _task_id,
        "ingest",
        f"入库论文: {topic_name[:30]}",
        total=len(selected_set),
    )
    yield ToolProgress(
        message=f"正在下载 {len(selected_set)} 篇选中论文...",
        current=0,
        total=len(selected_set),
    )

    # 分批搜索获取论文元数据
    all_papers = arxiv_client.fetch_latest(query=query, max_results=50)
    selected_papers = [p for p in all_papers if p.arxiv_id in selected_set]

    # 补充搜索结果中没有的（可能 ID 不在前50条中），逐个按 ID 拉取
    found_ids = {p.arxiv_id for p in selected_papers}
    missing_ids = selected_set - found_ids
    for mid in missing_ids:
        try:
            extra = arxiv_client.fetch_latest(query=f"id:{mid}", max_results=1)
            selected_papers.extend(extra)
        except Exception:
            logger.warning("Failed to fetch arxiv paper %s", mid)

    failed_papers: list[dict] = []
    ingested_papers: list[dict] = []

    with session_scope() as session:
        repo = PaperRepository(session)
        from packages.domain.enums import ActionType
        from packages.storage.repositories import ActionRepository, PipelineRunRepository

        run_repo = PipelineRunRepository(session)
        action_repo = ActionRepository(session)
        note = f"selected {len(arxiv_ids)} from query={query}"
        run = run_repo.start("ingest_arxiv", decision_note=note)
        try:
            for idx, paper in enumerate(selected_papers, 1):
                try:
                    saved = repo.upsert_paper(paper)
                    if topic_id:
                        repo.link_to_topic(saved.id, topic_id)
                    inserted_ids.append(saved.id)
                    try:
                        pdf_path = arxiv_client.download_pdf(paper.arxiv_id)
                        repo.set_pdf_path(saved.id, pdf_path)
                    except Exception:
                        pass
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
                global_tracker.update(
                    _task_id,
                    current=idx,
                    message=f"入库 {idx}/{len(selected_papers)}: {(paper.title or '')[:40]}",
                )
                yield ToolProgress(
                    message=f"入库 {idx}/{len(selected_papers)}: {(paper.title or '')[:40]}",
                    current=idx,
                    total=len(selected_papers),
                )

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
        global_tracker.finish(_task_id, success=False, error="未能入库任何论文")
        yield ToolResult(
            success=len(failed_papers) == 0,
            data={
                "ingested": 0,
                "query": query,
                "suggest_subscribe": False,
                "failed": failed_papers,
            },
            summary="未能入库任何论文"
            + (f"，{len(failed_papers)} 篇失败" if failed_papers else ""),
        )
        return

    total = len(inserted_ids)
    global_tracker.update(
        _task_id,
        current=0,
        total=total,
        message=f"入库 {total} 篇，开始向量化和粗读...",
    )
    yield ToolProgress(
        message=f"入库 {total} 篇，开始向量化和粗读...",
        current=0,
        total=total,
    )

    # 向量化 + 粗读（论文间 + 论文内双重并行）
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # 最多 3 篇论文同时处理，每篇 2 个 API 调用 → 最多 6 并发
    PAPER_CONCURRENCY = 3

    # 获取所有论文标题（在 session 内）
    paper_titles: dict[str, str] = {}
    with session_scope() as sess:
        for pid_str in inserted_ids:
            try:
                p = PaperRepository(sess).get_by_id(UUID(pid_str))
                paper_titles[pid_str] = (p.title or "")[:40]
            except Exception:
                paper_titles[pid_str] = pid_str[:8]

    def _process_one(pid_str: str) -> tuple[bool, bool]:
        """单篇论文：embed ∥ skim 并行"""
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
                    logger.warning(
                        "%s %s failed: %s",
                        label,
                        pid_str[:8],
                        exc,
                    )
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
            global_tracker.update(
                _task_id,
                current=done,
                message=f"嵌入+粗读 {done}/{total}: {title}",
            )
            yield ToolProgress(
                message=f"完成 {done}/{total}: {title}",
                current=done,
                total=total,
            )

    global_tracker.finish(_task_id, success=True)

    yield ToolResult(
        success=True,
        data={
            "total": total,
            "embedded": embed_ok,
            "skimmed": skim_ok,
            "query": query,
            "topic": topic_name,
            "paper_ids": inserted_ids[:10],
            "suggest_subscribe": is_new_topic,
            "ingested": ingested_papers,
            "failed": failed_papers,
        },
        summary=(
            f"入库 {total} 篇 → 主题「{topic_name}」，"
            f"向量化 {embed_ok}，粗读 {skim_ok}"
            + (f"，{len(failed_papers)} 篇失败已跳过" if failed_papers else "")
        ),
    )
