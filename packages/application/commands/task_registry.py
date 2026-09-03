"""第一批原子 Task 能力注册表（C4，设计③ §Task 原子边界）

单一事实源：每类工作原子的 capability 名、handler、幂等键模板、超时、重试、
资源类别与"不可自动重试"边界。C5 Workflow 模板、C6 调度器与 C7 Python Executor
都从本表读取；禁止在调用点散落硬编码。

原则（设计③）：只有值得被独立重试、隔离资源、观察或追溯的步骤才是 Task；
幂等键未命中即不重复产生领域副作用；send 类外部效果不可自动重试（manual_recovery）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    handler: str  # 可导入 dotted path："package.module:function"
    side_effect: str  # 单一有意义副作用的自然语言描述
    input_keys: tuple[str, ...]  # 稳定输入键（Task.input_ref 契约）
    idempotency_template: str  # 幂等键模板，{} 为占位
    timeout_s: int
    max_attempts: int
    resource_class: str  # default / network / llm / embedding
    manual_recovery: bool = False  # True = 失败不自动重试
    produces: tuple[str, ...] = field(default_factory=tuple)  # 产出（artifact/事件/领域变化）
    notes: str = ""


# 资源类别允许集（Dispatcher 按此隔离并发；与限流桶对齐）
RESOURCE_CLASSES = ("default", "network", "llm", "embedding")

TASK_CAPABILITIES: dict[str, CapabilitySpec] = {
    spec.name: spec
    for spec in [
        # ---------- 来源与文档 ----------
        CapabilitySpec(
            name="fetch_feed",
            handler="packages.integrations.arxiv_client:ArxivClient.fetch_latest",
            side_effect="无写库——返回候选 PaperCreate 列表供 upsert",
            input_keys=("query", "max_results", "sort_by", "days_back"),
            idempotency_template="fetch:{query}:{cursor}",
            timeout_s=120,
            max_attempts=3,
            resource_class="network",
            produces=(),
            notes="纯读外部源；失败按网络错误退避重试",
        ),
        CapabilitySpec(
            name="upsert_paper",
            handler="packages.storage.repositories.paper:PaperRepository.upsert_paper",
            side_effect="papers 行 + v1 SourceVersion + SourceAdded/SourceVersionDetected 事件（同事务）",
            input_keys=("arxiv_id", "title", "abstract"),
            idempotency_template="upsert:{arxiv_id}",
            timeout_s=30,
            max_attempts=3,
            resource_class="default",
            produces=("SourceAdded", "SourceVersionDetected"),
        ),
        CapabilitySpec(
            name="download_source",
            handler="packages.integrations.arxiv_client:ArxivClient.download_pdf",
            side_effect="PDF 文件落盘 + set_pdf_path",
            input_keys=("paper_id", "arxiv_id"),
            idempotency_template="dl:{arxiv_id}",
            timeout_s=300,
            max_attempts=3,
            resource_class="network",
            produces=(),
        ),
        # ---------- 研究流水线 ----------
        CapabilitySpec(
            name="skim_paper",
            handler="packages.ai.pipelines.paper_pipelines:PaperPipelines.skim",
            side_effect="AnalysisReport（summary_md/skim_score）+ PromptTrace 成本 + pipeline_runs",
            input_keys=("paper_id",),
            idempotency_template="skim:{paper_id}:{source_version_hash}",
            timeout_s=900,
            max_attempts=2,
            resource_class="llm",
            produces=("AnalysisReport",),
        ),
        CapabilitySpec(
            name="deep_read_paper",
            handler="packages.ai.pipelines.paper_pipelines:PaperPipelines.deep_dive",
            side_effect="AnalysisReport（deep_dive_md）+ ImageAnalysis + 同事务 ClaimExtraction",
            input_keys=("paper_id",),
            idempotency_template="deep:{paper_id}:{source_version_hash}",
            timeout_s=1800,
            max_attempts=2,
            resource_class="llm",
            produces=("AnalysisReport", "ClaimProposed"),
        ),
        CapabilitySpec(
            name="extract_claims",
            handler="packages.ai.claim_extractor:ClaimExtractionService.extract_for_paper",
            side_effect="ResearchRun + papermind Claims + Evidence（幂等指纹去重）",
            input_keys=("paper_id", "source_text"),
            idempotency_template="claims:{paper_id}:{source_version_hash}",
            timeout_s=600,
            max_attempts=2,
            resource_class="llm",
            produces=("ClaimProposed", "EvidenceExtracted"),
        ),
        CapabilitySpec(
            name="embed_paper",
            handler="packages.ai.pipelines.paper_pipelines:PaperPipelines.embed_paper",
            side_effect="papers.embedding 列更新",
            input_keys=("paper_id",),
            idempotency_template="embed:{paper_id}:{source_version_hash}",
            timeout_s=300,
            max_attempts=3,
            resource_class="embedding",
            produces=(),
        ),
        # ---------- 引用图谱 ----------
        CapabilitySpec(
            name="sync_citations_paper",
            handler="packages.ai.graph_service:GraphService.sync_citations_for_paper",
            side_effect="citations 边写入（外部引用 API 副作用）",
            input_keys=("paper_id", "limit"),
            idempotency_template="cite:{paper_id}:{date}",
            timeout_s=600,
            max_attempts=2,
            resource_class="network",
            produces=(),
        ),
        # ---------- 生成 ----------
        CapabilitySpec(
            name="generate_topic_wiki",
            handler="packages.ai.graph_service:GraphService.topic_wiki",
            side_effect="Wiki 文本（含 LLM；HTTP 语义下另写 generated_contents）",
            input_keys=("keyword", "limit"),
            idempotency_template="wiki:{keyword}:{date}",
            timeout_s=900,
            max_attempts=2,
            resource_class="llm",
            produces=("generated_contents",),
        ),
        CapabilitySpec(
            name="build_daily_brief",
            handler="packages.ai.brief_service:DailyBriefService.publish",
            side_effect="generated_contents + 简报 HTML 文件 + 可选邮件",
            input_keys=("recipient", "limit"),
            idempotency_template="brief:{date}",
            timeout_s=1800,
            max_attempts=2,
            resource_class="llm",
            produces=("generated_contents",),
        ),
        CapabilitySpec(
            name="send_brief_email",
            handler="packages.integrations.notifier:NotificationService.send_email_html",
            side_effect="外部邮件发送（不可撤回）",
            input_keys=("recipient", "html_ref"),
            idempotency_template="mail:{date}:{recipient}",
            timeout_s=60,
            max_attempts=1,
            resource_class="network",
            manual_recovery=True,  # 不可安全重放：失败进 manual_recovery，不自动重试
            produces=(),
            notes="发邮件不可撤回——失败人工介入，禁止自动重试（防重复骚扰）",
        ),
    ]
}


def get_spec(capability: str) -> CapabilitySpec:
    """取能力规格；未注册能力抛 KeyError（调用方显式登记，禁止静默兜底）"""
    return TASK_CAPABILITIES[capability]


def specs_for_resource_class(resource_class: str) -> list[CapabilitySpec]:
    return [s for s in TASK_CAPABILITIES.values() if s.resource_class == resource_class]
