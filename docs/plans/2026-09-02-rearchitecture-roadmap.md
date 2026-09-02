# PaperMind 2026 重构路线图（小目标拆解）

状态：**执行中**

日期：2026-09-02

分支：`refactor/papermind-2026`

依据：[PaperMind 2026 形态与重构设计](./2026-09-02-papermind-2026-rearchitecture.md)（下称"设计文档"，2026-09-02 第三版：Pi downstream fork + Local PM UI + Full Web 可选化 + 原子 Durable Execution）

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
| Stage A · Phase 0 基线 + 六份设计 | 10 | 4 | 进行中 |
| Stage B · Phase 1 application command/query | 8 | 0 | 未开始 |
| Stage C · Phase 2 原子 durable execution | 11 | 0 | 未开始 |
| Stage D · Phase 3 Research State 垂直切片 | 7 | 2 | 进行中 |
| Stage E · Phase 4 PM Research Terminal + MCP 一等化 | 10 | 0 | 未开始 |
| Stage F · Phase 5 Local UI 与可选 Full Web 适配 | 7 | 0 | 未开始 |
| Stage G · Phase 6 公开 Demo | 3 | 0 | 未开始 |
| Stage H · Phase 7 语言/存储决策门 | 2 | 0 | 未开始 |

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
- [ ] **A6 设计②：Application command/query 清单与调用映射**
  内容：把 151 个 HTTP handlers、MCP tools、agent tools 映射到有限的用例集合（设计文档 §5.1 命令/查询表）。
  出口条件：每个现有入口都有映射目标；无覆盖的用例显式列入"暂不迁移"。
- [ ] **A7 设计③：原子 Durable Execution 协议与迁移说明**
  内容：定义 ResearchRun/Job/Task/Attempt/Artifact、Task 原子边界、代码化 Workflow、lease/fencing、幂等/outbox、Reconciler 和 Executor capability；说明 `TaskTracker`、`BatchJob`、APScheduler、后台线程与 worker heartbeat 如何收敛。
  输入：审计报告 §2/§3/§6。
  出口条件：文档获确认，能直接指导 C1–C11。
- [ ] **A8 设计④：PM Research Terminal downstream 架构**
  内容：Pi 上游基线（pinned tag）、patch policy（有序 patch stack、product profile 先于 build/source pruning）、独立仓库 `PaperMind-Terminal` 维护准则、capability metadata、确定性命令、permission profiles、主题与领域 renderer、fallback 契约。
  出口条件：文档获确认，能直接指导 E1/E2。
- [ ] **A9 设计⑤：UI Surface Contract**
  内容：现有 Web route/capability inventory（retain/merge/local-ui/archive）、canonical presentation model 第一版、共享 UI 包（`@papermind/client` / `presentation` / `ui-core`）边界、deep links、Local UI loopback bridge 契约、Full Web 可选部署 profile。
  输入：审计报告 §2.4（前端三套轮询端点）。
  出口条件：文档获确认，inventory 一次产出、供 A9 与 F1 共同引用。
- [ ] **A10 设计⑥：HTTPS identity/token flow**
  内容：GitHub Web 登录、CLI device authorization、MCP OAuth discovery、PaperMind token、本地模型凭据与 Local UI session 的边界。
  出口条件：文档获确认，能直接指导 E3/E8–E10 与 G2。

## Stage B — Phase 1：application command/query

阶段出口条件：Full Web、Local UI、PM Research Terminal 和 MCP 对同一能力调用同一个 application handler；存在第一版 canonical presentation model。

- [ ] **B1 application 层骨架**：建立 commands/queries 目录结构、handler 协议与依赖注入约定；repository/provider 只允许在 application 层内使用。
- [ ] **B2 canonical presentation model 第一版**：定义 Paper/Claim/Evidence/Job/Task/Attempt/Artifact/diff 的 view model 契约；application handler 产出 canonical result，HTTP 返回用其包裹并保持兼容。TS 侧共享类型在 F2 正式提取，但契约先在服务端定死。
- [ ] **B3 只读切片①：SearchPapers + GetPaper**：对应 HTTP 路由改为调用 application handler，返回保持兼容，前端不动。
- [ ] **B4 只读切片②：GetResearchQuestion/ListClaims/GetClaimEvidence**：同上，覆盖研究状态读取面。
- [ ] **B5 MCP 工具改调 application handlers**：`apps/api/mcp.py` 工具不再直接引用 deps/service（审计 §1.6）。
- [ ] **B6 agent tools 改调 application handlers**：`packages/ai/tools/registry.py` 保留参数与返回语义，handler 业务下沉（设计文档 §5.5）。
- [ ] **B7 其余查询全量迁移**：按 A6 映射清单逐个推进，每批一个提交。
- [ ] **B8 命令面迁移**：ImportPaper/CreateResearchQuestion/StartSkim/StartDeepRead/StartEmbedding 等写路径走 application command，长任务入口统一创建 Job，不再直接调用具体 Worker 或线程池（为 Stage C 铺路）。

## Stage C — Phase 2：原子 durable execution

阶段出口条件：API/Executor 任意重启后，任务状态可解释、可恢复且不会静默丢失；同一 Task 的重复 Attempt 不会重复提交领域结果；单篇失败无需重跑整个批次。

- [ ] **C1 batch consumer 移出 API 进程**：API lifespan 不再启动任务消费（审计 §1.5，现仅 API 进程消费 `batch_jobs`，worker 不参与）。
- [ ] **C2 原子执行 schema**：落库 `jobs`、`tasks`、`task_attempts` 和 artifact/event references；ResearchRun 关联 Job，Job 聚合 Task，Task 保留 capability/schema/handler version、依赖、资源类别、预算与幂等键。
- [ ] **C3 统一旧状态**：用新 job store 取代内存 `TaskTracker`（10 分钟 TTL、重启即丢）、旧 `batch_jobs` 状态与心跳文件的权威地位；前端三套轮询端点收敛到 Job graph、Task 与 Attempt 查询。
- [ ] **C4 第一批原子 Task 清单**：为 Skim、DeepRead、Embedding、Topic Research 和 Daily Brief 标出单一有意义副作用、输入输出、timeout、retry、resource class 与无法自动重试的边界；禁止把普通 helper 机械拆成 Task。
- [ ] **C5 代码化 Workflow 模板**：实现顺序依赖、条件分支和 per-Paper fan-out；父 Job 支持 succeeded、partially_succeeded、failed、cancelled，并能解释每个子 Task 的贡献。
- [ ] **C6 scheduler/planner/dispatcher 分工**：APScheduler 只创建 Job，Planner 展开 ready Task，Dispatcher 按依赖、priority、resource class 和 concurrency policy 分派，不再进程内直跑研究逻辑。
- [ ] **C7 通用 Executor 协议**：Python Executor 每次只执行一个 Task Attempt，注册 capability/version/resource class，支持 drain；Worker 进程和心跳不再是产品层任务事实来源。
- [ ] **C8 lease、fencing 与 Reconciler**：领取和续约 lease 时签发 fencing token；迟到 Attempt 不能覆盖新结果；Reconciler 回收过期 lease 并执行 backoff、dead-letter 或 manual recovery。
- [ ] **C9 幂等与副作用账本**：数据库结果与 outbox 同事务提交；Paper/Claim/Evidence 写入使用稳定幂等键；邮件、provider call 等外部效果使用 provider key 或 effect ledger 去重。
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
- [ ] **D3 ResearchRun 生成待验证 Claim**：强制证据坐标与完整 provenance（source version、任务、时间、模型、策略版本）。
- [ ] **D4 查询实现**：GetResearchQuestion、ListClaims、GetClaimEvidence、DiffResearchState。
- [ ] **D5 Research Object 基础导出**：至少 JSON + Markdown，含校验值与 provenance 摘要。
- [ ] **D6 领域事件**：append-only outbox/event log 记录 Claim 与 SourceVersion 的关键状态变化（设计文档 §4.7 事件表）。
- [ ] **D7 confirmed 规则落地**：author/PaperMind/user 判断来源区分；无证据输出只能 draft/pending verification。

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

## Stage H — Phase 7：语言与存储决策门

- [ ] **H1 重测资源基线**：对照 A2 记录，定位剩余成本来源（Python control plane / 重依赖 / 数据库 / 具体任务）。
- [ ] **H2 决策记录**：是否迁移 Go control plane；个人服务用 SQLite 还是 PostgreSQL。出口条件：任何迁移都有测量证据和独立回滚路径，否则维持现状。

## 变更记录

- 2026-09-02：建立路线图；完成 A1 审计。
- 2026-09-02（第二次）：同步设计基线第二版——Pi 从 SDK adapter 改为 downstream fork 策略（A8/E1）、新增 Local PM UI（A9/F3/F4）、Full Web 从瘦身删除改为可选模块（F1/F5/F6）、设计五份变六份（A5–A10）、Phase 0–6 变 0–7（Stage A–H）、Phase 1 出口新增 canonical presentation model（B2）。
- 2026-09-02（第三次）：完成 A3——主用户流程端到端回归测试（tests/test_e2e_main_flow.py，LLM/arXiv/vision 全 fake + tmp SQLite）与 CI 测试 workflow（tests.yml）。
- 2026-09-02（第四次）：完成 A5 设计①（Research State 最小数据契约：7 实体、状态机、事件/outbox、PROV 映射、共存策略），§11 决策点待确认。
- 2026-09-02（第五次）：用户确认设计①全部决策点；完成 D1——数据契约落地为 models/枚举/UUIDv7/migration/仓储，16 个契约测试 + 全量 101 passed。
- 2026-09-02（第六次）：完成 A4 + D2——ingest 同事务建 v1 SourceVersion（9 个入库路径全覆盖）、A4 样本种子（author 即证 + papermind draft 待人工抽检），全量 104 passed。
