# 设计②：Application command/query 清单与调用映射

状态：**待确认**（重构路线图 A6；六份设计之第二份）

日期：2026-09-02

依据：[PaperMind 2026 形态与重构设计](./2026-09-02-papermind-2026-rearchitecture.md) §5.1/§5.5；[Phase 0 现状审计](./2026-09-02-phase0-baseline-audit.md)。

范围：把当前全部能力入口——**165 个 HTTP 路由**（17 个 router 文件）、**9 个 MCP 工具**、**26 个 agent 工具**——映射到有限的 application 用例集合；每个入口给出目标用例与迁移批次；无对应用例的入口显式列入"保持现状/废弃候选"。本映射是 Stage B（B2–B7）的执行清单，也是后续 capability metadata（E5）的种子。

## 1. 方法与规则

1. **用例目录冻结**：新能力先在 §2 目录登记（含 surface contract，设计⑤）再实现；禁止 router/MCP/agent 各自长出新业务编排。
2. **映射三列**：入口 → 目标用例 → 迁移批次（B2/B3/B4/B5/B6/B7/保持现状/废弃候选）。
3. **保持现状 ≠ 例外破坏规则**：文件流代理（PDF/图片）与系统健康检查没有业务编排，留在 router 层直通，不强制套 application 层。
4. **命令面统一提交 Job**：凡触发长任务的命令（Start*），B7 起只创建 Job/入队，不在请求进程直跑（为 Stage C 原子 durable execution 铺路）。
5. **语义保留**：agent 工具的参数与返回结构不变（§5.5），业务下沉到 application；HTTP 返回保持兼容，前端不动。

## 2. 目标用例目录

### 2.1 Queries（读）

| 用例 | 语义 | 状态 |
| --- | --- | --- |
| SearchPapers | 关键词/多渠道搜索论文 | 待迁移（B2） |
| GetPaper | 单篇详情（含 segments/figures 读取） | 待迁移（B2） |
| ListPapers | 按日期/状态/主题/标签过滤 | 待迁移（B6） |
| GetSimilarPapers | embedding 相似 | 待迁移（B2） |
| GetResearchQuestion | 问题聚合视图 | **已落地（D4）** |
| ListClaims | 问题下 Claim 列表 | **已落地（D4）** |
| GetClaimEvidence | 证据追溯 | **已落地（D4）** |
| DiffResearchState | 研究状态 diff | **已落地（D4）** |
| ExportResearchObject | RO 导出 JSON/MD | **已落地（D5）** |
| AskKnowledgeBase | RAG 问答 | 待迁移（B6） |
| GetDailyBrief / ListGeneratedContents / GetGeneratedContent | 简报与生成产物 | 待迁移（B6） |
| GetRecommendations / GetTrends / GetTodaySummary | 推荐与趋势 | 待迁移（B6） |
| GetGraph*（similarity-map/cluster-map/overview/cocitation/timeline/survey/gaps 等 14 个） | 图谱查询（重计算，service 内缓存保留） | 待迁移（B6） |
| ListTopics / GetTopicStats / GetTopicDistribution | 主题订阅读取 | 待迁移（B6） |
| ListActions / GetAction | 采集行动记录 | 待迁移（B6） |
| ListPipelineRuns / GetTask / ListActiveTasks | 旧任务观测（C10 后并入 GetJob/ListJobs） | 过渡保留 |
| GetJob / ListJobs | durable execution 观测 | Stage C（C10） |

### 2.2 Commands（写/触发）

| 用例 | 语义 | 批次 |
| --- | --- | --- |
| ImportPaper | arXiv/IEEE/参考文献导入（入库同事务建 SourceVersion，D2 已落） | B7 |
| CreateResearchQuestion / UpdateResearchQuestion | Research State | B7 |
| ProposeClaim / ConfirmClaim / ReviseClaim / InvalidateClaim | Claim 状态机（ClaimRepository 已实现，此处为命令封装） | B7 |
| StartSkim / StartDeepRead / StartEmbedding | 读流水线（deep 已挂 ClaimExtraction） | B7 |
| StartTopicResearch / StartCitationSync / StartAutoLink / StartDeepTrace | 采集与图谱任务 | B7 |
| StartFigureAnalysis / StartReasoningAnalysis | 论文分析任务 | B7 |
| StartWikiGeneration / StartDailyBrief / StartDailyReport* / StartBatchProcess | 生成与批处理 | B7 |
| StartFeedFetch / ManageCsFeeds | CS feeds | B7 |
| UpdatePaperFlag / ManageTags / ManageTopics / ManageGeneratedContents | 状态与配置类写 | B7 |
| ManageLlmConfig / ManageEmailConfig / ManageReportConfig | 设置面（注意 activate 需触发 LLM 配置缓存失效） | B7 后期 |
| TranslateContent / WritingAssist / ExplainSegment / SensemakingAct | 内容生成（同步 LLM；长任务部分进 durable） | B7 后期 |
| RunAgentChat / ConfirmAgentAction / RejectAgentAction | agent 会话（§5.5：harness 留在 Python agent loop，工具业务下沉） | B5 |
| CancelJob / RetryJob / PauseQueue / ResumeQueue | 任务控制 | Stage C（C10） |

### 2.3 保持现状（不进 application 层）

| 入口 | 理由 |
| --- | --- |
| GET /papers/proxy-arxiv-pdf、GET /papers/{id}/pdf、GET /papers/{id}/figures/{fid}/image、GET /bilingual-pdf/{id}/file | 文件流直通，无业务编排 |
| GET /health、GET /system/status、GET /system/worker、GET /metrics/costs | 基础设施观测（C10 后 worker 部分并入 Executor 健康） |
| /auth/*（login/status/me/tokens/device*） | 身份面归设计⑥（HTTPS identity/token flow） |
| POST /tasks/track | **废弃候选**——前端在服务端内存"造任务"（审计 §2.1），F1 移除 |

## 3. HTTP 路由映射（165 条）

### papers.py（20）

| 路由 | 用例 | 批次 |
| --- | --- | --- |
| GET /papers/latest | ListPapers | B2 |
| GET /papers/{paper_id} | GetPaper | B2 |
| POST /papers/search-multi | SearchPapers | B2 |
| GET /papers/{paper_id}/similar | GetSimilarPapers | B2 |
| GET /papers/folder-stats | GetLibraryStats（ListPapers 扩展） | B6 |
| GET /papers/recommended | GetRecommendations | B6 |
| GET /papers/suggest-channels | SearchPapers（渠道建议） | B6 |
| GET /papers/{paper_id}/segments | GetPaper（segments 子资源） | B6 |
| GET /papers/{paper_id}/figures | GetPaper（figures 子资源） | B6 |
| GET /papers/{paper_id}/duplicates | ListPapers（重复检测） | B6 |
| POST /papers/{paper_id}/ai/explain | ExplainSegment | B7 后期 |
| PATCH /papers/{paper_id}/favorite、/reject | UpdatePaperFlag | B7 |
| POST /papers/{paper_id}/download-pdf | DownloadSourceVersion | B7 |
| POST /papers/{paper_id}/figures/analyze | StartFigureAnalysis | B7 |
| POST /papers/{paper_id}/reasoning | StartReasoningAnalysis | B7 |
| POST /papers/ingest/ieee | ImportPaper(ieee) | B7 |
| GET /papers/proxy-arxiv-pdf、/pdf、/figures/{fid}/image | 保持现状（文件流） | — |

### topics.py（13）

| 路由 | 用例 | 批次 |
| --- | --- | --- |
| GET /topics、/topics/stats、/topics/distribution | ListTopics / GetTopicStats / GetTopicDistribution | B6 |
| GET /topics/{id}/fetch-status | GetTask（过渡）→ GetJob（C10） | C10 |
| GET /ingest/references/status/{task_id} | 同上 | C10 |
| POST /topics、PATCH/DELETE /topics/{id} | ManageTopics | B7 |
| POST /topics/suggest-keywords | SuggestKeywords（LLM 查询） | B6 |
| POST /topics/{id}/fetch | StartTopicResearch | B7 |
| POST /ingest/arxiv | ImportPaper(arxiv) | B7 |
| POST /ingest/references | ImportReferences | B7 |

### pipelines.py（10）

| 路由 | 用例 | 批次 |
| --- | --- | --- |
| POST /pipelines/skim、/deep、/embed | StartSkim / StartDeepRead / StartEmbedding | B7 |
| POST /rag/ask、/rag/ask-iterative | AskKnowledgeBase | B6 |
| GET /pipelines/runs | ListPipelineRuns（过渡） | B6 |
| GET /tasks/active、/tasks/{id}、/tasks/{id}/result | ListActiveTasks / GetTask / GetTaskResult（过渡 → C10） | C10 |
| POST /tasks/track | **废弃候选（F1）** | F1 |

### research.py（5）——**已全部经 application.queries 落地（D4/D5）** ✔

### content.py（9）

| 路由 | 用例 | 批次 |
| --- | --- | --- |
| GET /generated/list、/{id} | ListGeneratedContents / GetGeneratedContent | B6 |
| GET /wiki/paper/{id}、/wiki/topic | GetPaperWiki / GetTopicWiki | B6 |
| GET /trends/hot、/trends/emerging、/today | GetTrends / GetTodaySummary | B6 |
| POST /tasks/wiki/topic | StartWikiGeneration | B7 |
| POST /brief/daily | StartDailyBrief | B7 |
| DELETE /generated/{id} | ManageGeneratedContents | B7 |

### graph.py（18）

| 路由 | 用例 | 批次 |
| --- | --- | --- |
| 14 个 GET /graph/* | GetGraph*（查询组，service 缓存保留） | B6 |
| POST /citations/sync/incremental、/topic/{id}、/{paper_id} | StartCitationSync | B7 |
| POST /graph/auto-link | StartAutoLink | B7 |
| POST /graph/citation-network/topic/{id}/deep-trace | StartDeepTrace | B7 |

### jobs.py（8）

| 路由 | 用例 | 批次 |
| --- | --- | --- |
| GET /actions、/actions/{id}、/actions/{id}/papers | ListActions / GetAction | B6 |
| POST /jobs/daily/run-once、/jobs/graph/weekly-run-once | RunScheduleOnce（运维触发命令） | B7 |
| POST /jobs/batch-process-unread | StartBatchProcess | B7 |
| POST /jobs/daily-report/run-once、/send-only、/generate-only | StartDailyReport* | B7 |

### 其余 router（汇总）

| 文件（条数） | 用例组 | 批次 |
| --- | --- | --- |
| agent.py（6） | RunAgentChat / ConfirmAgentAction / RejectAgentAction / 会话 CRUD | B5（会话 CRUD B6） |
| auth.py（9） | 身份面 → 设计⑥ | 保持现状 |
| settings.py（12）+ llm_configs.py（6） | ManageLlmConfig / ManageEmailConfig / ManageReportConfig | B7 后期 |
| tags.py（8） | ManageTags | B7 |
| cs_feeds.py（6） | ManageCsFeeds / StartFeedFetch | B7 |
| translate.py（5） | TranslateContent（bilingual-pdf 长任务 → durable） | B7 后期 |
| sensemaking.py（6+） | SensemakingAct | B7 后期 |
| writing.py（4） | WritingAssist | B7 后期 |
| system.py（4） | 保持现状（观测） | — |

## 4. MCP 工具映射（9 个，apps/api/mcp.py）

| 工具 | 用例 | 批次 |
| --- | --- | --- |
| search_papers | SearchPapers | B4 |
| get_paper | GetPaper | B4 |
| get_daily_brief | GetDailyBrief | B4 |
| recommend_papers | GetRecommendations | B4 |
| find_similar | GetSimilarPapers | B4 |
| trigger_skim | StartSkim | B4（命令封装后） |
| trigger_embed | StartEmbedding | B4 |
| trigger_daily_job | StartDailyIngest | B4 |
| get_task_status | GetTask（过渡 → GetJob） | C10 |

B4 的改造方式：工具函数只做"解析参数 → 调 application → 组装 MCP 结果"，删除对 `deps.pipelines/rag_service/graph_service` 的直接引用（审计 §1.6）。

## 5. Agent 工具映射（26 个，packages/ai/tools/registry.py）

| 工具组 | 工具 | 用例 | 批次 |
| --- | --- | --- | --- |
| 只读查询 | search_papers、get_paper_detail、get_similar_papers、get_citation_tree、get_timeline、list_topics、get_system_status、list_papers_by_filter | 对应 Query | B5 |
| LLM 查询 | ask_knowledge_base、suggest_keywords、writing_assist、search_arxiv | AskKnowledgeBase / SuggestKeywords / WritingAssist / SearchPapers(arxiv) | B5 |
| 触发任务 | skim_paper、deep_read_paper、embed_paper | StartSkim / StartDeepRead / StartEmbedding（agent 内同步语义保留） | B5 |
| 批处理 | batch_skim/deep_read/embed_papers、get_batch_job_status | StartBatchJob / GetJob（batch_jobs → durable，Stage C） | B5 |
| 生成与分析 | generate_wiki、generate_daily_brief、reasoning_analysis、analyze_figures、identify_research_gaps | 对应 Command | B5 |
| 配置 | manage_subscription | ManageTopics | B5 |
| 导入 | ingest_arxiv | ImportPaper | B5 |

改造方式（§5.5）：`registry.py` 保留 schema 与 confirm 语义，handler 改为调 application；`registry.py` 不再是能力唯一注册点（长期由 capability contract 派生，E5）。

## 6. 与 Research State 的交汇

- `StartSkim/StartDeepRead` 在 B7 封装时保留 D3 已落地的链路：deep read 同事务生成 ResearchRun → 待验证 Claim。
- `ProposeClaim/ConfirmClaim/ReviseClaim/InvalidateClaim` 命令 = ClaimRepository 状态机的薄封装（含"无证据不得 confirmed、papermind 仅用户可确认"规则）。
- `ImportPaper` 保留 D2 链路：入库同事务建 v1 SourceVersion + SourceAdded/SourceVersionDetected。
- `CancelJob` 等任务控制在 Stage C 之前没有真实对象（当前无 cancel 端点），B7 只登记目录不实现。

## 7. 迁移批次出口核对（Stage B）

| 批次 | 覆盖 | 出口 |
| --- | --- | --- |
| B2 | papers 读路径（latest/get/search-multi/similar） | HTTP 返回兼容，e2e 通过 |
| B3 | research/* | 已完成（D4/D5 即 B3 实体） |
| B4 | MCP 9 工具 | 不再引用 deps 服务单例 |
| B5 | agent 26 工具 | registry 不再直接 import 具体服务 |
| B6 | 上表 B6 查询组（约 45 条） | 逐批提交 |
| B7 | 命令面（约 40 条） | 长任务命令只创建 Job/入队 |

## 8. 待确认决策点

1. **用例目录粒度**：Graph 14 个端点归并为"GetGraph* 查询组"（一个用例族、多个 query 函数），还是逐个登记？提案：用例族。
2. **agent 会话（agent.py）**：RunAgentChat 留在 Python agent loop（§5.5），仅工具业务下沉——确认不需要在 B 阶段重写会话编排。
3. **/tasks/track 废弃时机**：提案 F1（前端瘦 身）执行，B 阶段只标记 deprecated。
4. **身份面（auth.py）不进 application 层**：独立信任域，由设计⑥统一——确认。

## 变更记录

- 2026-09-02：初版（A6）。当前入口规模：HTTP 165（含 D4/D5 新增 5 条 research 路由）、MCP 9、agent 26。
