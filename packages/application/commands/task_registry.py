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
        # ---------- C3 退出门：统一长任务（原 tracker 调用点全部迁移至此） ----------
        CapabilitySpec(
            name="daily_ingest_and_brief",
            handler="packages.ai.task_handlers:daily_ingest_and_brief",
            side_effect="订阅抓取入库 + 每日简报生成（generated_contents）",
            input_keys=(),
            idempotency_template="daily_ingest_brief:{date}",
            timeout_s=3600,
            max_attempts=2,
            resource_class="llm",
            produces=("generated_contents",),
        ),
        CapabilitySpec(
            name="weekly_graph_maintenance",
            handler="packages.ai.task_handlers:weekly_graph_maintenance",
            side_effect="逐主题引用边同步 + 增量同步（citations 边写入）",
            input_keys=(),
            idempotency_template="weekly_graph:{iso_week}",
            timeout_s=3600,
            max_attempts=2,
            resource_class="network",
            produces=(),
        ),
        CapabilitySpec(
            name="daily_report_workflow",
            handler="packages.ai.task_handlers:daily_report_workflow",
            side_effect="每日报告工作流（精读 + 生成 + 发邮件）",
            input_keys=(),
            idempotency_template="daily_report:{date}",
            timeout_s=5400,
            max_attempts=1,  # 含发邮件步骤，失败不自动重试（人工介入）
            resource_class="llm",
            manual_recovery=True,
            produces=("generated_contents",),
        ),
        CapabilitySpec(
            name="daily_report_send_only",
            handler="packages.ai.task_handlers:daily_report_send_only",
            side_effect="快速生成简报并发邮件（不可撤回）",
            input_keys=("recipient",),
            idempotency_template="report_send:{date}:{recipient}",
            timeout_s=1800,
            max_attempts=1,
            resource_class="llm",
            manual_recovery=True,
            produces=("generated_contents",),
        ),
        CapabilitySpec(
            name="batch_process_unread",
            handler="packages.ai.task_handlers:batch_process_unread",
            side_effect="未读论文批量 embed+skim（AnalysisReport/批量嵌入）",
            input_keys=("max_papers",),
            idempotency_template="batch_unread:{date}:{max_papers}",
            timeout_s=5400,
            max_attempts=1,  # 单篇失败已在 handler 内计数，整批重试会重复 LLM 成本
            resource_class="llm",
            produces=(),
        ),
        CapabilitySpec(
            name="skim_papers_batch",
            handler="packages.ai.task_handlers:skim_papers_batch",
            side_effect="选定论文批量粗读（AnalysisReport）",
            input_keys=("paper_ids",),
            idempotency_template="skim_batch:{paper_ids_hash}",
            timeout_s=3600,
            max_attempts=1,
            resource_class="llm",
            produces=(),
        ),
        CapabilitySpec(
            name="topic_dispatch",
            handler="packages.ai.task_handlers:topic_dispatch",
            side_effect="按订阅计划逐主题抓取入库（papers + SourceAdded）",
            input_keys=(),
            idempotency_template="topic_dispatch:{date_hour}",
            timeout_s=3600,
            max_attempts=1,  # 单主题失败在 handler 内记录，不整批重试
            resource_class="network",
            produces=(),
        ),
        CapabilitySpec(
            name="cs_feed_dispatch",
            handler="packages.ai.task_handlers:cs_feed_dispatch",
            side_effect="CS 分类同步 + 订阅抓取入库",
            input_keys=(),
            idempotency_template="cs_dispatch:{date_hour}",
            timeout_s=1800,
            max_attempts=2,
            resource_class="network",
            produces=(),
        ),
        CapabilitySpec(
            name="fetch_topic_papers",
            handler="packages.ai.task_handlers:fetch_topic_papers",
            side_effect="单个订阅主题抓取入库（papers + SourceAdded）",
            input_keys=("topic_id",),
            idempotency_template="topic_fetch:{topic_id}:{date_hour}",
            timeout_s=1800,
            max_attempts=2,
            resource_class="network",
            produces=(),
        ),
        CapabilitySpec(
            name="ingest_arxiv_query",
            handler="packages.ai.task_handlers:ingest_arxiv_query",
            side_effect="按关键词 arXiv 搜索入库（papers + action）",
            input_keys=("query", "max_results", "topic_id", "sort_by", "days_back"),
            idempotency_template="ingest_query:{query}:{date_hour}",
            timeout_s=1800,
            max_attempts=2,
            resource_class="network",
            produces=(),
        ),
        CapabilitySpec(
            name="import_selected",
            handler="packages.ai.task_handlers:import_selected",
            side_effect="按选中 ID 批量入库 + embed/skim（papers + action）",
            input_keys=("arxiv_ids", "query"),
            idempotency_template="import_selected:{arxiv_ids_hash}",
            timeout_s=3600,
            max_attempts=1,  # 内部逐篇容错，整批重试会重复 LLM 成本
            resource_class="network",
            produces=(),
        ),
        CapabilitySpec(
            name="import_references",
            handler="packages.ai.task_handlers:import_references",
            side_effect="参考文献批量导入（papers + citations）",
            input_keys=("source_paper_id", "source_paper_title", "entries", "topic_ids"),
            idempotency_template="ref_import:{source_paper_id}:{entries_hash}",
            timeout_s=3600,
            max_attempts=2,
            resource_class="network",
            produces=(),
        ),
        CapabilitySpec(
            name="cs_feed_fetch_category",
            handler="packages.ai.task_handlers:cs_feed_fetch_category",
            side_effect="单个 CS 分类抓取入库（papers）",
            input_keys=("category_code",),
            idempotency_template="cs_fetch:{category_code}:{date_hour}",
            timeout_s=1800,
            max_attempts=2,
            resource_class="network",
            produces=(),
        ),
        CapabilitySpec(
            name="sync_citations_incremental",
            handler="packages.ai.task_handlers:sync_citations_incremental",
            side_effect="增量引用边同步（citations 写入）",
            input_keys=("paper_limit", "edge_limit_per_paper"),
            idempotency_template="cite_incr:{date_hour}",
            timeout_s=1800,
            max_attempts=2,
            resource_class="network",
            produces=(),
        ),
        CapabilitySpec(
            name="sync_citations_topic",
            handler="packages.ai.task_handlers:sync_citations_topic",
            side_effect="主题引用边同步（citations 写入）",
            input_keys=("topic_id", "paper_limit", "edge_limit_per_paper"),
            idempotency_template="cite_topic:{topic_id}:{date_hour}",
            timeout_s=1800,
            max_attempts=2,
            resource_class="network",
            produces=(),
        ),
        CapabilitySpec(
            name="topic_wiki_save",
            handler="packages.ai.task_handlers:topic_wiki_save",
            side_effect="主题 Wiki 生成 + generated_contents 落库",
            input_keys=("keyword", "limit"),
            idempotency_template="wiki_save:{keyword}:{date}",
            timeout_s=900,
            max_attempts=2,
            resource_class="llm",
            produces=("generated_contents",),
        ),
        CapabilitySpec(
            name="daily_brief_publish",
            handler="packages.ai.task_handlers:daily_brief_publish",
            side_effect="每日简报生成 + generated_contents（HTTP 语义含 content_id）",
            input_keys=("recipient",),
            idempotency_template="brief_publish:{date}:{recipient}",
            timeout_s=1800,
            max_attempts=2,
            resource_class="llm",
            produces=("generated_contents",),
        ),
        CapabilitySpec(
            name="analyze_figures",
            handler="packages.ai.task_handlers:analyze_figures",
            side_effect="图表提取与解读（ImageAnalysis + 图片文件）",
            input_keys=("paper_id", "max_figures"),
            idempotency_template="figures:{paper_id}:{date}",
            timeout_s=1800,
            max_attempts=2,
            resource_class="llm",
            produces=("ImageAnalysis",),
        ),
        CapabilitySpec(
            name="translate_bilingual_pdf",
            handler="packages.ai.task_handlers:translate_bilingual_pdf",
            side_effect="双语 PDF 翻译（PaperTranslation 落库）",
            input_keys=("paper_id", "target_lang", "mode"),
            idempotency_template="bilingual:{paper_id}:{target_lang}:{mode}",
            timeout_s=900,
            max_attempts=2,
            resource_class="network",
            produces=("PaperTranslation",),
        ),
    ]
}


def get_spec(capability: str) -> CapabilitySpec:
    """取能力规格；未注册能力抛 KeyError（调用方显式登记，禁止静默兜底）"""
    return TASK_CAPABILITIES[capability]


def specs_for_resource_class(resource_class: str) -> list[CapabilitySpec]:
    return [s for s in TASK_CAPABILITIES.values() if s.resource_class == resource_class]
