# 设计③：原子 Durable Execution 协议与迁移说明

状态：**待确认**（重构路线图 A7；六份设计之第三份）

日期：2026-09-02

依据：[PaperMind 2026 形态与重构设计](./2026-09-02-papermind-2026-rearchitecture.md) §5.2–§5.4（第四版）；[Phase 0 现状审计](./2026-09-02-phase0-baseline-audit.md) §1–§3、§6；[设计① Research State 数据契约](./2026-09-02-design-1-research-state-data-contract.md)（ResearchRun 衔接）。

范围：把设计文档 §5.2 的架构概念落成**可直接建表的 schema、可执行的状态机、可指派的组件职责和版本化 Go/Python 协议**，并给出"现有四套任务机制如何收敛"的迁移映射。出口条件：能直接指导 C0–C11。

## 1. 对象模型与表结构

五层：`ResearchRun（领域，已有）→ Job → Task → Attempt → Artifact`，外加既有 `research_events` 作领域事件 outbox。全部主键 UUIDv7 hex（与设计①一致）；JSON 列走 `JSONB_or_JSON()`；时间 UTC。

### 1.1 jobs（用户意图/计划流程）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | String(32) PK | |
| kind | String(64) | capability 名，如 `RunTopicResearch`、`BuildDailyBrief`（设计②命令目录） |
| status | enum {submitted, planning, queued, running, partially_succeeded, failed, cancelling, cancelled} | 见 §2 |
| payload | JSON | 参数摘要（paper_ids、query、config 等） |
| idempotency_key | String(128) unique nullable | 幂等提交：同 key 重复提交返回已有 Job |
| priority | int | 默认 0； scheduler 任务可低、用户交互可高 |
| budget | JSON | `{max_retries, timeout_s, max_cost_usd}` |
| research_run_id | FK→research_runs.id nullable | 领域层衔接（设计①：Run 说明为何执行） |
| created_by | String(128) | user / scheduler / watch / api |
| progress | JSON | `{current, total, message}`——由子 Task 收敛聚合，**不手写** |
| created_at / started_at / finished_at | DateTime | |

### 1.2 tasks（可独立调度/重放的工作原子）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | String(32) PK | |
| job_id | FK→jobs.id | 父 Job |
| seq | int | 展示顺序 |
| capability | String(64) | handler 注册名（如 `skim_paper`） |
| handler_version / input_schema_version | int | 重放可解释性 |
| status | enum {queued, leased, running, succeeded, failed, cancelled, dead_letter, manual_recovery} | |
| depends_on | JSON | 前置 task id 列表（DAG 最小表达） |
| input_ref | JSON | 稳定 ID/值描述，不依赖进程内存 |
| output_artifact_id | FK→artifacts.id nullable | |
| idempotency_key | String(128) unique | 幂等副作用键（如 `skim:{paper_id}:{source_version_hash}`） |
| priority / resource_class | int / String(32) | `default`/`pdf`/`llm`/`embedding`/`graph` |
| timeout_s / max_attempts / attempt_count | int | |
| lease_token | String(64) nullable | 领取时签发 |
| lease_expires_at | DateTime nullable | 心跳续约 |
| last_error | Text nullable | |
| created_at / updated_at | DateTime | |

### 1.3 task_attempts（每次真实执行）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | String(32) PK | |
| task_id | FK→tasks.id | |
| attempt_no | int | 1 起步 |
| executor_id | String(64) | 执行载体标识 |
| fencing_token | int | 单调递增；提交终态时校验 |
| status | enum {running, succeeded, failed, timeout, cancelled} | |
| error_class / error_message | String(64) / Text | 错误分类（network/llm/validation/...）供重试策略 |
| log_ref / cost_refs | JSON | 日志与 PromptTrace 引用 |
| started_at / finished_at | DateTime | |

### 1.4 artifacts（可引用产物）

| 字段 | 类型 |
| --- | --- |
| id | String(32) PK |
| task_id | FK→tasks.id |
| kind | String(32)（report/export/file/...） |
| uri | String(1024)（文件路径或 DB 引用） |
| content_hash | String(64) |
| metadata_json | JSON |
| created_at | DateTime |

**与 research_events 的分工**：Task 生命周期记在 tasks/attempts（执行审计）；Python Executor 只提交带 fencing token 的 result proposal/Artifact，不直接写 Core 表。Go Core 校验后通过 application command 将领域变化与 `research_events` 在同一事务提交（outbox，设计①）。`JobFailed` 事件由 Go Reconciler 在 Job 终态时发出，`ResearchRunCompleted` 由 Run 收敛逻辑发出——事件词汇表不变。

## 2. 状态机

```text
Job:   submitted → planning → queued → running → succeeded*/partially_succeeded/failed
       （succeeded* 由子 Task 全部成功收敛而来，不手写）
       任意运行态 → cancelling → cancelled（未领取 Task 立即取消；运行中 Attempt 协作退出）

Task:  queued → leased → running → succeeded
                                ├→ failed ──(attempt < max_attempts, backoff)──→ queued
                                ├→ failed ──(attempts 耗尽)──→ dead_letter
                                └→ cancelled
       不可安全重放且已失败 → manual_recovery（不自动重试）
```

- **Job 状态只由子 Task 收敛**（Reconciler 计算），Executor/业务代码不得直接写 Job 终态。
- **lease 规则**：Dispatcher 领取时生成 `lease_token` + `fencing_token = attempt_count`，租期默认 10 分钟，Executor 每 1/3 租期续约；租期过期 Reconciler 置回 queued 并递增 attempt_count——**旧 Attempt 的 fencing_token 小于当前值，其终态提交被拒绝**（迟到写入不覆盖新结果）。
- **取消语义**：协作式。cancel 只置 Job=cancelling + 未领取 Task=cancelled；运行中 Attempt 收到取消请求在安全检查点退出（LLM 调用间隙、PDF 分页间隙）；超过 grace（默认 5 分钟）由 Reconciler 释放 lease 按副作用策略处理。已提交的领域结果不回滚，由补偿事件修正。

## 3. 第一批 Task 原子边界（C4 清单）

"原子"= 值得独立重试、隔离资源、观察或追溯的步骤；普通 helper/纯查询不建 Task。

| capability | 输入 | 主要副作用 | 幂等键 | resource_class | 超时 | 重试 |
| --- | --- | --- | --- | --- | --- | --- |
| fetch_feed | topic 订阅、cursor | 抓取 arXiv 列表（无写库） | `fetch:{topic}:{date}` | network | 120s | 3 |
| upsert_paper | PaperCreate | papers + SourceVersion v1 + 事件 | `upsert:{arxiv_id}` | default | 30s | 3 |
| download_source | paper_id, version | PDF 文件 + set_pdf_path | `dl:{paper}:{hash}` | network | 300s | 3 |
| skim_paper | paper_id | AnalysisReport + pipeline_runs | `skim:{paper}:{sv_hash}` | llm | 600s | 2 |
| deep_read_paper | paper_id | AnalysisReport + vision 分析 | `deep:{paper}:{sv_hash}` | llm | 1800s | 2 |
| extract_claims | paper_id, source_text | ResearchRun + Claims + Evidence（D3） | `claims:{paper}:{sv_hash}` | llm | 600s | 2 |
| embed_paper | paper_id | paper.embedding | `embed:{paper}:{sv_hash}` | embedding | 120s | 3 |
| build_daily_brief | date, limit | generated_contents + HTML 文件 | `brief:{date}` | llm | 900s | 2 |
| send_brief_email | recipient, html | 外部邮件 | `mail:{date}:{recipient}` | network | 60s | **0 → manual_recovery** |

Citation 同步（sync_citations_for_paper/topic）、figure 分析、auto-link 同规则登记；输入输出表在 C4 实现时逐个补全。

## 4. Workflow 模板（C5，代码定义 + 状态持久化）

```python
WORKFLOW_TEMPLATES = {
    "RunTopicResearch": plan_topic_research,   # ResolveSubscription → FetchFeed → [UpsertPaper × N] → [Download+Skim+Embed+ExtractClaims × N] → 收敛
    "BuildDailyBrief": plan_daily_brief,       # CollectCandidates → BuildBrief → (SendEmail | manual_recovery)
    "ProcessUnreadBatch": plan_batch,          # [Skim/Deep/Embed × N]（对应现 batch_jobs）
    "RunCitationSync": plan_citation_sync,     # per-paper fan-out
}
```

- Planner 是纯函数：`plan(job, completed_tasks, artifacts) -> [task 输入]`；每轮调度增量展开，支持顺序依赖、条件分支、per-paper fan-out。
- **部分成功**：fan-out 中单篇失败不重跑整批；Job 终态由成功/失败比与 workflow policy（`continue_on_failure: true` 默认）决定 succeeded / partially_succeeded / failed。
- 不建设通用 DAG 平台/可视化编辑器（设计文档风险项）。

## 5. 运行组件（C6/C7/C8）

| 组件 | 职责 | 部署形态（第一阶段） |
| --- | --- | --- |
| Scheduler | 按时间/事件创建 Job；不执行研究逻辑 | Go Core |
| Workflow Planner | 以纯函数增量展开 ready Task | Go Core |
| Dispatcher | 按 depends_on/priority/resource_class/concurrency 签发 lease | Go Core |
| Executor | 每次执行一个 Task Attempt；续约 lease；提交 result proposal/Artifact | 独立 Python 进程（按 resource_class 设并发上限） |
| Reconciler | 过期 lease 回收、backoff 重试、死信、Job 收敛、`JobFailed` 事件 | Go Core 定时循环 |

- **Python API 进程零消费**（C1）：`batch_consumer` 从 lifespan 移除；所有新任务由 Go Core create_job / 查询 / 控制。
- **Executor Protocol**（C0/C7）：版本化 HTTPS/JSON 端点至少覆盖 register、claim、heartbeat、complete、fail、cancel；每次 complete/fail 必须携带 attempt_id 与 fencing_token。Executor 只能读取自己 lease 对应的输入和 Artifact 上传能力。
- **Executor capability 注册**（C7）：`{executor_id, capabilities:[...], resource_limits, version, heartbeat_at}` 落 `executor_status` 表（取代 worker heartbeat 文件）；`drain` = Core 停止给它签发新 lease，当前 Attempt 正常收敛。
- **单一权威写入**：jobs/tasks/attempts、Research State 和 outbox 只由 Go Core 写；Python Executor 不共享 ORM，不直连这些表。迁移按 aggregate 切换所有权，禁止双写。
- **SQLite/PG 差异**：领取发生在 Go Core 内部。PG 可用 `FOR UPDATE SKIP LOCKED`；SQLite profile 由单 Dispatcher 串行签发 lease，因此 Python Executor 数量不会转化为多个数据库写入者。

## 6. 旧机制收敛映射（C3/C11 的执行说明）

| 现状（审计） | 目标 | 迁移方式 |
| --- | --- | --- |
| 内存 `TaskTracker`（600s TTL、重启即丢、裸线程/任务） | tasks/attempts 表 | `global_tracker.submit` 调用点改为 `create_job(kind=...)`；`/tasks/*` 端点过渡期改读 tasks（C3），随后并入 `/jobs`（C10） |
| `batch_jobs` 表（3 kinds，仅 API 进程消费） | ProcessUnreadBatch workflow | C11 第一批：存量 pending batch_jobs 转为 tasks；batch consumer 删除（C1） |
| APScheduler 4 个 job（进程内直跑） | Go Scheduler 只建 Job | 过渡期 APScheduler 只向 Go Core 提交：`topic_dispatch_job` → `RunTopicResearch`；`brief_job` → `BuildDailyBrief`；`weekly_graph` → `RunCitationSync`；`cs_feed_dispatch` → `StartFeedFetch`，随后由 Go Scheduler 接管时间规则 |
| worker heartbeat 文件（1200s 过期约定） | executor_status 表 | C7；`/system/worker` 端点改读表 |
| FastAPI BackgroundTasks / 模块级 ThreadPoolExecutor / 裸 daemon 线程 | 全部消失 | 调用点逐一改为命令（设计②映射表 B7 批次） |
| IdleProcessor（worker 进程内） | 按需 Job（空闲时 create_job(ProcessUnreadBatch)） | C11 |
| `_dispatching` 布尔防冲突 | Job 幂等键 + Dispatcher 去重 | C2 |
| `recover_stale_running`（running→failed 破坏性恢复） | Reconciler lease 回收重入 | C8 |
| `pipeline_runs` 表 | 保留为 legacy 观测 | Attempt 为权威执行审计后，C 阶段末评估只读归档 |
| POST /tasks/track（前端造任务） | 废弃 | F1 |

## 7. 控制与观察面（C10）

```
POST /jobs                      提交（kind + payload + idempotency_key）
GET  /jobs?status=&kind=        列表
GET  /jobs/{id}                 Job + 子 Task graph（含 Attempt 摘要、成本、错误）
POST /jobs/{id}/cancel|retry    Job 级控制
POST /tasks/{id}/retry          单 Task 重试（dead_letter/manual_recovery 出口）
POST /queue/pause|resume        队列级（Dispatcher 停止/恢复领取）
GET  /executors、POST /executors/{id}/drain   运维面（与用户控制同账号、分 scope）

POST /internal/executors/register
POST /internal/tasks/claim
POST /internal/attempts/{id}/heartbeat
POST /internal/attempts/{id}/complete|fail
```

CLI（`pm jobs ...`）与 MCP 在 Phase 4 经同一公共 REST 面（设计②目录），不另写第二套 API。`/internal/*` 只服务 Executor，使用独立凭据、audience、scope 和网络策略，不暴露给 Demo 用户。

## 8. 测试策略（C11 的验收用例）

1. **强杀恢复**：Python Executor 执行中 kill 模拟（不续约）→ Go Reconciler 回收 → Task 重入 → 幂等键防重复领域写入。
2. **lease 过期 + 迟到写入**：过期后旧 Attempt 携旧 fencing_token 提交终态 → 被拒。
3. **部分失败**：fan-out 5 篇 1 篇失败 → Job partially_succeeded，其余成功结果保留。
4. **重复提交**：同 idempotency_key 两次 create_job → 同一 Job。
5. **取消**：queued Task 立即取消；running Attempt 协作退出；grace 后 Reconciler 收敛。
6. **回归底线**：A3 主流程 e2e + 全量 pytest 全程绿。

## 9. 待确认决策点

1. **lease 默认租期 10 分钟 / 续约间隔 200s**：LLM 长调用（deep read 实测可达数分钟）是否需要 per-capability 租期表？提案：budget.timeout_s 覆盖默认值即可。
2. **Executor 并发**：第一阶段单 Python Executor 进程 + 每 resource_class 并发上限（llm=2、embedding=2、network=4、default=2）——与现有限流桶对齐，确认？
3. **`pipeline_runs` 归档时机**：C 阶段末评估，还是直接保留长期？提案：C 阶段末。
4. **Job 级成本预算硬闸**（budget.max_cost_usd）第一阶段是否启用？提案：字段先落、执行闸在质量检查（P1）接入。

## 变更记录

- 2026-09-02：初版（A7）。
- 2026-09-02：架构决策更新——运行组件改为 Go Core 持有 Scheduler/Planner/Dispatcher/Reconciler 与全部权威状态，Python 仅通过版本化 Executor Protocol 执行 Attempt 并提交 proposal/Artifact；新增 C0。
