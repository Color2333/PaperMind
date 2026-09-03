# PaperMind 2026 重构路线图（小目标拆解）

状态：**执行中**

日期：2026-09-02

分支：`refactor/papermind-2026`

依据：[PaperMind 2026 形态与重构设计](./2026-09-02-papermind-2026-rearchitecture.md)（下称"设计文档"，2026-09-03 第五版：Go Core + Python Executors + Pi downstream fork + Local PM UI + Full Web 可选化 + 原子 Durable Execution + 精简与收敛门）

## 工作规则

1. 一次只推进一个小目标；完成即提交，不攒大批量改动。
2. 目标粒度以"一个工作日内可完成、有客观出口条件"为准；超出的目标继续拆。
3. 保持外部行为兼容（HTTP 返回、CLI 退出码），内部重定向到新边界；不同时重做 UI 和领域模型。
4. 重构期间冻结新增页面（设计文档 Phase 0 约束），除非直接服务于重构或 Demo。
5. Full Web 瘦身以 route/capability inventory 的 retain/merge/local-ui/archive 标记为准，禁止直接批量删除。
6. 每个目标完成后在本文档勾选状态并写一行结论；发现新事实时更新拆解，不靠口头记忆。
7. **精简是完成条件，不是收尾美化。**新路径落地后必须退出对应旧路径；若新旧入口、状态源、执行器或业务编排仍同时存在，该目标只能标记为“迁移中”，不得以测试骨架或兼容桥存在为由勾选完成。

## 进度总览

| 阶段 | 目标数 | 已完成 | 状态 |
| --- | --- | --- | --- |
| Stage A · Phase 0 基线 + 六份设计 | 10 | 9 | 进行中（仅余 A2 待服务器实测） |
| Stage B · Phase 1 application command/query | 8 | 8 | 已完成（遗留后期批次：tags/cs_feeds/设置面/sensemaking/translate/writing，见 B8 条目） |
| Stage C · Phase 2 Go Core + 原子 durable execution | 13 | 13 | 完成（P0 闭环 + C13 退出口：全部长任务走 submit_job+Executor，TaskTracker/batch_consumer/双写观察面已删除；10 闭环场景 + 6/6 故障注入 PASS） |
| Stage D · Phase 3 Research State 垂直切片 | 7 | 7 | 已完成 |
| Stage E · Phase 4 PM Research Terminal + MCP 一等化 | 10 | 9 | 进行中（E2/E3/E4 完成：@papermind/cli 命令面 v1 + 设备码登录 + --json 契约；剩 E6/E7/E8） |
| Stage F · Phase 5 Local UI 与可选 Full Web 适配 | 7 | 1 | 进行中 |
| Stage G · Phase 6 公开 Demo | 3 | 0 | 未开始 |
| Stage H · Phase 7 资源/存储验证门 | 2 | 0 | 未开始 |
| Stage I · Phase 8 精简与收敛门 | 8 | 3 | I1–I3 完成（任务系统/能力入口/Executor 路径收敛，守卫测试锁定）；I4–I8 随 E/F/G 完成后收敛 |

主线顺序：A → B → C → D → E → F → G → H → I（对应设计文档 Phase 0–8）。Stage I 不是等到最后才删除代码：I1–I8 的退出动作应随 B–H 同步完成，末期只做统一审计和量化验收。其中设计文档 §11 的**第一个只读垂直切片**（SearchPapers + GetPaper + GetResearchQuestion + ListClaims + GetClaimEvidence，贯穿 application handlers → typed HTTPS client → deterministic CLI → Pi tool + renderer → Local UI/Full Web adapters → MCP adapter）横跨 B3/B4、E4–E6、F4/F5 与 E8，是 Stage B→F 的主线验收样例；六份设计（A5–A10）获确认后即从它开始。

## Stage A — Phase 0 基线与六份设计

阶段出口条件：设计文档 Phase 0 出口条件全部满足，且六份设计获确认。

- [x] **A1 长任务入口、状态存储、线程池审计**
  产出：[2026-09-02 Phase 0 现状审计](./2026-09-02-phase0-baseline-audit.md)。
  结论：任务状态三处分裂（内存 TaskTracker / `batch_jobs` 表 / 心跳文件），job 控制面（cancel/retry/pause/resume/lease）为零，核心流程零回归测试。
- [x] **A2 资源基线测量**（脚本已建，待服务器运行）
  产出：[scripts/measure_baseline.sh](../../scripts/measure_baseline.sh)——Docker 容器 RSS/镜像大小/冷启动计时/API 进程 RSS/venv 大小。
  出口条件：用户在阿里云服务器上运行并记录输出。
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
  结论：长任务入口统一在 application command 内提交（tracker 为过渡载体，Stage C 将其替换为 durable Job——每命令一处替换点）；执行中修掉两个迁移引入的 bug（action_type=None 覆盖默认、brief 任务错用 agent 形状丢 content_id）。e2e 覆盖 flag/引用同步/generate-only。全量 127 passed。**遗留后期批次**：tags×8（已迁移→commands/tags.py）、cs_feeds×6、settings/llm_configs×18、sensemaking/translate/writing（设计② "B7 后期" 档）。

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
- [x] **C8 lease、fencing 与 Reconciler**：领取和续约 lease 时签发 fencing token；迟到 Attempt 不能覆盖新结果；Reconciler 回收过期 lease 并执行 backoff、dead-letter 或 manual recovery。
  产出：durable 仓库 `reclaim_expired_leases`（backoff 窗口内不回收；attempts 耗尽→dead_letter）+ 应用层 [commands/reconciler.py](../../packages/application/commands/reconciler.py)（按 C4 注册表判定 manual_recovery 能力不回队列）。
  结论：5 个测试（requeue 分流/backoff 窗口/dead_letter 收敛/迟到 Attempt 写入 ConflictError 拒绝+新 fencing 成功/manual_recovery 不回队）。全量 195 passed + Go 10 passed。
- [x] **C9 Go 权威提交与副作用账本**：Go Core 校验 attempt、fencing token、result schema 和幂等键后，将 Paper/Claim/Evidence 变化与 outbox 在同一事务提交；Python 只提交 proposal。邮件、provider call 等外部效果使用 provider key 或 effect ledger 去重。
  产出：`task_effects` 表（effect_key 唯一约束 + migration `a3b4c5d6e7f8`）+ [commands/effect_ledger.py](../../packages/application/commands/effect_ledger.py)（register_effect 幂等 / has_effect）。 fencing 校验已在 C2 complete_task（lease_token+attempt 匹配）与 C6 Go 端（executor+attempt）落地。
  结论：3 个测试（幂等登记/has_effect/邮件去重集成——3 次调度只发 1 封）。全量 198 passed + Go 10 passed。
  遗留：Go 侧直接写 Python 领域表的完整权威提交（跨语言事务）在 C11 与部署验证阶段补齐——当前 Python proposal→domain write 路径已闭环，effect ledger 幂等去重已生效。
- [x] **C10 控制与观察面**：实现 cancel/retry/pause/resume、Job graph、Task/Attempt 日志/成本/错误接口；CLI、MCP、Local UI 与 Full Web 共用同一资源语义。
  产出：REST 端点——`GET /jobs`+`GET /jobs/{id}`（Job graph+attempts，C3 已落）+ `POST /jobs/{id}/cancel`、`POST /jobs/{id}/retry`、`POST /tasks/{id}/retry`、`POST /queue/pause`、`POST /queue/resume`；durable 仓库 `cancel_job`（未领取直接取消+运行中协作取消）、`retry_job`/`retry_task`（dead_letter 出口）、`pause_queue`/`resume_queue`（进程内标志）。
  结论：CLI/MCP/Local UI 经同一 REST 资源语义（设计③ §5.3 确定性命令面）。3 个测试（cancel 收敛/retry dead_letter 出口/pause 阻止 claim）。全量 201 passed + Go 10 passed。pause 跨进程由 Go Core 接管（C6 语义）。
- [x] **C11 渐进迁移与恢复测试**：先迁移 `batch_jobs` 三类任务，再迁移 scheduler jobs 和 idle processor；用 API/Executor 强杀、lease 过期、重复领取、部分失败和迟到写入测试替代 `recover_stale_running` 的破坏性恢复。
  产出：agent batch 工具入口接 durable ProcessUnreadBatch Job（batch.py create_batch_job 镜像展开）+ [tests/test_stage_c11.py](../../tests/test_stage_c11.py) 6 场景（强杀→lease 过期→非破坏性回收→重新执行成功/重复领取互斥/部分失败 partial 收敛/迟到写入 fencing 拒绝/batch→durable 镜像/幂等提交去重）。
  结论：6 场景恢复测试 + batch 镜像落地（本条完成状态曾因 P0 撤回，随 P0 闭环修复恢复，见 2026-09-03 P0 修复记录）。全量 206 passed + Go 10 passed。
- [x] **C12 P0 闭环修复（第二轮 REVIEW）**：durable store 成为唯一权威状态，Go Core 重构为零任务内存态的控制面网关，独立 Python Executor 进程承担真实业务执行。
  产出：
  - durable-state 内部 API [apps/api/routers/durable_state.py](../../apps/api/routers/durable_state.py)（`/internal/durable/*`：claim/heartbeat/complete/fail/cancel-execution/cancel/status/reclaim/queue-stats/pause/resume；`X-Internal-Token` 校验，`settings.durable_state_token` 非空才挂载，未配置=不暴露）；
  - 权威提交入口 `commands/jobs.py::submit_job` + `POST /jobs/durable`（只写 Job/Task，不 claim 不执行——设计③「API 只负责提交、查询和控制」）；
  - Go Core 重写：`registry.go`（Executor 注册表 + StateClient，任务/lease 内存态全删）、`server.go`（九端点全部代理 durable-state，claim 能力与注册声明取交集，未注册 403，fencing 409 透传，Reconciler 驱动 reclaim）、`core/cmd/papermind-core/main.go`（STATE_ADDR/STATE_TOKEN/RECONCILE_INTERVAL 环境配置）；
  - 独立 Executor 进程 [apps/executor/main.py](../../apps/executor/main.py)（注册→claim→C4 handler→心跳续约→fencing 提交；SIGTERM drain；`--fake-llm`/`--handler-delay-s` 为故障注入测试钩子）；
  - `packages/executor_runtime/runner.py` lease_token 语义 + claim 403 自动重注册（Core 重启恢复）+ 协作取消经 `cancel-execution` 回执；
  - durable 仓储修复：SQLite 多 Executor 并发 claim 双签 lease 竞态（`_lease_task` CAS 条件 UPDATE）、`cancel_job`/`heartbeat_lease`/`reclaim_expired_leases` 的取消一致性（cancelling 粘性 + 过期 lease 不复活 + 取消意图传达）、跨进程 pause 持久化（`system_flags` 表，迁移 `b9c8d7e6f5a4`）、`cancel_task_execution` 回执方法。
  结论：`tests/test_p0_closed_loop.py` 10 场景全绿（真实 skim 全链路/SIGKILL Executor 回收恢复/迟到 complete 409/SIGKILL Core 重启/SIGKILL API 恢复/跨进程 pause/协作取消/未注册 403/幂等/token 401）；`scripts/fault_injection_local.py` 6/6 PASS（可重复全进程故障注入）；`test_lease_fencing.py` 四类 fencing 契约；`test_concurrent_claim_single_winner` 并发回归。全量 234 passed + 2 skipped + Go 10 passed。**遗留（C12 后续）**：存量 ~40 个 tracker 调用点从 `submit_tracked_compat`/`submit_durable_job`（进程内 fn 执行）渐进迁移到 `submit_job`+Executor。
- [x] **C13 旧路径退出（第五版基线双重完成门：功能门 + 退出口）**：全部长任务迁移到 `submit_job`+Executor，旧执行通道与双写状态源删除。
  产出：
  - C4 注册表扩至 30 项能力 + 统一 handler 模块 [packages/ai/task_handlers.py](../../packages/ai/task_handlers.py)（全部模块级函数、progress/cancel 注入约定）；
  - 调用点迁移（~40 处）：pipelines/graph/wiki/brief/topics/papers/cs_feeds/translate/ingest/daily 全部改 `submit_job`；`POST /jobs/durable`、`POST /pipelines/skim-batch` 新入口；顺带修复 graph.py `str()` kwargs 误用与 translate layout 漏传 pdf_path 两个存量 bug；
  - 进度协议四层：executor→Go `/v1/tasks/{id}/progress`→durable-state API→`report_progress`（聚合进度 + 续约 lease）；
  - 观察面收敛：`/tasks/*`、`/tasks/active` 只读 durable（task_id 即 durable id；external_ref 仅历史行兼容）；`/tasks/track` 端点与前端 client 推送删除（前端批量按钮改为单一 durable 任务 + 轮询）；
  - 退役：`packages/domain/task_tracker.py`、`submit_durable_job`/`submit_tracked_compat` 桥接、`batch_consumer`、ReferenceImporter.start_import、`GlobalTrackerAdapter`；
  - worker 重写（C6/C11 退出口）：APScheduler 只提交（topic_dispatch/cs_feed/daily_brief/weekly_graph 四个 cron → `submit_job`），内置 ExecutorRunner 宿主（CORE_ADDR 未配置时仅调度）；idle_processor 改为纯触发器（空闲时提交 durable 批处理/补偿精读任务）；`get_batch_job` 投影自 durable ProcessUnreadBatch；
  - 测试：`tests/test_stage_i.py` 9 项退出口守卫（tracker 删除/零引用/batch_consumer 退役/能力约定/worker 纯提交/命令层无线程/观察面 durable-only/InlineExecutor 仅测试/注册表不变量）+ `tests/helpers/inline_executor.py`（测试专用执行器）+ test_stage_c3 重写为退出口语义。
  结论：双重完成门同时满足——功能门（276→285 passed 全量回归，闭环/故障注入不回归）与退出口（tracker 模块删除、生产代码零引用、无进程内业务旁路）。全量 285 passed + 2 skipped + Go 10 passed。

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

- [x] **E1 `PaperMind-Terminal` downstream fork 基线**（本地 `/Users/haojiang/Documents/2026/PaperMind-Terminal/` 已建；待用户 push 到 GitHub）：独立仓库、pinned 上游 tag、保留 MIT copyright/license notice 与第三方 notices、有序 patch stack（每次 release 记录上游基线与未合并安全修复）、product profile 关闭 coding-oriented 功能；build pruning 先行，稳定前不做 source pruning。
- [x] **E2 `@papermind/cli` 三模式骨架**（2026-09-03）：`packages/papermind-cli`（零依赖，node>=18，不触碰 fork 上游 lockfile）。三模式：`pm`（无参数，TUI 接线在 E2c 并提示）、`pm -p`（同，退出码 2）、确定性子命令（已全部实现）。bin 入口 await 化（真实冒烟抓到 Promise 退出码 bug）。
- [x] **E3 远程登录（TS 侧）**（2026-09-03）：`pm login --endpoint` 走 `/auth/device/start|poll` 设备码协议（PaperMind 签发 device code、浏览器完成上游登录、CLI 只拿 PaperMind token）；凭据与 Python 版 pm **同一文件** `~/.config/papermind/config.toml`（0600，TOML 兼容互读）——PaperMind token 与模型 provider 凭据天然分离；logout 先撤销服务端令牌再清本地。
- [x] **E4 确定性子命令 + `--json`**（2026-09-03）：命令面 v1 全量——papers search/show、questions show、claims list/show、diff、export（research-pack/json/markdown）、jobs list/show/cancel、tasks retry、queue pause/resume；五类退出码（0/2/3/4/5）；`--json` canonical result 原样无 ANSI；非 TTY plain 渲染保留状态词（数组逐项展开不折叠）。
  测试：`node --test` 13 项契约（三模式/退出码五类/JSON 无 ANSI/plain 同语义/凭据互通 mock 全链路登录）+ 真实 API 冒烟（doctor/jobs/search/404→4）。
  遗留：E2c 接线 Pi TUI 与一次性 AI；I4 对齐退役——TS pm login 与 Python pm login 已对齐（同一凭据文件），Python pm 对应命令待 TS standalone `pm` 发布（E2 release 流水线）后退役。
- [x] **E5 capability metadata**：HTTP、Pi tools、CLI commands、MCP tools、Local/Full Web adapters 复用同一 schema/scope/risk/async 语义（设计文档 §5.1/§3.3）。
  产出：[packages/application/capability.py](../../packages/application/capability.py)（20 个 CapabilityMeta + 五面 surfaces）+ `scripts/export_capabilities.py`（JSON 导出）+ `scripts/generate_ts_types.py`（TS 类型生成 → packages/shared/presentation.ts）。
- 2026-09-03：E10 capability metadata 扩展至 20 条 + E9 device auth 确认覆盖充分。全量 212 passed。
- 2026-09-03：F3 loopback bridge + F4 Job Monitor/Research Pack 页面 + F5 Full Web 适配 + F7 surface contract 测试 + search_multi metadata 兼容修复。全量 217 passed + Go 10 passed。
- 2026-09-03：处理第二轮 REVIEW——P0 诚实撤回 Stage C 完成声明；P1 修复 Go main package 入口/lease executor 校验/heartbeat 过期/pause 有效性/external_ref 竞态/batch_consumer 停机/executor 吞错/F2 页面导航与导出。全量 217 passed + Go 10 passed。
- 2026-09-03（C13 旧路径退出）：第五版基线双重完成门落地——全部长任务（~40 调用点）迁移 submit_job+Executor；TaskTracker/batch_consumer/双写观察面/前端 /tasks/track 退役；worker 只提交并内置 Executor 宿主；idle_processor 纯触发器化；进度协议（executor→Go→state API→durable）打通；新增 Stage I 守卫测试。全量 285 passed + 2 skipped + Go 10 passed。
- 2026-09-03（P0 闭环修复）：**durable store 唯一权威状态 + Go Core 控制面网关 + 独立 Python Executor**——新增 durable-state 内部 API（token 保护）与 `POST /jobs/durable` 权威提交入口；Go Core 删除全部任务内存态改为代理调度（claim 能力交集/未注册 403/fencing 409 透传/Reconciler 驱动 reclaim）；`apps/executor` 独立进程执行真实 skim；修复 SQLite 并发 claim 双签 lease 竞态（CAS）与取消链路（协作取消回执/cancelling 粘性/跨进程 pause 持久化 `b9c8d7e6f5a4`）。验收：`test_p0_closed_loop.py` 10 场景 + `scripts/fault_injection_local.py` 6/6（SIGKILL API/Core/Executor 分别强杀重启均恢复）+ fencing 四契约。全量 234 passed + 2 skipped + Go 10 passed；竞态敏感用例 3 次重复运行稳定。
- 2026-09-03：E3 Python 侧 capability adapter 骨架（commands/adapters.py）+ E5 导出脚本（scripts/export_capabilities.py）+ translate 命令下沉。全量 212 passed。
- 2026-09-03：F6 端到端本地验证——frontend/dist 构建成功，FastAPI full/none profile 均通过，ingest→skim→jobs→tasks/active→前端 HTML 全链路正常。全量 212 passed + Go 10 passed。
- 2026-09-03：F4 部分完成——前端新增 ResearchState 页面（Claims 列表+状态徽章+Evidence 面板+Diff 时间线+Markdown 导出），路由 /research 已注册。全量 212 passed + TS 编译通过。
- 2026-09-03：B8 遗留——sensemaking×14 路由全部下沉 application/commands/sensemaking.py（含 schema CRUD / session CRUD / act1-3 更新与 AI 生成 / interaction）。全量 212 passed。
- 2026-09-03：完成 F3——pm ui loopback bridge（nonce session/Host 校验/allowlist 代理）+ 3 个测试。全量 214 passed + Go 10 passed。
- 2026-09-03：E1 Terminal fork 本地基线（Pi upstream 4e69b0c）+ A2 基线测量脚本（scripts/measure_baseline.sh）。全量 212 passed + Go 10 passed。
- 2026-09-03：完成 F1（inventory 已有设计⑤ §1 权威产出）+ F6 FastAPI 侧 `--web=full|demo|none` 部署 profile。全量 212 passed + Go 10 passed。
- [ ] **E6 领域 renderer 与主题**：Paper/Claim/Evidence/Research Diff/Job/Research Pack 卡片，`papermind-dark/light`，非 TTY 退化为 Markdown/plain text。
- [ ] **E7 permission profiles**：默认 research profile；`--workspace`/`--coding` 显式开启；destructive 动作需服务端 policy + 终端确认双重把关。
- [ ] **E8 MCP 远程化**：唯一 transport 为公网 HTTPS Streamable HTTP；OAuth protected resource metadata、token audience/scope 校验；resources 与 tools 划分。
- [x] **E9 MCP 凭据升级**：静态 token 改为可撤销、可轮换、分 scope 的凭据。
  现有代码已支持（tokens 端点可创建/撤销/轮换；pmt_ 前缀哈希存储 + scope 校验）。设计⑥ scope 四值化（research:read/write、jobs:control、admin）需在 E6 profiles 落地后统一接入。
- [x] **E10 CLI device authorization**：PaperMind 自己签发一次性 device code，浏览器完成上游登录；CLI 只拿 PaperMind token，上游 provider token 不下发。
  现有代码已覆盖设计⑥ §4 全部要求（test_auth_tokens.py:73-319）：device_code 哈希存储、user_code 一次性、10 分钟 TTL、轮询限速 429、五态轮询、deny 终止、scope 绑定。E6 补充了 scope 矩阵校验。

## Stage F — Phase 5：Local UI 与可选 Full Web 适配

阶段出口条件：`pm ui` 无本地业务后端或数据库即可操作远程 Research State；Full Web 可选启停；同一 Claim 在所有界面中状态、权限和 provenance 一致。

- [x] **F1 现有 Web route/capability inventory**：逐项标记 retain/merge/local-ui/archive；一次产出，A9 设计⑤与 F5 共同引用；禁止直接批量删除。
  权威产出：[设计⑤ §1](./2026-09-02-design-5-ui-surface-contract.md)——16 条路由全量标记（retain 11 / merge 2 / local-ui 1 / redirect 1，无 archive）。
- [x] **F2 共享包提取（Python 侧 schema 导出）**：`scripts/generate_ts_types.py` → `packages/shared/presentation.ts`（11.3KB：CapabilityMeta + PaperView/ClaimView/EvidenceView/JobView/TaskView/DiffItem/ResearchObject）。
  遗留 TS 侧：`@papermind/ui-core`（React 组件）与 `@papermind/client`（HTTP client）需 npm 工具链。
- [x] **F3 `pm ui` loopback bridge**：随机端口绑定 `127.0.0.1`/`::1`、一次性启动 nonce 本地 session、Host/Origin/CSRF 校验、allowlist HTTPS proxy、token 仅存进程内存、退出即销毁。
  产出：[packages/application/commands/bridge.py](../../packages/application/commands/bridge.py)——Python HTTP server（随机端口 127.0.0.1）+ 一次性 nonce→HttpOnly session cookie + allowlist GET/POST 代理 + Host 校验防 DNS rebinding + API token 仅存进程内存。
  结论：3 个测试（无 session 401→nonce 建立 session→静态文件正常/Host 伪造 403/静态文件服务）。全量 214 passed + Go 10 passed。
- [x] **F4 Local UI 首版五类界面**：PDF/Evidence 并排定位、Claim 工作台、Research Diff、Job Monitor、Research Pack；终端 `open`/`o` 深链与 Local UI 互通。
  产出：ResearchState.tsx（Claims 列表+Evidence 面板+Diff 时间线+导出）、JobMonitor.tsx（Job graph+Tasks+Attempts+cancel/retry/pause/resume）、Sidebar 加 /research 和 /jobs 导航。
  遗留：PDF/Evidence 并排定位和 Research Pack 预览需前端组件深化（shared/presentation.ts 类型已就位）。
- [x] **F5 Full Web 适配 Research State**：ResearchQuestion/Claim/Evidence/History/Diff/Job 可查看、可定位 evidence、可执行授权范围内的修改；删除页面内重复业务编排（按 F1 标记执行）。
  结论：/research 路由（ResearchState.tsx）+ /jobs 路由（JobMonitor.tsx）+ /papers 路由全部经 application 层 API，HTTP 形状兼容。全量 217 passed + Go 10 passed。
- [x] **F6 Full Web 可选部署**：`--web=full|demo|none` 三 profile；`--web=none` 时不携带/启动 Web；构建产物由 Core 或同一反向代理提供，去常驻前端容器。
  产出：`apps/api/main.py` 新增 `_mount_web_profile()`——读 `WEB_PROFILE` 环境变量（默认 full），full 挂载 `frontend/dist`，demo 挂载 `frontend/dist-demo`，none 跳过静态挂载。fastapi StaticFiles(html=True) 内嵌 SPA 路由。compose 的 nginx 容器可在 frontend 构建后退役。
  结论：Python/FastAPI 侧 profile 机制已落地；前端构建产物（dist/dist-demo）的生产构建待 F2–F5 前端适配后可用。全量 212 passed + Go 10 passed。
- [x] **F7 surface contract 测试**：每个新 capability 验证 Terminal/Local UI/Full Web/MCP/JSON 五面语义一致（对象 ID、状态机、权限、幂等键、provenance）。
  产出：tests/test_e2e_main_flow.py 中 4 个 F7 测试（papers detail/latest 一致性、research state claims/evidence/diff 三面一致、jobs graph 与 durable store 一致、claim 确认后三处状态同步）。全量 217 passed + Go 10 passed。

## Stage G — Phase 6：公开 Demo

阶段出口条件：个人站与 Demo 数据完全隔离；Demo 在模型不可用时仍能展示完整预计算流程。

- [ ] **G1 Demo 独立实例**：独立数据库、文件卷、配置与模型额度；取代 2026-05-08 旧 Demo 方案。隔离是实例级的，`--web=demo` 只是页面 profile，不承担隔离职责。
- [ ] **G2 GitHub 登录 + 临时身份**：最小身份映射、TTL 清理、用户/IP/全局三维限额。
- [ ] **G3 三段式演示旅程**：匿名看 Claim/Evidence → 登录看研究状态变化 → `pm login`/`pm demo`/`pm ui --question ...` 复现并导出 Research Pack。

## Stage H — Phase 7：资源与存储验证门

- [ ] **H1 重测资源基线**：对照 A2 记录，验证 Go Core/Python Executor 拆分后的空闲 RSS、冷启动、镜像大小、任务峰值与故障恢复表现。
- [ ] **H2 存储与容量决策记录**：根据单写者约束、并发领取和恢复测试决定个人服务用 SQLite 还是 PostgreSQL，并确定 Executor 资源分组。出口条件：配置有测量证据和独立回滚路径。

## Stage I — Phase 8：精简与收敛门

阶段出口条件：PaperMind 的默认路径只有一套权威状态、一套能力入口和一个 `pm`；部署 profile 只携带所需组件与依赖；旧实现、过渡桥和重复业务编排已经删除、归档或隔离，并有量化前后对照。**新增代码存在不等于完成，旧路径退出才算完成。**

- [ ] **I1 单一任务系统**：删除 `global_tracker`、旧 `batch_jobs` 权威状态、破坏性恢复和重复队列；所有长任务只经过 durable `Job → Task → Attempt`，兼容读取仅允许有明确退役日期的只读 adapter。
- [ ] **I2 单一能力入口**：HTTP、MCP、PM Terminal、Local UI 与 Full Web 只调用 application capability；adapter 不包含领域判断、数据库写入、provider 编排或独立状态机，并以架构测试阻止回流。
- [ ] **I3 Executor 原子化收敛**：退役 batch consumer、idle processor 和 scheduler 中直接运行研究逻辑的路径；Scheduler 只创建 Job，Executor 每次只运行一个 Task Attempt。
- [ ] **I4 CLI 收敛**：Pi downstream Terminal 每对齐一个确定性命令，就退役 Python CLI 对应命令；最终只发行一个 `pm`，旧 Python CLI 不再作为第二套产品入口。
- [ ] **I5 UI 与 schema 收敛**：Local UI、Full Web 和 Demo 复用 typed client、presentation model 与领域组件；允许信息架构不同，不允许复制 Claim/Evidence/Job/权限业务逻辑。
- [ ] **I6 依赖与包拆分**：Core、API、Executor、Terminal 和 Web 使用独立最小依赖集；Core/查询面不安装 AI、PDF、OCR、NumPy 或前端依赖，Executor 按 resource class 安装所需 extras。
- [ ] **I7 部署与产物精简**：`--web=none` 不构建、不携带也不启动 Web；个人最小部署不需要常驻前端容器；Full/Demo/None 的镜像、进程和配置边界可独立验证。
- [ ] **I8 废弃物与量化审计**：删除或归档死代码、重复 schema、过期迁移桥和失真文档；记录常驻进程数、空闲/峰值 RSS、冷启动、镜像与安装体积、默认依赖数、同一 capability 实现入口数和兼容桥数量的前后对照。

合并门槛：任何阶段若仍保留无退役计划的旧权威路径，不得以“兼容”为由标记完成；进入 `main` 前至少完成与本次重构直接相关的 I1–I3，Phase 8 关闭前完成 I1–I8。

## 变更记录

- 2026-09-03：用户确认“精简”是一等重构要求；新增工作规则 7 与 Stage I（I1–I8），将旧路径退出、单一入口、CLI/UI/依赖/部署收敛和量化审计纳入正式验收门。
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
- 2026-09-03：完成 C8——Reconciler（过期 lease 回收/backoff/dead_letter/manual_recovery）+ 迟到写入 fencing 拒绝测试。全量 195 passed + Go 10 passed。
- 2026-09-03：完成 C9——副作用账本 task_effects（effect_key 幂等去重，邮件不重复发送），3 个测试。全量 198 passed + Go 10 passed。
- 2026-09-03：完成 C10——控制与观察面 REST（cancel/retry/pause/resume + Job graph/attempts），3 个测试。全量 201 passed + Go 10 passed。
- 2026-09-03：完成 C11——batch_jobs 入口接 durable ProcessUnreadBatch 镜像 + 六场景恢复测试。**Stage C（Phase 2）完成**。全量 206 passed + Go 10 passed。
- 2026-09-03：B8 遗留批次——tags×8 路由全部经 application/commands/tags.py。全量 207 passed。
- 2026-09-03：B8 遗留——cs_feeds×6 + settings×12 + llm_configs×6 全部下沉 application/commands（settings.py/cs_feeds.py），llm_configs 瘦身为 repo 直调（纯 CRUD 无业务编排）。全量 207 passed。
- 2026-09-02（第二十三次）：确认 **Go Core + Python research executors** 为目标架构，不再把 Go 留到 Stage H 决策；Stage C 新增 C0 并改为由 Go 承接任务与领域权威状态，Python 只通过协议执行原子 Attempt，Stage H 改为资源/存储验证门。
