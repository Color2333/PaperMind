# PaperMind 2026 重构路线图（小目标拆解）

状态：**执行中**

日期：2026-09-02

分支：`refactor/papermind-2026`

依据：[PaperMind 2026 形态与重构设计](./2026-09-02-papermind-2026-rearchitecture.md)（下称"设计文档"，2026-09-02 第四版：Go Core + Python Executors + Pi downstream fork + Local PM UI + Full Web 可选化 + 原子 Durable Execution）

## 工作规则

1. 一次只推进一个小目标；完成即提交，不攒大批量改动。
2. 目标粒度以"一个工作日内可完成、有客观出口条件"为准；超出的目标继续拆。
3. 保持外部行为兼容（HTTP 返回、CLI 退出码），内部重定向到新边界；不同时重做 UI 和领域模型。
4. 重构期间冻结新增页面（设计文档 Phase 0 约束），除非直接服务于重构或 Demo。
5. Full Web 瘦身以 route/capability inventory 的 retain/merge/local-ui/archive 标记为准，禁止直接批量删除。
6. 每个目标完成后在本文档勾选状态并写一行结论；发现新事实时更新拆解，不靠口头记忆。

## 进度总览

| 阶段 | 目标数 | 已完成 | 状态 |
| --- | --- | --- | --- |
| Stage A · Phase 0 基线 + 六份设计 | 10 | 9 | 进行中（仅余 A2 待服务器实测） |
| Stage B · Phase 1 application command/query | 8 | 8 | 已完成（遗留后期批次：tags/cs_feeds/设置面/sensemaking/translate/writing，见 B8 条目） |
| Stage C · Phase 2 Go Core + 原子 durable execution | 12 | 8 | 进行中 |
| Stage D · Phase 3 Research State 垂直切片 | 7 | 7 | 已完成 |
| Stage E · Phase 4 PM Research Terminal + MCP 一等化 | 10 | 0 | 未开始 |
| Stage F · Phase 5 Local UI 与可选 Full Web 适配 | 7 | 0 | 未开始 |
| Stage G · Phase 6 公开 Demo | 3 | 0 | 未开始 |
| Stage H · Phase 7 资源/存储验证门 | 2 | 0 | 未开始 |

主线顺序：A → B → C → D → E → F → G → H（对应设计文档 Phase 0–7）。其中设计文档 §11 的**第一个只读垂直切片**（SearchPapers + GetPaper + GetResearchQuestion + ListClaims + GetClaimEvidence，贯穿 application handlers → typed HTTPS client → deterministic CLI → Pi tool + renderer → Local UI/Full Web adapters → MCP adapter）横跨 B3/B4、E4–E6、F4/F5 与 E8，是 Stage B→F 的主线验收样例；六份设计（A5–A10）获确认后即从它开始。

## Stage A — Phase 0 基线与六份设计

阶段出口条件：设计文档 Phase 0 出口条件全部满足，且六份设计获确认。

- [x] **A1 长任务入口、状态存储、线程池审计**
  产出：[2026-09-02 Phase 0 现状审计](./2026-09-02-phase0-baseline-audit.md)。
  结论：任务状态三处分裂（内存 TaskTracker / `batch_jobs` 表 / 心跳文件），job 控制面（cancel/retry/pause/resume/lease）为零，核心流程零回归测试。
- [ ] **A2 资源基线测量**
  产出：测量脚本 + `docs/plans/` 基线记录。
  内容：API/worker/PostgreSQL/前端容器的空闲与峰值 RSS、镜像大小、冷启动时间；需在服务器上实测。
  出口条件：每个容器均有数值记录（Phase 0 出口条件第 1 项）。
- [x] **A3 核心流程回归测试**
  产出：[tests/test_e2e_main_flow.py](../../tests/test_e2e_main_flow.py)（3 个测试：arXiv 导入与去重 / 导入→下载PDF→skim→deep→embed→ask→brief 全链路 / 空库 RAG 兜底）+ [.github/workflows/tests.yml](../../.github/workflows/tests.yml)（PR/push 自动跑 pytest）。
  结论：主链路在 HTTP→service→repository 层面可重复运行；LLM/arXiv/vision 以类级 fake 隔离，每测试独立 tmp SQLite(WAL)，全套 85 passed。
- [x] **A4 Research State 人工校验样本**
  产出：[scripts/seed_research_sample.py](../../scripts/seed_research_sample.py)（包装 [packages/ai/seed_research.py](../../packages/ai/seed_research.py)）——预置问题"视听说话人分离"+ 每篇论文一条 author 引用即证判断（规则自动 confirmed）+ 一条 papermind 综合判断（保持 draft）+ supports 关系；幂等可重跑。
  结论：author 部分按已确认规则即证即 confirmed；papermind 部分明确标记待人工校验——建议用户在 Demo 前抽查一次（`python scripts/seed_research_sample.py --dry-run`）。
- [x] **A5 设计①：Research State 最小数据契约**
  产出：[2026-09-02 设计① Research State 最小数据契约](./2026-09-02-design-1-research-state-data-contract.md)。
  结论：7 实体字段级契约 + Claim 状态机（无证据坐标不得 confirmed；papermind 最高 pending_verification）+ 事件表兼任 History/outbox + PROV 字段级映射 + 与现有 schema 的不回填共存策略；§11 五个决策点已按提案确认（2026-09-02）。
- [x] **A6 设计②：Application command/query 清单与调用映射**
  产出：[2026-09-02 设计② Application 用例映射](./2026-09-02-design-2-application-use-case-map.md)。
  结论：165 HTTP + 9 MCP + 26 agent 工具全部映射到用例目录（Queries 24 / Commands 31 / 保持现状 4 组 / 废弃候选 1），并给出 B2–B7 批次出口；research/* 已随 D4/D5 落地为目录首批实体。§8 有 4 个决策点待确认。
- [x] **A7 设计③：原子 Durable Execution 协议与迁移说明**
  产出：[2026-09-02 设计③ 原子 Durable Execution 协议](./2026-09-02-design-3-durable-execution-protocol.md)。
  结论：jobs/tasks/task_attempts/artifacts 四张表 schema + Job/Task 状态机（lease/fencing/协作式取消）+ 第一批 9 个 Task 原子边界（幂等键/超时/重试）+ 4 个 Workflow 模板 + 五组件部署形态 + 旧机制（TaskTracker/batch_jobs/APScheduler/heartbeat/裸线程）逐项收敛映射 + C11 验收用例。§9 有 4 个决策点待确认。
- [x] **A8 设计④：PM Research Terminal downstream 架构**
  产出：[2026-09-02 设计④ Terminal 架构](./2026-09-02-design-4-terminal-architecture.md)。
  结论：PaperMind-Terminal 独立仓库 + pinned upstream + 有序 patch stack + profile→build→source 三段裁剪；@papermind/cli 包结构、确定性命令面 v1（映射设计②用例）、五类退出码与 --json 契约、三档 permission profiles、六类领域卡片、终端契约测试；现有 Python pm（设备码协议）作为过渡资产复用。§10 有 4 个决策点待确认。
- [x] **A9 设计⑤：UI Surface Contract**
  产出：[2026-09-02 设计⑤ UI Surface Contract](./2026-09-02-design-5-ui-surface-contract.md)。
  结论：现有 16 条 Web 路由全量标记（retain 11 / merge 2 / local-ui 1 / redirect 1，无 archive）；canonical presentation model 以 capability metadata output_schema 生成 TS 类型（Python 为源）；三个共享包边界 + loopback bridge 安全契约（nonce/CSRF/allowlist/内存 token）+ 五类 Local UI 界面 + Full Web 三 profile + 五面 surface contract 测试。§9 有 4 个决策点待确认。
- [x] **A10 设计⑥：HTTPS identity/token flow**
  产出：[2026-09-02 设计⑥ identity/token flow](./2026-09-02-design-6-identity-token-flow.md)。
  结论：三信任域凭据模型（PaperMind/模型 provider/上游身份严格分离）；scope 二值升级四值（research:read/write、jobs:control、admin，capability metadata 为权威）；现有设备码流规范固化（限速/一次性/TTL）；GitHub Web 登录最小映射（Demo）；MCP OAuth protected resource discovery 迁移路径；Local UI session 边界。§10 有 4 个决策点待确认。

## Stage B — Phase 1：application command/query

阶段出口条件：Full Web、Local UI、PM Research Terminal 和 MCP 对同一能力调用同一个 application handler；存在第一版 canonical presentation model。

- [x] **B1 application 层骨架**：建立 commands/queries 目录结构、handler 协议与依赖注入约定；repository/provider 只允许在 application 层内使用。
  结论：`packages/application/`（queries：research_state/research_export/papers；commands 占位待 B7）；层约定写入包 docstring——query 接收 session 返回 canonical dict，上层禁止直接 import 服务单例，对外兼容优先。
- [x] **B2 canonical presentation model 第一版**：定义 Paper/Claim/Evidence/Job/Task/Attempt/Artifact/diff 的 view model 契约；application handler 产出 canonical result，HTTP 返回用其包裹并保持兼容。TS 侧共享类型在 F2 正式提取，但契约先在服务端定死。
  结论：canonical result = application queries 的 plain dict（D4/D5/B2 已是唯一事实源）；TS 类型生成规则已在设计⑤ §2 固化（capability metadata output_schema 构建期导出），F2 执行提取。
- [x] **B3 只读切片①：SearchPapers + GetPaper**：对应 HTTP 路由改为调用 application handler，返回保持兼容，前端不动。
  产出：[packages/application/queries/papers.py](../../packages/application/queries/papers.py)（list_papers/get_paper/search_multi/get_similar_papers，含序列化下沉）+ papers.py 四路由改薄封装（404 detail 形状保持兼容）。
  结论：e2e 断言四端点返回兼容（latest/detail/404/similar/search-multi fake 渠道），全量 113 passed。
- [x] **B4 只读切片②：GetResearchQuestion/ListClaims/GetClaimEvidence**：同上，覆盖研究状态读取面。
  结论：已随 D4/D5 完成——/research/* 五个只读路由全部经 application.queries（research_state/research_export），e2e 覆盖四端点 + 导出。
- [x] **B5 MCP 工具改调 application handlers**：`apps/api/mcp.py` 工具不再直接引用 deps/service（审计 §1.6）。
  产出：9 个工具改调 application（新增 [queries/content.py](../../packages/application/queries/content.py)、[queries/tasks.py](../../packages/application/queries/tasks.py)（过渡）、[commands/pipelines.py](../../packages/application/commands/pipelines.py)、[commands/daily.py](../../packages/application/commands/daily.py)）；工具体抽为 `_tool_*` 可测试函数 + 薄 `@mcp.tool` 包装；MCP 字段契约（skim_summary/deep_dive 等）在协议层映射保持不变。
  结论：`mcp.py` 零 `apps.api.deps` 引用；6 个工具测试（读/同步命令/异步任务/失败路径），全量 119 passed。
- [x] **B6 agent tools 改调 application handlers**：`packages/ai/tools/registry.py` 保留参数与返回语义，handler 业务下沉（设计文档 §5.5）。
  产出（2026-09-02，共三批 + 收尾）：24 个 agent 工具全部改调 application——read×3（commands/pipelines）、batch×4（commands/batch，过渡）、search 族×11（queries/papers/ask/graph/content 扩展）、analysis×2（queries/analysis）、writing×1、system×1、topics×2（queries/topics）、wiki/brief/gaps×3（commands/brief/wiki、queries/graph）、ingest×2（commands/ingest：导入业务 + 双层并行 + 后台 PDF 池 + tracker 内聚，handler 只做进度→ToolProgress 桥接）。
  结论：registry 保留 schema/confirm/短前缀解析语义；`_get_paper_detail` 为纯投影（无服务引用）保持原状。**测试顺带修掉存量 bug**：search_arxiv 对 PaperCreate 误用 ORM 列名 `metadata_json`（有结果即 AttributeError）。全量 125 passed。
- [x] **B7 其余查询全量迁移**：按 A6 映射清单逐个推进，每批一个提交。
  产出（2026-09-02，三批）：content 8 条（wiki×2/generated×2/trends×2/today；写 generated 走 commands/generated）；topics 6 条（列表含批量聚合/stats/distribution/suggest-keywords/fetch-status/references status）；jobs actions×3（queries/actions.py）；pipelines runs + tasks×4（queries/tasks.py 过渡观测）；graph 14 个 GET 全部经 queries/graph.py（facade lru_cache 持有；TTL 缓存与 run_in_threadpool 留在传输层）。
  结论：canonical result 平铺 plain dict，HTTP 404/detail 形状逐处兼容；e2e 覆盖 topics/stats/actions/runs/tasks/trends/graph 空库路径。全量 126 passed。
- [x] **B8 命令面迁移**：ImportPaper/CreateResearchQuestion/StartSkim/StartDeepRead/StartEmbedding 等写路径走 application command，长任务入口统一创建 Job，不再直接调用具体 Worker 或线程池（为 Stage C 铺路）。
  产出（2026-09-02，四批）：papers 写×6（flag/download-pdf/figures-analyze/reasoning/ieee → commands/papers + ingest + queries/analysis）；topics 写×6（CRUD/fetch/references → commands/topics）；ingest/arxiv（→ commands/ingest.import_from_arxiv_query + describe_ingested_papers）；pipelines Start*×3（commands/pipelines.start_*）；graph 同步×5（commands/graph）；content×3（wiki task → commands/wiki.start_topic_wiki_with_save、brief/daily → commands/brief.start_daily_brief_task、generated delete）；jobs POST×5（commands/daily：daily_job/weekly_maintenance/batch_unread/daily_report×2——BackgroundTasks 原语在该层消失，命令自管后台线程）。
  结论：长任务入口统一在 application command 内提交（tracker 为过渡载体，Stage C 将其替换为 durable Job——每命令一处替换点）；执行中修掉两个迁移引入的 bug（action_type=None 覆盖默认、brief 任务错用 agent 形状丢 content_id）。e2e 覆盖 flag/引用同步/generate-only。全量 127 passed。**遗留后期批次**：tags×8、cs_feeds×6、settings/llm_configs×18、sensemaking/translate/writing（设计② "B7 后期" 档）。

## Stage C — Phase 2：Go Core + 原子 durable execution

阶段出口条件：API/Executor 任意重启后，任务状态可解释、可恢复且不会静默丢失；同一 Task 的重复 Attempt 不会重复提交领域结果；单篇失败无需重跑整个批次。

- [x] **C0 Go Core 与 Executor Protocol 骨架**：建立 Go module、配置/健康检查/版本化 HTTPS API、capability registry 和 Python executor client；协议覆盖 register、claim、heartbeat、complete、fail、cancel，所有消息带 schema/version 与 correlation id。先跑通 fake Executor，不迁移算法。
  产出：[core/](../../core/)（module `github.com/Color2333/PaperMind/core`，纯 stdlib 零依赖）——protocol.go（信封 v1 + 六动作消息类型）、registry.go（内存能力注册 + 任务队列 + lease 签发 + 最简 fencing）、server.go（7 端点）、main.go（:8081，CORE_ADDR 可覆盖）+ [core/README.md](../../core/README.md)。
  Python 侧：[packages/core_client/client.py](../../packages/core_client/client.py)（六动作 + health，correlation_id 生成/回显校验，SchemaMismatchError 类型化）。
  验证：Go 7 个测试全绿（fake Executor 完整闭环/fail 重入队+迟到 complete 409 拒绝/cancel/schema 拒绝/未注册拒绝）；Python 契约测试 5 个（hermetic MockTransport）；CI 增加 go-core job（vet+test）。全量 141 passed。
- [x] **C1 batch consumer 移出 API 进程**：Python API lifespan 不再启动任务消费（审计 §1.5，现仅 API 进程消费 `batch_jobs`，worker 不参与）；新任务入口转向 Go Core。
  产出（2026-09-02）：`apps/api/main.py` lifespan 移除 `_batch_lifespan`（仅保留 MCP session manager）；`apps/worker/main.py` 启动/优雅关闭接管 `batch_consumer.start()/stop()`；`batch_consumer` 抽出可单步执行的 `poll_once()`。
  结论：Python 侧进程职责分离达成（API 请求处理 / worker 任务消费）。**顺带根修存量 bug**：claim 事务提交后 ORM 脱管过期，`_run_one_job` 访问 `job.paper_ids` 必抛 DetachedInstanceError 并被 loop 吞掉——批次任务此前一进入执行就卡 running；改为事务内取纯值。守卫测试（API 源码无 batch 引用 + worker 接管）+ 3 个消费行为测试。全量 136 passed。
  遗留：`新任务入口转向 Go Core` 半句依赖 C0——届时 batch 类入口从 tracker/batch_jobs 切到 Go Job 提交（C11 第一批）。
- [x] **C2 原子执行 schema**：落库 `jobs`、`tasks`、`task_attempts` 和 artifact/event references；ResearchRun 关联 Job，Job 聚合 Task，Task 保留 capability/schema/handler version、依赖、资源类别、预算与幂等键。
  产出：4 张 ORM 表（UUIDv7；tasks↔artifacts FK 环用 use_alter）+ 3 组枚举（JobStatus 含 succeeded / TaskStatus 8 态 / AttemptStatus）+ alembic `e2f3a4b5c6d7` + SQLite create_all 兜底 + [repositories/durable.py](../../packages/storage/repositories/durable.py)（Job 幂等创建、claim 签发 lease+attempt+fencing、依赖满足检查、fail→重试/dead_letter、Artifact 关联、Job 状态由子 Task 收敛的 `recompute_job_status`）。
  结论：9 个契约测试全绿（幂等/lease 互斥/fencing 拒绝/重试→dead_letter/partially_succeeded 收敛/依赖顺序/artifact/Run↔Job 关联/attempt 记录）；alembic 离线渲染通过。全量 150 passed。
- [x] **C3 统一旧状态**：用新 job store 取代内存 `TaskTracker`（10 分钟 TTL、重启即丢）、旧 `batch_jobs` 状态与心跳文件的权威地位；前端三套轮询端点收敛到 Job graph、Task 与 Attempt 查询。
  产出：`tasks.external_ref` 列（migration `f3a4b5c6d7e8`）+ `commands/jobs.py` 的 `submit_durable_job`/`submit_tracked_compat`（durable Job+Task+Attempt 持久化桥接：进度双写/lease 续约/成功失败写回/result 存储）+ 12 个 tracker.submit 站点全部接桥（pipelines×3/graph×3/papers×1/wiki×2/brief×1/topics×1/daily×3 中的 submit 形态）。
  统一观察面：`GET /jobs`、`GET /jobs/{id}`（Job graph + attempts）、`/tasks/active`（tracker+durable 合并）、`/tasks/{id}` 与 `/tasks/{id}/result` **durability 优先**（重启后 tracker 丢失仍可查询）。
  结论：durable store 成为任务状态权威记录，tracker 降级为进程内执行通道；api-thread 领取用 `claim_task_by_id`（fn 与 Task 绑定，不做工作窃取）。过程中修掉 3 个迁移引入 bug（create_job status 参数、位置参数顺序、wiki fn_kwargs 冗余透传）。新增 3+1 个测试（桥接成功/失败流、兼容形状、统一端点 e2e）。全量 154 passed + Go 7 passed。
  遗留：batch_jobs/心跳文件/线程型 daily-report 的权威切换随 C7（Executor）与 C11（渐进迁移）完成。
- [x] **C4 第一批原子 Task 清单**：为 Skim、DeepRead、Embedding、Topic Research 和 Daily Brief 标出单一有意义副作用、输入输出、timeout、retry、resource class 与无法自动重试的边界；禁止把普通 helper 机械拆成 Task。
  产出：[packages/application/commands/task_registry.py](../../packages/application/commands/task_registry.py)——12 个 CapabilitySpec（fetch_feed/upsert_paper/download_source/skim/deep_read/extract_claims/embed/sync_citations_paper/topic_wiki/daily_brief/send_brief_email），每条含 handler dotted path、幂等键模板、timeout、max_attempts、resource_class、manual_recovery 边界与产出声明。
  结论：不变量测试 5 项（handler 可导入/timeout>0/resource class 合法/manual_recovery ⇒ max_attempts=1/四类资源覆盖）；Start* 命令（pipelines×3、wiki、brief）已改为从注册表读 spec。全量 179 passed + Go 7 passed。
- [x] **C5 代码化 Workflow 模板**：实现顺序依赖、条件分支和 per-Paper fan-out；父 Job 支持 succeeded、partially_succeeded、failed、cancelled，并能解释每个子 Task 的贡献。
  产出：[packages/application/commands/workflows.py](../../packages/application/commands/workflows.py)——WORKFLOW_TEMPLATES 注册 4 个代码定义模板（RunTopicResearch：fetch+每篇 upsert→download→skim∥embed→extract fan-out；ProcessUnreadBatch：per-Paper skim∥embed；BuildDailyBrief：build→条件 send_mail；RunCitationSync：per-Paper fan-out）+ `expand_job` 幂等展开（idempotency 去重，重放不重复）+ `start_workflow_job`。
  结论：depends_on 在展开期解析为同 Job task id；claim 按依赖满足过滤；父 Job 收敛复用 C2 recompute（全成功→succeeded/部分→partially_succeeded）。6 个测试（fan-out 数量/依赖解析/幂等重放/条件分支/收敛）。全量 185 passed + Go 7 passed。
- [x] **C6 Go 调度控制面**：在 Go Core 中实现 Scheduler、Planner、Dispatcher 和 Reconciler；旧 APScheduler 仅在过渡期把到期事件提交为 Go Job，不再进程内直跑研究逻辑。
  产出：core/controlplane.go——控制面 `POST /v1/tasks/submit`（capability/input/resource_class/timeout/priority）入 Core 内存调度队列；观察面 `GET /v1/tasks/{id}/status`（状态/attempt/失败计数/结果）；Reconciler 循环回收过期 lease（回队列重跑，C8 扩展退避）。
  结论：Go 测试 10 个（控制面提交→fake Executor 闭环/观察面含结果/过期 lease 回收后新 attempt/schema 校验）；Planner/Dispatcher 的依赖与优先级逻辑与 C2 仓储/HTTP claim 共享（claim 端点即 Dispatcher 出口）；APScheduler 提交切换待 C7 Executor 可执行后落地（Core 任务当前无真实 handler 执行者）。全量 185 passed + Go 10 passed。
- [x] **C7 Python Executor 落地**：Python Executor 每次只执行一个 Task Attempt，通过 C0 协议注册 capability/version/resource class、领取和续约 lease、提交 result proposal/Artifact，支持协作取消与 drain；不直写 Job/Task/Attempt 或 Research State 表。
  产出：[packages/executor_runtime/runner.py](../../packages/executor_runtime/runner.py)——ExecutorRunner（claim→handler→complete/fail 循环 + 心跳线程续约 + cancel_requested 协作取消 + drain/idle-exit）+ `handlers_from_registry`（C4 注册表 dotted path 解析与适配）。Executor 不直写任何领域表——提交面全部经 C0 协议。
  结论：5 个 hermetic 测试（完整周期/handler 异常→fail/no_handler/cancel_requested 协作退出/drain 停止领取）。全量 190 passed + Go 10 passed。
- [ ] **C8 lease、fencing 与 Reconciler**：领取和续约 lease 时签发 fencing token；迟到 Attempt 不能覆盖新结果；Reconciler 回收过期 lease 并执行 backoff、dead-letter 或 manual recovery。
- [ ] **C9 Go 权威提交与副作用账本**：Go Core 校验 attempt、fencing token、result schema 和幂等键后，将 Paper/Claim/Evidence 变化与 outbox 在同一事务提交；Python 只提交 proposal。邮件、provider call 等外部效果使用 provider key 或 effect ledger 去重。
- [ ] **C10 控制与观察面**：实现 cancel/retry/pause/resume、Job graph、Task/Attempt 日志/成本/错误接口；CLI、MCP、Local UI 与 Full Web 共用同一资源语义。
- [ ] **C11 渐进迁移与恢复测试**：先迁移 `batch_jobs` 三类任务，再迁移 scheduler jobs 和 idle processor；用 API/Executor 强杀、lease 过期、重复领取、部分失败和迟到写入测试替代 `recover_stale_running` 的破坏性恢复。

## Stage D — Phase 3：Research State 垂直切片

阶段出口条件：同一 Claim 能从 Web/API 追溯到精确证据、生成活动和历史版本；无证据坐标的模型输出不进入 confirmed 状态。

- [x] **D1 数据契约落地**：按 A5 设计建模 + migration。
  产出：7 张 ORM 表（UUIDv7 hex 主键）+ 13 个领域枚举 + `packages/domain/ids.py` + alembic migration `d1e5a9c3b7f2` + SQLite `create_all` 兜底 + [repositories/research.py](../../packages/storage/repositories/research.py)（状态机强制、evidence 幂等指纹、事件与业务变更同事务写入）。
  结论：16 个契约测试全绿（tests/test_research_state.py）；alembic 离线渲染与 SQLite 运行时建表已验证；全量 101 passed。
- [x] **D2 样本迁移**：迁移 A4 的预置研究问题与少量论文，不批量回填历史数据。
  产出：`PaperRepository.upsert_paper` 新建分支同事务建 v1 SourceVersion（幂等，9 个入库路径全覆盖）+ seed 脚本（存量切片论文回补 v1，author 引用即证 + papermind draft 占位）。
  结论：ingest → SourceVersion/事件 同事务由 e2e 测试断言；种子幂等由 3 个契约测试覆盖；全量 104 passed。
- [x] **D3 ResearchRun 生成待验证 Claim**：强制证据坐标与完整 provenance（source version、任务、时间、模型、策略版本）。
  产出：[packages/ai/claim_extractor.py](../../packages/ai/claim_extractor.py)（`extract_in_session` 可嵌调用方事务 / `extract_for_paper` 独立事务）+ `build_claim_extraction_prompt` + deep_dive 管线挂接（同事务原子提交，抽取失败不影响精读结果）。
  结论：Run 记录 model/policy/cost_refs（指向 PromptTrace）；引用无法在源文本核实的判断保持 draft（不伪造坐标），可核实的经证据规则推进 pending_verification；幂等键 = 同版本+同引用+同坐标。4 个单元测试 + e2e 断言，全量 108 passed。
- [x] **D4 查询实现**：GetResearchQuestion、ListClaims、GetClaimEvidence、DiffResearchState。
  产出：[packages/application/queries/research_state.py](../../packages/application/queries/research_state.py)（application 层第一个模块，canonical result 为 plain dict）+ 只读路由 [apps/api/routers/research.py](../../apps/api/routers/research.py)（/research/questions/*、/research/claims/*/evidence，已挂 main.py）。
  结论：diff 以 research_events 为唯一事实源，映射 added/confirmed/revised/invalidated/strengthened/weakened/conflict/superseded/retraction；HTTP 只做协议转换。1 个 diff 单测 + 1 个 e2e（四端点全链路），全量 110 passed。
- [x] **D5 Research Object 基础导出**：至少 JSON + Markdown，含校验值与 provenance 摘要。
  产出：[packages/application/queries/research_export.py](../../packages/application/queries/research_export.py)（question+claims+evidence+relations+source_versions+provenance，sha256 校验值覆盖载荷、确定性可重导）+ `GET /research/questions/{id}/export?format=json|markdown`。
  结论：同一数据两次导出 content_hash 一致（generated_at 不参与 hash），数据变化 hash 随之变化；Markdown 为同一载荷的人读渲染（renderer 不改语义）。2 个测试（确定性单测 + HTTP e2e），全量 112 passed。
- [x] **D6 领域事件**：append-only outbox/event log 记录 Claim 与 SourceVersion 的关键状态变化（设计文档 §4.7 事件表）。
  结论：随 D1–D3 落地——`research_events` 与聚合变更同事务写入（outbox 规则），`list_unprocessed`/`mark_processed` 消费面就绪；§4.7 的 11 个事件已产出 10 个并有测试（claim_proposed/confirmed/revised/invalidated、relation_recorded、evidence_extracted、source_added、source_version_detected、research_run_completed、job_failed），`RetractionDetected` 随 P1 watch 接入。
- [x] **D7 confirmed 规则落地**：author/PaperMind/user 判断来源区分；无证据输出只能 draft/pending verification。
  结论：随 D1/D3 落地并有测试锁定——`claims.origin` 三分；无证据坐标不得 confirmed（`test_confirm_requires_evidence_and_user`）；papermind 不可自动 confirmed（`test_papermind_claim_defaults_and_cannot_self_confirm`）；author+支持性证据规则自动确认；引用不可核实的抽取结果保持 draft（`test_unverifiable_quote_stays_draft_without_evidence`）。

## Stage E — Phase 4：PM Research Terminal 与 MCP 一等化

阶段出口条件：不打开 Web，也能在 `pm` 终端和确定性命令中完成搜索、查看 Claim/Evidence、比较研究状态、触发处理、查看进度、取消任务和导出。

- [ ] **E1 `PaperMind-Terminal` downstream fork 基线**：独立仓库、pinned 上游 tag、保留 MIT copyright/license notice 与第三方 notices、有序 patch stack（每次 release 记录上游基线与未合并安全修复）、product profile 关闭 coding-oriented 功能；build pruning 先行，稳定前不做 source pruning。
- [ ] **E2 `@papermind/cli` 与 standalone `pm`**：同进程运行裁剪后的 Pi agent core/TUI，加载 PaperMind system prompt、主题与 renderer；`pm` / `pm -p` / 确定性子命令三模式骨架。
- [ ] **E3 远程登录**：`pm login --endpoint`，PaperMind token 与本地模型 provider 凭据分开保存/撤销。
- [ ] **E4 确定性子命令 + `--json`**：查询面优先（papers/questions/claims/evidence/diff/export），稳定退出码，无 ANSI 污染。
- [ ] **E5 capability metadata**：HTTP、Pi tools、CLI commands、MCP tools、Local/Full Web adapters 复用同一 schema/scope/risk/async 语义（设计文档 §5.1/§3.3）。
- [ ] **E6 领域 renderer 与主题**：Paper/Claim/Evidence/Research Diff/Job/Research Pack 卡片，`papermind-dark/light`，非 TTY 退化为 Markdown/plain text。
- [ ] **E7 permission profiles**：默认 research profile；`--workspace`/`--coding` 显式开启；destructive 动作需服务端 policy + 终端确认双重把关。
- [ ] **E8 MCP 远程化**：唯一 transport 为公网 HTTPS Streamable HTTP；OAuth protected resource metadata、token audience/scope 校验；resources 与 tools 划分。
- [ ] **E9 MCP 凭据升级**：静态 token 改为可撤销、可轮换、分 scope 的凭据。
- [ ] **E10 CLI device authorization**：PaperMind 自己签发一次性 device code，浏览器完成上游登录；CLI 只拿 PaperMind token，上游 provider token 不下发。

## Stage F — Phase 5：Local UI 与可选 Full Web 适配

阶段出口条件：`pm ui` 无本地业务后端或数据库即可操作远程 Research State；Full Web 可选启停；同一 Claim 在所有界面中状态、权限和 provenance 一致。

- [ ] **F1 现有 Web route/capability inventory**：逐项标记 retain/merge/local-ui/archive；一次产出，A9 设计⑤与 F5 共同引用；禁止直接批量删除。
- [ ] **F2 共享包提取**：`@papermind/client`（typed HTTPS client + auth types）、`@papermind/presentation`（canonical view models）、`@papermind/ui-core`（React primitives + 领域组件）；不导入服务端 repository、Python handler 或 Pi 私有 session 类型。
- [ ] **F3 `pm ui` loopback bridge**：随机端口绑定 `127.0.0.1`/`::1`、一次性启动 nonce 本地 session、Host/Origin/CSRF 校验、allowlist HTTPS proxy、token 仅存进程内存、退出即销毁。
- [ ] **F4 Local UI 首版五类界面**：PDF/Evidence 并排定位、Claim 工作台、Research Diff、Job Monitor、Research Pack；终端 `open`/`o` 深链与 Local UI 互通。
- [ ] **F5 Full Web 适配 Research State**：ResearchQuestion/Claim/Evidence/History/Diff/Job 可查看、可定位 evidence、可执行授权范围内的修改；删除页面内重复业务编排（按 F1 标记执行）。
- [ ] **F6 Full Web 可选部署**：`--web=full|demo|none` 三 profile；`--web=none` 时不携带/启动 Web；构建产物由 Core 或同一反向代理提供，去常驻前端容器。
- [ ] **F7 surface contract 测试**：每个新 capability 验证 Terminal/Local UI/Full Web/MCP/JSON 五面语义一致（对象 ID、状态机、权限、幂等键、provenance）。

## Stage G — Phase 6：公开 Demo

阶段出口条件：个人站与 Demo 数据完全隔离；Demo 在模型不可用时仍能展示完整预计算流程。

- [ ] **G1 Demo 独立实例**：独立数据库、文件卷、配置与模型额度；取代 2026-05-08 旧 Demo 方案。隔离是实例级的，`--web=demo` 只是页面 profile，不承担隔离职责。
- [ ] **G2 GitHub 登录 + 临时身份**：最小身份映射、TTL 清理、用户/IP/全局三维限额。
- [ ] **G3 三段式演示旅程**：匿名看 Claim/Evidence → 登录看研究状态变化 → `pm login`/`pm demo`/`pm ui --question ...` 复现并导出 Research Pack。

## Stage H — Phase 7：资源与存储验证门

- [ ] **H1 重测资源基线**：对照 A2 记录，验证 Go Core/Python Executor 拆分后的空闲 RSS、冷启动、镜像大小、任务峰值与故障恢复表现。
- [ ] **H2 存储与容量决策记录**：根据单写者约束、并发领取和恢复测试决定个人服务用 SQLite 还是 PostgreSQL，并确定 Executor 资源分组。出口条件：配置有测量证据和独立回滚路径。

## 变更记录

- 2026-09-02：建立路线图；完成 A1 审计。
- 2026-09-02（第二次）：同步设计基线第二版——Pi 从 SDK adapter 改为 downstream fork 策略（A8/E1）、新增 Local PM UI（A9/F3/F4）、Full Web 从瘦身删除改为可选模块（F1/F5/F6）、设计五份变六份（A5–A10）、Phase 0–6 变 0–7（Stage A–H）、Phase 1 出口新增 canonical presentation model（B2）。
- 2026-09-02（第三次）：完成 A3——主用户流程端到端回归测试（tests/test_e2e_main_flow.py，LLM/arXiv/vision 全 fake + tmp SQLite）与 CI 测试 workflow（tests.yml）。
- 2026-09-02（第四次）：完成 A5 设计①（Research State 最小数据契约：7 实体、状态机、事件/outbox、PROV 映射、共存策略），§11 决策点待确认。
- 2026-09-02（第五次）：用户确认设计①全部决策点；完成 D1——数据契约落地为 models/枚举/UUIDv7/migration/仓储，16 个契约测试 + 全量 101 passed。
- 2026-09-02（第六次）：完成 A4 + D2——ingest 同事务建 v1 SourceVersion（9 个入库路径全覆盖）、A4 样本种子（author 即证 + papermind draft 待人工抽检），全量 104 passed。
- 2026-09-02（第七次）：完成 D3——ClaimExtractionService 挂接 deep_dive，ResearchRun 生成待验证 Claim（provenance 完整、引用核实强制、幂等），全量 108 passed。
- 2026-09-02（第八次）：完成 D4——application 层首个模块（四查询）+ 只读 /research/* 路由；同一 Claim 可从 API 追溯到精确证据与 diff，全量 110 passed。
- 2026-09-02（第九次）：完成 D5——Research Object 基础导出（JSON+Markdown，确定性 sha256 校验值，provenance 摘要），全量 112 passed。
- 2026-09-02（第十次）：核对后关闭 D6/D7（实体与规则已随 D1–D3 落地且有测试）——**Stage D（Phase 3）完成**：同一 Claim 可从 API 追溯到精确证据、生成活动与历史版本，无证据的模型输出不进入 confirmed。Phase 3 出口条件达成。
- 2026-09-02（第十一次）：完成 A6 设计②——165 HTTP + 9 MCP + 26 agent 工具全量映射到用例目录与 B2–B7 迁移批次。
- 2026-09-02（第十二次）：完成 A7 设计③——原子 durable execution 协议（四表 schema、状态机、9 个 Task 原子边界、4 个 Workflow 模板、旧机制收敛映射）。
- 2026-09-02（第十三次）：完成 A8 设计④——PM Terminal downstream 架构（fork 基线/patch policy/命令面/permission profiles/renderer/契约测试）。
- 2026-09-02（第十四次）：完成 A9 设计⑤——UI Surface Contract（16 路由 inventory、presentation model、共享包、loopback bridge 契约）。
- 2026-09-02（第十五次）：完成 A10 设计⑥——identity/token flow（三信任域、scope 四值化、设备码规范固化、GitHub 登录、MCP discovery）。**六份设计全部产出**；A2（资源基线）待服务器实测。
- 2026-09-02（第十六次）：完成 B1/B2/B3/B4——application 层骨架 + papers 读路径下沉（返回兼容 e2e）+ 研究状态读取面（随 D4/D5）；全量 113 passed。**Stage B 剩余：B5 MCP 工具改调、B6 agent 工具改调、B7 其余查询与命令面。**
- 2026-09-02（第十七次）：完成 B5——MCP 9 工具改调 application（零 deps 引用，协议字段兼容），全量 119 passed。
- 2026-09-02（第十八次）：B6 第一批——agent 工具 read/batch/search 三组共 10 个改调 application（commands/pipelines、commands/batch、queries/papers 扩展），全量 123 passed。
- 2026-09-02（第十九次）：B6 第二、三批——ask/citation_tree/timeline/suggest_keywords + reasoning/figures/writing/system/topics/wiki_brief 共 13 个改调 application（新增 queries：ask/graph/analysis/system/topics；commands：brief/wiki）；仅余 ingest.py。全量 123 passed。
- 2026-09-02（第二十次）：B6 完成——ingest 工具业务下沉到 commands/ingest（handler 只桥接进度），并修复存量 bug（search_arxiv 误用 metadata_json）；**24 个 agent 工具全部经 application 层**。全量 125 passed。
- 2026-09-02（第二十一次）：完成 B7——content/topics/jobs/pipelines/graph 共约 31 条 HTTP 查询全部下沉 application（queries：content 扩展/actions 新建/topics 扩展/tasks 扩展/graph 查询族）；HTTP 形状逐处兼容。全量 126 passed。
- 2026-09-02（第二十二次）：完成 B8——四批命令面迁移（papers/topics/ingest/pipelines/graph/content/jobs 共约 30 条写路径），长任务入口统一在 application command 提交（tracker 过渡）；修掉两个迁移引入 bug。**Stage B（Phase 1）完成**。全量 127 passed。
- 2026-09-02（第二十三次）：处理 REVIEW 六项（wheel 打包/ingest 失败语义/query-command 边界+架构守卫/有界执行器/伪进度/index 字段），全量 132 passed。
- 2026-09-02（第二十四次）：完成 C1（Python 侧）——batch consumer 移出 API 进程（worker 接管 + poll_once 单步化），根修 DetachedInstance 存量 bug；Go Core 入口切换待 C0。全量 136 passed。
- 2026-09-02（第二十五次）：完成 C0——Go Core 骨架（core/ module：协议信封 v1 + 六动作 + 能力注册 + 内存队列/lease；7 个 Go 测试）+ Python executor client（5 个契约测试）+ CI go-core job。全量 141 passed。
- 2026-09-02（第二十六次）：完成 C2——durable execution 四表 schema + durable 仓储（幂等/lease/fencing/收敛）+ 9 个契约测试。全量 150 passed。
- 2026-09-03：完成 C3——12 个任务入口接 durable 桥接（权威切换到 job store），统一观察面端点（/jobs、/jobs/{id}、/tasks/* durability 优先）。全量 154 passed + Go 7 passed。
- 2026-09-03：完成 C4——原子 Task 能力注册表（12 spec + 不变量测试），Start* 命令改读注册表。全量 179 passed + Go 7 passed。
- 2026-09-03：完成 C5——代码化 Workflow 模板（4 模板注册 + 幂等展开 + fan-out/依赖/条件分支），6 个测试。全量 185 passed + Go 7 passed。
- 2026-09-03：完成 C6——Go 控制面（任务提交/观察端点 + Reconciler 过期 lease 回收），Go 测试 10 个。全量 185 passed + Go 10 passed。
- 2026-09-03：完成 C7——Python Executor 运行时（claim/handler/complete/fail + 心跳续约 + 协作取消 + drain），5 个 hermetic 测试。全量 190 passed + Go 10 passed。
- 2026-09-02（第二十三次）：确认 **Go Core + Python research executors** 为目标架构，不再把 Go 留到 Stage H 决策；Stage C 新增 C0 并改为由 Go 承接任务与领域权威状态，Python 只通过协议执行原子 Attempt，Stage H 改为资源/存储验证门。
