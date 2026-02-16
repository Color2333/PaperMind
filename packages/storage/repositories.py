"""
数据仓储层
@author Bamzc
"""
from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from packages.domain.enums import PipelineStatus, ReadStatus
from packages.domain.schemas import DeepDiveReport, PaperCreate, SkimReport
from packages.storage.models import (
    AnalysisReport,
    Citation,
    GeneratedContent,
    LLMProviderConfig,
    Paper,
    PaperTopic,
    PipelineRun,
    PromptTrace,
    SourceCheckpoint,
    TopicSubscription,
)


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦距离"""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 1.0
    return 1.0 - (dot / (na * nb))


class PaperRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_paper(self, data: PaperCreate) -> Paper:
        q = select(Paper).where(Paper.arxiv_id == data.arxiv_id)
        existing = self.session.execute(q).scalar_one_or_none()
        if existing:
            existing.title = data.title
            existing.abstract = data.abstract
            existing.publication_date = data.publication_date
            existing.metadata_json = data.metadata
            existing.updated_at = datetime.now(UTC)
            self.session.flush()
            return existing

        paper = Paper(
            arxiv_id=data.arxiv_id,
            title=data.title,
            abstract=data.abstract,
            publication_date=data.publication_date,
            metadata_json=data.metadata,
        )
        self.session.add(paper)
        self.session.flush()
        return paper

    def list_latest(self, limit: int = 20) -> list[Paper]:
        q: Select[tuple[Paper]] = (
            select(Paper).order_by(Paper.created_at.desc()).limit(limit)
        )
        return list(self.session.execute(q).scalars())

    def list_all(self, limit: int = 10000) -> list[Paper]:
        q: Select[tuple[Paper]] = (
            select(Paper).order_by(Paper.created_at.desc()).limit(limit)
        )
        return list(self.session.execute(q).scalars())

    def list_by_ids(self, paper_ids: list[str]) -> list[Paper]:
        if not paper_ids:
            return []
        q = select(Paper).where(Paper.id.in_(paper_ids))
        return list(self.session.execute(q).scalars())

    def list_by_read_status(
        self, status: ReadStatus, limit: int = 200
    ) -> list[Paper]:
        q = (
            select(Paper)
            .where(Paper.read_status == status)
            .order_by(Paper.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(q).scalars())

    def list_by_topic(
        self, topic_id: str, limit: int = 200
    ) -> list[Paper]:
        q = (
            select(Paper)
            .join(PaperTopic, Paper.id == PaperTopic.paper_id)
            .where(PaperTopic.topic_id == topic_id)
            .order_by(Paper.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(q).scalars())

    def get_by_id(self, paper_id: UUID) -> Paper:
        paper = self.session.get(Paper, str(paper_id))
        if paper is None:
            raise ValueError(f"paper {paper_id} not found")
        return paper

    def set_pdf_path(self, paper_id: UUID, pdf_path: str) -> None:
        paper = self.get_by_id(paper_id)
        paper.pdf_path = pdf_path
        paper.updated_at = datetime.now(UTC)

    def update_embedding(
        self, paper_id: UUID, embedding: list[float]
    ) -> None:
        paper = self.get_by_id(paper_id)
        paper.embedding = embedding
        paper.updated_at = datetime.now(UTC)

    def update_read_status(
        self, paper_id: UUID, status: ReadStatus
    ) -> None:
        paper = self.get_by_id(paper_id)
        upgrade = (
            paper.read_status == ReadStatus.unread
            and status in (ReadStatus.skimmed, ReadStatus.deep_read)
        ) or (
            paper.read_status == ReadStatus.skimmed
            and status == ReadStatus.deep_read
        )
        if upgrade:
            paper.read_status = status

    def similar_by_embedding(
        self,
        vector: list[float],
        exclude: UUID,
        limit: int = 5,
    ) -> list[Paper]:
        if not vector:
            return []
        q = (
            select(Paper)
            .where(Paper.id != str(exclude))
            .where(Paper.embedding.is_not(None))
        )
        candidates = list(self.session.execute(q).scalars())
        ranked = sorted(
            candidates,
            key=lambda p: _cosine_distance(vector, p.embedding or []),
        )
        return ranked[:limit]

    def full_text_candidates(
        self, query: str, limit: int = 8
    ) -> list[Paper]:
        """按关键词搜索论文（每个词独立匹配 title/abstract）"""
        tokens = [t for t in query.lower().split() if len(t) >= 2]
        if not tokens:
            return []
        # 每个关键词必须出现在 title 或 abstract 中
        conditions = []
        for token in tokens:
            conditions.append(
                func.lower(Paper.title).contains(token)
                | func.lower(Paper.abstract).contains(token)
            )
        q = select(Paper).where(*conditions).limit(limit)
        return list(self.session.execute(q).scalars())

    def semantic_candidates(
        self, query_vector: list[float], limit: int = 8
    ) -> list[Paper]:
        if not query_vector:
            return []
        q = select(Paper).where(Paper.embedding.is_not(None))
        candidates = list(self.session.execute(q).scalars())
        ranked = sorted(
            candidates,
            key=lambda p: _cosine_distance(
                query_vector, p.embedding or []
            ),
        )
        return ranked[:limit]

    def link_to_topic(self, paper_id: str, topic_id: str) -> None:
        q = select(PaperTopic).where(
            PaperTopic.paper_id == paper_id,
            PaperTopic.topic_id == topic_id,
        )
        found = self.session.execute(q).scalar_one_or_none()
        if found:
            return
        self.session.add(
            PaperTopic(paper_id=paper_id, topic_id=topic_id)
        )

    def get_topic_names_for_papers(
        self, paper_ids: list[str]
    ) -> dict[str, list[str]]:
        """批量查 paper → topic name 映射"""
        if not paper_ids:
            return {}
        q = (
            select(PaperTopic.paper_id, TopicSubscription.name)
            .join(
                TopicSubscription,
                PaperTopic.topic_id == TopicSubscription.id,
            )
            .where(PaperTopic.paper_id.in_(paper_ids))
        )
        rows = self.session.execute(q).all()
        result: dict[str, list[str]] = {}
        for pid, tname in rows:
            result.setdefault(pid, []).append(tname)
        return result


class AnalysisRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_skim(self, paper_id: UUID, skim: SkimReport) -> None:
        report = self._get_or_create(paper_id)
        innovations = "".join(
            [f"  - {x}\n" for x in skim.innovations]
        )
        report.summary_md = (
            f"- 一句话: {skim.one_liner}\n"
            f"- 创新点:\n{innovations}"
        )
        report.skim_score = skim.relevance_score
        report.key_insights = {"skim_innovations": skim.innovations}

    def upsert_deep_dive(
        self, paper_id: UUID, deep: DeepDiveReport
    ) -> None:
        report = self._get_or_create(paper_id)
        risks = "".join([f"- {x}\n" for x in deep.reviewer_risks])
        report.deep_dive_md = (
            f"## Method\n{deep.method_summary}\n\n"
            f"## Experiments\n{deep.experiments_summary}\n\n"
            f"## Ablation\n{deep.ablation_summary}\n\n"
            f"## Reviewer Risks\n{risks}"
        )
        report.key_insights = {
            **(report.key_insights or {}),
            "reviewer_risks": deep.reviewer_risks,
        }

    def _get_or_create(self, paper_id: UUID) -> AnalysisReport:
        pid = str(paper_id)
        q = select(AnalysisReport).where(
            AnalysisReport.paper_id == pid
        )
        found = self.session.execute(q).scalar_one_or_none()
        if found:
            return found
        report = AnalysisReport(paper_id=pid, key_insights={})
        self.session.add(report)
        self.session.flush()
        return report

    def summaries_for_papers(
        self, paper_ids: list[str]
    ) -> dict[str, str]:
        if not paper_ids:
            return {}
        q = select(AnalysisReport).where(
            AnalysisReport.paper_id.in_(paper_ids)
        )
        reports = list(self.session.execute(q).scalars())
        return {x.paper_id: x.summary_md or "" for x in reports}

    def contexts_for_papers(
        self, paper_ids: list[str]
    ) -> dict[str, str]:
        if not paper_ids:
            return {}
        q = select(AnalysisReport).where(
            AnalysisReport.paper_id.in_(paper_ids)
        )
        reports = list(self.session.execute(q).scalars())
        out: dict[str, str] = {}
        for x in reports:
            combined = []
            if x.summary_md:
                combined.append(x.summary_md)
            if x.deep_dive_md:
                combined.append(x.deep_dive_md[:2000])
            out[x.paper_id] = "\n\n".join(combined)
        return out


class PipelineRunRepository:
    def __init__(self, session: Session):
        self.session = session

    def start(
        self,
        pipeline_name: str,
        paper_id: UUID | None = None,
        decision_note: str | None = None,
    ) -> PipelineRun:
        run = PipelineRun(
            pipeline_name=pipeline_name,
            paper_id=str(paper_id) if paper_id else None,
            status=PipelineStatus.running,
            decision_note=decision_note,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def finish(
        self, run_id: UUID, elapsed_ms: int | None = None
    ) -> None:
        run = self.session.get(PipelineRun, str(run_id))
        if not run:
            return
        run.status = PipelineStatus.succeeded
        run.elapsed_ms = elapsed_ms

    def fail(self, run_id: UUID, error_message: str) -> None:
        run = self.session.get(PipelineRun, str(run_id))
        if not run:
            return
        run.status = PipelineStatus.failed
        run.retry_count += 1
        run.error_message = error_message

    def list_latest(self, limit: int = 30) -> list[PipelineRun]:
        q = (
            select(PipelineRun)
            .order_by(PipelineRun.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(q).scalars())


class PromptTraceRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        stage: str,
        provider: str,
        model: str,
        prompt_digest: str,
        paper_id: UUID | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        input_cost_usd: float | None = None,
        output_cost_usd: float | None = None,
        total_cost_usd: float | None = None,
    ) -> None:
        self.session.add(
            PromptTrace(
                stage=stage,
                provider=provider,
                model=model,
                prompt_digest=prompt_digest,
                paper_id=str(paper_id) if paper_id else None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                input_cost_usd=input_cost_usd,
                output_cost_usd=output_cost_usd,
                total_cost_usd=total_cost_usd,
            )
        )

    def summarize_costs(self, days: int = 7) -> dict:
        since = datetime.now(UTC) - timedelta(days=max(days, 1))
        total_q = select(
            func.count(PromptTrace.id),
            func.coalesce(func.sum(PromptTrace.input_tokens), 0),
            func.coalesce(func.sum(PromptTrace.output_tokens), 0),
            func.coalesce(func.sum(PromptTrace.total_cost_usd), 0.0),
        ).where(PromptTrace.created_at >= since)
        count, in_tokens, out_tokens, total_cost = (
            self.session.execute(total_q).one()
        )

        by_stage_q = (
            select(
                PromptTrace.stage,
                func.count(PromptTrace.id),
                func.coalesce(
                    func.sum(PromptTrace.total_cost_usd), 0.0
                ),
            )
            .where(PromptTrace.created_at >= since)
            .group_by(PromptTrace.stage)
        )
        by_model_q = (
            select(
                PromptTrace.provider,
                PromptTrace.model,
                func.count(PromptTrace.id),
                func.coalesce(
                    func.sum(PromptTrace.total_cost_usd), 0.0
                ),
            )
            .where(PromptTrace.created_at >= since)
            .group_by(PromptTrace.provider, PromptTrace.model)
        )

        by_stage = [
            {
                "stage": stage,
                "calls": calls,
                "total_cost_usd": float(cost),
            }
            for stage, calls, cost in self.session.execute(
                by_stage_q
            ).all()
        ]
        by_model = [
            {
                "provider": prov,
                "model": mdl,
                "calls": calls,
                "total_cost_usd": float(cost),
            }
            for prov, mdl, calls, cost in self.session.execute(
                by_model_q
            ).all()
        ]

        return {
            "window_days": days,
            "calls": int(count),
            "input_tokens": int(in_tokens or 0),
            "output_tokens": int(out_tokens or 0),
            "total_cost_usd": float(total_cost or 0.0),
            "by_stage": by_stage,
            "by_model": by_model,
        }


class SourceCheckpointRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, source: str) -> SourceCheckpoint | None:
        q = select(SourceCheckpoint).where(
            SourceCheckpoint.source == source
        )
        return self.session.execute(q).scalar_one_or_none()

    def upsert(
        self, source: str, last_published_date: date | None
    ) -> None:
        found = self.get(source)
        now = datetime.now(UTC)
        if found:
            found.last_fetch_at = now
            if last_published_date and (
                found.last_published_date is None
                or last_published_date > found.last_published_date
            ):
                found.last_published_date = last_published_date
            return
        self.session.add(
            SourceCheckpoint(
                source=source,
                last_fetch_at=now,
                last_published_date=last_published_date,
            )
        )


class CitationRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_edge(
        self,
        source_paper_id: str,
        target_paper_id: str,
        context: str | None = None,
    ) -> None:
        q = select(Citation).where(
            Citation.source_paper_id == source_paper_id,
            Citation.target_paper_id == target_paper_id,
        )
        found = self.session.execute(q).scalar_one_or_none()
        if found:
            if context:
                found.context = context
            return
        self.session.add(
            Citation(
                source_paper_id=source_paper_id,
                target_paper_id=target_paper_id,
                context=context,
            )
        )

    def list_all(self) -> list[Citation]:
        return list(
            self.session.execute(select(Citation)).scalars()
        )

    def list_for_paper_ids(
        self, paper_ids: list[str]
    ) -> list[Citation]:
        if not paper_ids:
            return []
        q = select(Citation).where(
            Citation.source_paper_id.in_(paper_ids)
            | Citation.target_paper_id.in_(paper_ids)
        )
        return list(self.session.execute(q).scalars())


class TopicRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_topics(
        self, enabled_only: bool = False
    ) -> list[TopicSubscription]:
        q = select(TopicSubscription).order_by(
            TopicSubscription.created_at.desc()
        )
        if enabled_only:
            q = q.where(TopicSubscription.enabled.is_(True))
        return list(self.session.execute(q).scalars())

    def get_by_name(self, name: str) -> TopicSubscription | None:
        q = select(TopicSubscription).where(
            TopicSubscription.name == name
        )
        return self.session.execute(q).scalar_one_or_none()

    def get_by_id(self, topic_id: str) -> TopicSubscription | None:
        return self.session.get(TopicSubscription, topic_id)

    def upsert_topic(
        self,
        *,
        name: str,
        query: str,
        enabled: bool = True,
        max_results_per_run: int = 20,
        retry_limit: int = 2,
    ) -> TopicSubscription:
        found = self.get_by_name(name)
        if found:
            found.query = query
            found.enabled = enabled
            found.max_results_per_run = max(max_results_per_run, 1)
            found.retry_limit = max(retry_limit, 0)
            found.updated_at = datetime.now(UTC)
            self.session.flush()
            return found
        topic = TopicSubscription(
            name=name,
            query=query,
            enabled=enabled,
            max_results_per_run=max(max_results_per_run, 1),
            retry_limit=max(retry_limit, 0),
        )
        self.session.add(topic)
        self.session.flush()
        return topic

    def update_topic(
        self,
        topic_id: str,
        *,
        query: str | None = None,
        enabled: bool | None = None,
        max_results_per_run: int | None = None,
        retry_limit: int | None = None,
    ) -> TopicSubscription:
        topic = self.session.get(TopicSubscription, topic_id)
        if topic is None:
            raise ValueError(f"topic {topic_id} not found")
        if query is not None:
            topic.query = query
        if enabled is not None:
            topic.enabled = enabled
        if max_results_per_run is not None:
            topic.max_results_per_run = max(max_results_per_run, 1)
        if retry_limit is not None:
            topic.retry_limit = max(retry_limit, 0)
        topic.updated_at = datetime.now(UTC)
        self.session.flush()
        return topic

    def delete_topic(self, topic_id: str) -> None:
        topic = self.session.get(TopicSubscription, topic_id)
        if topic is not None:
            self.session.delete(topic)


class LLMConfigRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[LLMProviderConfig]:
        q = select(LLMProviderConfig).order_by(
            LLMProviderConfig.created_at.desc()
        )
        return list(self.session.execute(q).scalars())

    def get_active(self) -> LLMProviderConfig | None:
        q = select(LLMProviderConfig).where(
            LLMProviderConfig.is_active.is_(True)
        )
        return self.session.execute(q).scalar_one_or_none()

    def get_by_id(self, config_id: str) -> LLMProviderConfig:
        cfg = self.session.get(LLMProviderConfig, config_id)
        if cfg is None:
            raise ValueError(
                f"llm_config {config_id} not found"
            )
        return cfg

    def create(
        self,
        *,
        name: str,
        provider: str,
        api_key: str,
        api_base_url: str | None,
        model_skim: str,
        model_deep: str,
        model_vision: str | None,
        model_embedding: str,
        model_fallback: str,
    ) -> LLMProviderConfig:
        cfg = LLMProviderConfig(
            name=name,
            provider=provider,
            api_key=api_key,
            api_base_url=api_base_url,
            model_skim=model_skim,
            model_deep=model_deep,
            model_vision=model_vision,
            model_embedding=model_embedding,
            model_fallback=model_fallback,
            is_active=False,
        )
        self.session.add(cfg)
        self.session.flush()
        return cfg

    def update(
        self,
        config_id: str,
        *,
        name: str | None = None,
        provider: str | None = None,
        api_key: str | None = None,
        api_base_url: str | None = None,
        model_skim: str | None = None,
        model_deep: str | None = None,
        model_vision: str | None = None,
        model_embedding: str | None = None,
        model_fallback: str | None = None,
    ) -> LLMProviderConfig:
        cfg = self.get_by_id(config_id)
        if name is not None:
            cfg.name = name
        if provider is not None:
            cfg.provider = provider
        if api_key is not None:
            cfg.api_key = api_key
        if api_base_url is not None:
            cfg.api_base_url = api_base_url
        if model_skim is not None:
            cfg.model_skim = model_skim
        if model_deep is not None:
            cfg.model_deep = model_deep
        if model_vision is not None:
            cfg.model_vision = model_vision
        if model_embedding is not None:
            cfg.model_embedding = model_embedding
        if model_fallback is not None:
            cfg.model_fallback = model_fallback
        cfg.updated_at = datetime.now(UTC)
        self.session.flush()
        return cfg

    def delete(self, config_id: str) -> None:
        cfg = self.session.get(LLMProviderConfig, config_id)
        if cfg is not None:
            self.session.delete(cfg)

    def activate(self, config_id: str) -> LLMProviderConfig:
        """激活指定配置，同时取消其他配置的激活状态"""
        all_cfgs = self.list_all()
        for c in all_cfgs:
            c.is_active = c.id == config_id
        self.session.flush()
        return self.get_by_id(config_id)

    def deactivate_all(self) -> None:
        """取消所有配置的激活状态（回退到 .env 默认配置）"""
        all_cfgs = self.list_all()
        for c in all_cfgs:
            c.is_active = False
        self.session.flush()


class GeneratedContentRepository:
    """持久化生成内容（Wiki / Brief）"""

    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        content_type: str,
        title: str,
        markdown: str,
        keyword: str | None = None,
        paper_id: str | None = None,
        metadata_json: dict | None = None,
    ) -> GeneratedContent:
        gc = GeneratedContent(
            content_type=content_type,
            title=title,
            markdown=markdown,
            keyword=keyword,
            paper_id=paper_id,
            metadata_json=metadata_json or {},
        )
        self.session.add(gc)
        self.session.flush()
        return gc

    def list_by_type(
        self, content_type: str, limit: int = 50
    ) -> list[GeneratedContent]:
        q = (
            select(GeneratedContent)
            .where(GeneratedContent.content_type == content_type)
            .order_by(GeneratedContent.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(q).scalars())

    def get_by_id(
        self, content_id: str
    ) -> GeneratedContent | None:
        return self.session.get(GeneratedContent, content_id)

    def delete(self, content_id: str) -> None:
        gc = self.session.get(GeneratedContent, content_id)
        if gc is not None:
            self.session.delete(gc)
