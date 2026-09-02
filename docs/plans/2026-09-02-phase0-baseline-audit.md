# Phase 0 现状审计：长任务入口、状态存储与执行原语

状态：**已完成**（路线图目标 A1）

日期：2026-09-02

依据：[PaperMind 2026 形态与重构设计](./2026-09-02-papermind-2026-rearchitecture.md) Phase 0 第 2 项"列出所有长任务入口、状态存储和线程池"。

所有行号基于本审计当日 `main`（`23f3c2b`）快照。

## TL;DR

1. **任务状态三处分裂**：进程内 `TaskTracker`（10 分钟 TTL、重启即丢）、`batch_jobs` 表（仅 3 种 job kind，且只被 API 进程消费）、心跳/状态文件。没有统一持久 job store。
2. **长任务入口有 6 类并存的执行原语**：tracker 后台裸线程、FastAPI BackgroundTasks、请求线程内同步跑完、APScheduler、API lifespan 内 batch consumer 线程、MCP/agent 工具直调。执行原语无统一抽象。
3. **job 控制面为零**：没有任何 cancel/retry/pause/resume 端点；取消仅翻转标志不中断线程；崩溃恢复是破坏性的（running 一律置 failed）；无 lease、无 per-job 超时、无幂等。
4. **核心用户流程零回归测试**：导入 → skim/deep read → ask → brief 无任何 pytest/e2e 覆盖。
5. **进程职责交错**：`batch_jobs` 队列 worker 不消费（API 进程消费）；定时任务只有 worker 跑。两进程不能互相接管任务。

## 0. 部署与依赖配置事实

- backend 与 worker 共用同一镜像 `Dockerfile.backend`（[docker-compose.yml:17-93](../../docker-compose.yml)），镜像同时携带核心、LLM、PDF、graph extras（[pyproject.toml:32-47](../../pyproject.toml)，graph extras = numpy/scikit-learn/umap-learn）。
- SQLite 配置下 compose 仍拉起 PostgreSQL 占位容器（docker-compose.yml:38-42、99-100 注释自述）。
- backend/worker 各预留 512 MB、上限 2 GB（docker-compose.yml:49-56、86-93）；前端 nginx 容器上限 256 MB（122-143）。
- worker 命令 `python -m apps.worker.main`（docker-compose.yml:66），显式禁用 healthcheck（84-85）。

## 1. 长任务入口

### 1.1 FastAPI 路由 → `global_tracker.submit`（后台裸线程，立即返回 task_id）

| 路由 | 位置 | 执行内容 |
| --- | --- | --- |
| POST `/pipelines/skim/{paper_id}` | apps/api/routers/pipelines.py:25-41 | `pipelines.skim` |
| POST `/pipelines/deep/{paper_id}` | apps/api/routers/pipelines.py:44-60 | `pipelines.deep_dive` |
| POST `/pipelines/embed/{paper_id}` | apps/api/routers/pipelines.py:63-79 | `pipelines.embed_paper` |
| POST `/citations/sync/incremental` | apps/api/routers/graph.py:22-41 | `graph_service.sync_incremental` |
| POST `/citations/sync/topic/{topic_id}` | apps/api/routers/graph.py:44-75 | 按 topic 同步引用 |
| POST `/citations/sync/{paper_id}` | apps/api/routers/graph.py:78-97 | 按 paper 同步引用 |
| POST `/topics/{topic_id}/fetch` | apps/api/routers/topics.py:192-228 | `run_topic_ingest`（抓取 + 并行 skim/embed + 限额精读） |
| POST `/ingest/references` | apps/api/routers/topics.py:306-318 | `ReferenceImporter.start_import`（reference_import.py:49-74 提交 tracker） |
| POST `/papers/{paper_id}/figures/analyze` | apps/api/routers/papers.py:486-548 | 图表分析 |
| POST `/tasks/wiki/topic` | apps/api/routers/content.py:88-102 | `graph_service.topic_wiki` |
| POST `/brief/daily` | apps/api/routers/content.py:166-202 | `brief_service.publish` |
| POST `/jobs/daily/run-once` | apps/api/routers/jobs.py:21-35 | `run_daily_ingest` + `run_daily_brief` |
| POST `/jobs/graph/weekly-run-once` | apps/api/routers/jobs.py:38-91 | 逐 topic 引用同步 + `sync_incremental` |
| POST `/translate/bilingual-pdf` | apps/api/routers/translate.py:74-124 | 快速/排版双语翻译（pdf2zh） |
| POST `/cs/feeds/{category_code}/fetch` | apps/api/routers/cs_feeds.py:140-204 | tracker 抓取 + `_trigger_auto_link`（189） |

### 1.2 FastAPI `BackgroundTasks`（响应后同进程执行）

- POST `/jobs/batch-process-unread` — apps/api/routers/jobs.py:94-154：`background_tasks.add_task(_run_batch)`（153），内部再开 `ThreadPoolExecutor(max_workers=PAPER_CONCURRENCY)`（134）。
- POST `/jobs/daily-report/run-once` — apps/api/routers/jobs.py:247-276：后台 `asyncio.new_event_loop().run_until_complete(...)`（264-266）。
- POST `/jobs/daily-report/send-only` — apps/api/routers/jobs.py:279-310。

### 1.3 同步阻塞请求线程的长任务路由（handler 内直接跑完）

- POST `/ingest/arxiv` — apps/api/routers/topics.py:254-303；POST `/papers/ingest/ieee` — papers.py:627-691。
- POST `/papers/{id}/download-pdf` — papers.py:313-333（同步下载）。
- POST `/papers/{id}/reasoning` — papers.py:610-621；POST `/papers/{id}/duplicates` — papers.py:594-607（embedding 相似度）。
- POST `/graph/citation-network/topic/{id}/deep-trace` — graph.py:189-192；POST `/graph/auto-link` — graph.py:245-248。
- 14 个 GET 图谱端点 — graph.py:103-325：`await run_in_threadpool(...)` 同步计算 UMAP/k-means/PageRank/LLM，60–600s 缓存。
- GET `/wiki/paper/{id}`、GET `/wiki/topic` — content.py:19-51：GET 内同步 LLM 生成并写库。
- POST `/rag/ask`、`/rag/ask-iterative` — pipelines.py:108-126。
- POST `/sessions/{id}/act1|act2|act3/generate` — sensemaking.py:260-302。
- POST `/writing/process|refine|process-multimodal` — writing.py:20-65。
- POST `/translate/selection|segments` — translate.py:54-71（后者内部每请求池 5 线程，services/translate.py:43）。
- POST `/agent/chat` — agent.py:107-244：SSE 流内执行多轮 agent loop，工具可再提交 tracker 任务；`/agent/confirm|reject/{action_id}` — agent.py:342-361。
- POST `/settings/email-configs/{id}/test` — settings.py:270。

### 1.4 APScheduler jobs（worker 进程，apps/worker/main.py）

调度器 `BlockingScheduler` + `APSThreadPoolExecutor(max_workers=3)`（253-254）；公共 kwargs `max_instances=1, misfire_grace_time=300, coalesce=True`（257-262）。

| job id | 位置 | 触发 | 内容 |
| --- | --- | --- | --- |
| `topic_dispatch` | worker/main.py:123-178（注册 267-273） | 每小时 :00 | 按 `TopicSubscription` 计划逐个 `_retry_with_backoff(run_topic_ingest)` |
| `cs_feed_dispatch` | worker/main.py:221-229（276-282） | 每小时 :05 | `CSFeedOrchestrator.sync_categories()` + `run()` |
| `daily_brief` | worker/main.py:181-205（288-306） | DB 配置 cron，默认 `0 4 * * *` | `run_daily_brief` |
| `weekly_graph` | worker/main.py:208-218（309-316） | `settings.weekly_cron` 默认周日 22:00 | 引用同步维护 |

另：worker 启动时 `start_idle_processor()`（335；packages/ai/idle_processor.py:452-454），空闲时逐篇补处理。

### 1.5 API lifespan 内的 batch consumer

- apps/api/main.py:170-177 — `_batch_lifespan` 启停 batch consumer，与 MCP lifespan 合并（181）；MCP 挂载 main.py:259。
- packages/agent_core/batch_consumer.py:62-70 — `start()` 先 `recover_stale_running()`（67）再起 daemon 线程（68）。
- `_consumer_loop`（46-59）每 5s 从 `batch_jobs` 表 `claim_next()` 取 pending job，`_run_one_job`（23-43）按 kind 执行 `pipelines.skim/deep_dive/embed_paper`。
- **关键事实：worker 进程不消费 `batch_jobs`；只有 API 进程消费。** 写入方是 agent 工具 `batch_*`（§1.7）。

### 1.6 MCP 工具（apps/api/mcp.py）

- 副作用：`trigger_skim`（222-251，同步阻塞执行）、`trigger_embed`（254-274，同步）、`trigger_daily_job`（277-298，tracker.submit）。
- 只读/计算：`search_papers`（82-103）、`get_paper`（106-151）、`get_daily_brief`（154-170，可能触发 LLM）、`recommend_papers`（173-184）、`find_similar`（187-219）、`get_task_status`（301-320，轮询 tracker）。

### 1.7 Agent 工具（packages/ai/tools/registry.py + handlers/）

触发长任务（多数 `requires_confirm=True`）：

- `ingest_arxiv` — registry.py:184-200；handler ingest.py:113-343（入库后开线程池并行 embed+skim；PDF 下载进模块级 `_pdf_download_pool`，21/58）。
- `skim_paper` / `deep_read_paper` / `embed_paper` — registry.py:201-236；agent loop 内同步执行（handlers/read.py:19-97）。
- `batch_skim_papers` / `batch_deep_read_papers` / `batch_embed_papers` — registry.py:444-491；写 `batch_jobs` 表（handlers/batch.py:14-42），由 §1.5 的 API 进程 consumer 消费。
- `generate_wiki` — registry.py:237-256（submit 后轮询 tracker）；`generate_daily_brief` — 257-271（同步）；`reasoning_analysis` — 315-326；`analyze_figures` — 378-394；`manage_subscription` — 272-299；`identify_research_gaps` — 327-343；`search_arxiv`/`suggest_keywords`/`writing_assist`/`ask_knowledge_base` — LLM 类。
- `get_batch_job_status`（registry.py:492-503；handlers/batch.py:45-71）是 `batch_jobs` 的**唯一查询面，无 REST 端点**。

Subagent：packages/agent_core/subagents.py:39-123，每次各起独立线程（88、120）。

## 2. 任务/状态存储

### 2.1 进程内 tracker

- packages/domain/task_tracker.py:76-217 — `TaskTracker`：纯内存 dict（86）+ 锁（87）；`TaskInfo` 完成后 TTL 600s（27）；模块级单例 `global_tracker`（217）。
- `submit()`（140-180）每个任务新建一个裸 daemon `threading.Thread`（178），无池化、无并发上限。
- `cancel()`（127-136）仅置 `finished=True, success=False` 标志，不中断线程；**全仓库无任何 HTTP 端点调用它**。
- 前端可经 POST `/tasks/track`（pipelines.py:139-165）直接在服务端内存创建/更新/完成任务条目。
- 适配器：packages/agent_core/tasks.py:261-349（`GlobalTrackerAdapter`）。
- 另有 agent 规划用的文件型任务系统（非 job 执行）：`TaskManager`（tasks.py:73-110，task_*.json 落盘）、`TodoManager`（todos.py:78-79）。

### 2.2 数据库表

- `batch_jobs` — packages/storage/models.py:659-673（kind 仅 skim/deep_read/embed；status pending/running/completed/failed）。仓储 repositories/batch.py:17-82：`claim_next` 用 `with_for_update(skip_locked=True)`（32-45，**SQLite StaticPool 单连接下无效**，仅 Postgres 生效）；`recover_stale_running`（73-82）把 running 一律置 failed。
- `pipeline_runs` — models.py:144-167（每次 skim/deep/embed/ingest 写入，paper_pipelines.py:166、332、429、484、534）；`retry_count` 列存在但无自动重试执行器。
- `topic_subscriptions` — models.py:204-214（`last_run_at/last_error` 由 worker/main.py:70-80 持久化）；`cs_feed_subscriptions` — models.py:560-566（active/cool_down/paused）。
- `agent_pending_actions` — models.py:355-358（agent 确认挂起）；`generated_contents` — models.py:294-297（wiki/简报产物）；`paper_translations` — models.py:637。

### 2.3 文件系统状态

- worker 心跳文件 `/app/data/worker_heartbeat.json` — 写 apps/worker/main.py:41-57（全失败时不写，靠过期判断）；读 apps/api/routers/system.py:22-41（stale 阈值 1200s）。
- 跨进程限流 token bucket 状态文件 — packages/ai/rate_limiter.py:22-101。
- agent TaskManager/TodoManager JSON 文件；简报 HTML 落盘（handlers/wiki_brief.py:123）。

### 2.4 前端轮询端点（三套并存）

- GET `/tasks/active` — pipelines.py:132-136；前端 GlobalTaskContext.tsx:57-58 每 2s/10s 轮询。
- GET `/tasks/{task_id}`（+`/result`）— pipelines.py:168-186；pollTask.ts:32/50（2s 间隔、5 分钟客户端超时，但后端任务继续跑），被 skim/deep/embed/翻译/wiki/简报等使用。
- GET `/ingest/references/status/{task_id}` — topics.py:321-329。
- GET `/topics/{id}/fetch-status` — topics.py:231-248：实现是遍历 `global_tracker.get_active()` 按 task_id 前缀**模糊匹配**（235-240）。
- GET `/actions`、`/actions/{id}`、`/actions/{id}/papers` — jobs.py:160-241。
- `batch_jobs`：无 REST 查询端点（仅 §1.7 agent 工具）。

## 3. 线程池与后台循环

进程级常驻：

- batch consumer daemon 线程 + while 轮询（batch_consumer.py:46-70）。
- `IdleProcessor` daemon 线程 + 60s 轮询循环（idle_processor.py:370-454）；其 `record_api_request()`（462-466）**全仓库无调用点（死代码）**。
- APScheduler 主循环 + executor 池 3（worker/main.py:68、253-254）。
- 模块级池：`_auto_link_pool`（paper_pipelines.py:98，提交点 238/382 与 cs_feed_orchestrator.py:261）、`_pdf_download_pool`（handlers/ingest.py:21，提交点 58）。

任务期创建（生命周期跟随请求/任务，无全局上限）：

- 每个 tracker 任务一个裸线程（task_tracker.py:178）。
- daily_runner.py:238（池 3）+ 篇内池 2（61）；jobs.py:134（池 PAPER_CONCURRENCY）；brief_service.py:453（池 4）；figure_service.py:343（池 3）；citation.py:75、427；wiki.py:352；translate.py:191（池 5）+ services/translate.py:43（池 5）。
- reference_import.py:163-167 完成后一次性 daemon 线程 `_bg_skim_and_embed`（455-468）。
- FastAPI `BackgroundTasks`（jobs.py:153、275、309）；`run_in_threadpool`（graph.py 13 处、mcp.py:37）；`asyncio.to_thread`（papers.py:122、channel_pool.py:44）。
- agent 主循环 packages/agent_core/loop.py:251-320。

## 4. Service 单例与重依赖（apps/api/deps.py）

- deps.py:136 `pipelines = PaperPipelines()` → PyMuPDF/fitz（packages/ai/pdf_parser.py:18）、`VisionPdfReader`、`LLMClient`、Arxiv/Ieee client、CostGuard（paper_pipelines.py:18-28）。
- deps.py:137 `rag_service` → LLM + 仓储（rag_service.py:12-21）。
- deps.py:138 `brief_service` → Jinja2、NotificationService（brief_service.py:13、17）。
- deps.py:139 `graph_service` → 引用/图谱子服务门面（graph/facade.py:25-49）；`SimilarityService` 按需拉 numpy（similarity.py:28）、umap（54-57）、sklearn PCA fallback（63）。
- deps.py:28-74 模块级 `TTLCache`；apps/api/services/translate.py:11 模块级 `LLMClient()`。
- DB 引擎 import 时创建（packages/storage/db.py:67-74；SQLite 走 StaticPool 单连接）；迁移在 apps/api/main.py:215。
- `LLMClient.__init__` 本身轻量（llm_client.py:221-223），OpenAI SDK 在首次使用（202）。

## 5. Worker 进程

- 启动 `python -m apps.worker.main`（docker-compose.yml:66；单机合并部署 infra/supervisord.conf:16-41）。
- **不是队列消费者**：直接读 `topic_subscriptions`/`cs_feed_subscriptions`/`daily_report_configs` 决策并同步执行（worker/main.py:129-136、288-294）。`batch_jobs` 队列 worker 不参与（见 §1.5）。
- 健康：心跳文件（41-57 写 / system.py:26-41 读）；其余仅日志。进程内 `_dispatching` 布尔（idle_processor.py:25-36）仅 worker 进程内有效。
- 优雅关闭 SIGINT/SIGTERM → scheduler shutdown + stop_idle_processor（worker/main.py:320-328）。

## 6. Job 控制语义：现状与缺失

现有：

- 取消：`TaskTracker.cancel` 仅翻转标志（task_tracker.py:127-136），无中断、无端点。
- 重试：ad-hoc — worker `_retry_with_backoff`（worker/main.py:83-99）、topic `retry_limit` + 指数退避（daily_runner.py:151-187）、`pipeline_runs.retry_count` 列无执行器引用。
- 崩溃恢复：`recover_stale_running` 仅 API 启动时 running→failed（repositories/batch.py:73-82），丢弃进度语境，无续跑。
- 认领：`claim_next` 用 `skip_locked`（batch.py:32-45），仅 Postgres 有效。
- 暂停：仅 IdleProcessor 在"不再空闲"时逐篇 break（idle_processor.py:246-255），进程内，用户不可控。
- 限流：rate_limiter.py 跨进程 token bucket + 并发/日配额（282-306）。

缺失：

- 无 cancel/retry/pause/resume 任何 REST 端点（tracker 任务与 batch_jobs 均无）。
- 无 lease/租约续约：job 认领后进程死亡只能等下次 API 重启统一置 failed。
- 无 per-job 超时：tracker 任务无超时（task_tracker.py:159-176）；前端 5 分钟超时只是客户端放弃，后端继续跑。
- `batch_jobs` 无 priority、无 dead-letter、失败条目不可重试；kind 仅 3 种。
- 无幂等/去重：同一 paper 可被 API consumer、idle processor、topic ingest、手动端点并发处理；跨进程无锁。

## 7. 测试覆盖

- tests/ 共 8 文件、85 个测试：仓储（test_repositories.py）、auth token/设备码（test_auth_tokens.py:73-319）、demo 中间件限流（test_demo_mode.py:59-166）、IEEE 客户端、agent 会话历史、导入冒烟（test_import_smoke.py:9-136）。
- **无 pytest 级 e2e**；`scripts/e2e-full.mjs` 是手动 Playwright UI 冒烟，未纳入测试运行器；前端无单测。
- 主用户流（导入 → skim/deep read → ask → brief）零自动化覆盖。最大未覆盖面：PaperPipelines、TaskTracker 生命周期、batch consumer、batch_jobs 仓储、APScheduler 四个 job、IdleProcessor、MCP 工具、RAG/brief/graph 服务、jobs router 全部端点、translate、reference importer。

## 8. 与目标架构的差距（作为设计②③的输入）

- 任务状态三处分裂，无统一持久 job store；`global_tracker` 任务随 API 重启全丢，worker 进程内任务对 API/前端不可见。
- 执行原语异构（裸线程、5+ 个临时/模块级池、BackgroundTasks、APScheduler、daemon consumer），无统一队列/worker 协议。
- 进程职责交错：batch 队列只有 API 消费，定时任务只有 worker 执行，互不接管。
- job 控制面为零（无 cancel/retry/pause/resume 端点，无 lease/timeout/幂等/死信），恢复是破坏性的。
- 查询面碎片化：前端三套轮询端点 + 前缀模糊匹配；batch_jobs 无 REST 查询；前端还能在服务端内存"造任务"（POST /tasks/track）。
- 重依赖（NumPy/UMAP/sklearn/PyMuPDF/LLM）以 import 期单例固化在 API 进程（deps.py:136-139）；重图谱计算靠 `run_in_threadpool` 兜底而非任务化。
- 健康信号依赖共享卷心跳文件 1200s 过期约定，非 DB/队列化。
- 核心 flow 零回归测试（→ 路线图 A3）。

## 变更记录

- 2026-09-02：初版，基于 `main@23f3c2b` 快照审计。
