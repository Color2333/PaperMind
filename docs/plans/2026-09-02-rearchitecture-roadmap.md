# PaperMind 2026 重构路线图（小目标拆解）

状态：**执行中**

日期：2026-09-02

分支：`refactor/papermind-2026`

依据：[PaperMind 2026 形态与重构设计](./2026-09-02-papermind-2026-rearchitecture.md)（下称"设计文档"）

## 工作规则

1. 一次只推进一个小目标；完成即提交，不攒大批量改动。
2. 目标粒度以"一个工作日内可完成、有客观出口条件"为准；超出的目标继续拆。
3. 保持外部行为兼容（HTTP 返回、CLI 退出码），内部重定向到新边界；不同时重做 UI 和领域模型。
4. 重构期间冻结新增页面（设计文档 Phase 0 约束），除非直接服务于重构或 Demo。
5. 每个目标完成后在本文档勾选状态并写一行结论；发现新事实时更新拆解，不靠口头记忆。

## 进度总览

| 阶段 | 目标数 | 已完成 | 状态 |
| --- | --- | --- | --- |
| Stage A · Phase 0 基线 + 五份设计 | 9 | 1 | 进行中 |
| Stage B · Phase 1 application command/query | 7 | 0 | 未开始 |
| Stage C · Phase 2 durable jobs | 5 | 0 | 未开始 |
| Stage D · Phase 3 Research State 垂直切片 | 7 | 0 | 未开始 |
| Stage E · Phase 4 PM Research Terminal + MCP 一等化 | 9 | 0 | 未开始 |
| Stage F · Phase 5 前端瘦身 + Demo | 6 | 0 | 未开始 |
| Stage G · Phase 6 语言/存储决策门 | 2 | 0 | 未开始 |

主线顺序：A → B → C → D → E → F → G（对应设计文档 Phase 0–6）。其中设计文档 §11 的**第一个只读垂直切片**（SearchPapers + GetPaper + GetResearchQuestion + ListClaims + GetClaimEvidence，贯穿 application handlers → typed HTTPS client → CLI → Pi renderer → MCP adapter）横跨 B2/B3 与 E3/E4/E5，是 Stage B→E 的主线验收样例；五份设计（A5–A9）获确认后即从它开始。

## Stage A — Phase 0 基线与五份设计

阶段出口条件：设计文档 Phase 0 出口条件全部满足，且五份设计获确认。

- [x] **A1 长任务入口、状态存储、线程池审计**
  产出：[2026-09-02 Phase 0 现状审计](./2026-09-02-phase0-baseline-audit.md)。
  结论：任务状态三处分裂（内存 TaskTracker / `batch_jobs` 表 / 心跳文件），job 控制面（cancel/retry/pause/resume/lease）为零，核心流程零回归测试。
- [ ] **A2 资源基线测量**
  产出：测量脚本 + `docs/plans/` 基线记录。
  内容：API/worker/PostgreSQL/前端容器的空闲与峰值 RSS、镜像大小、冷启动时间；需在服务器上实测。
  出口条件：每个容器均有数值记录（Phase 0 出口条件第 1 项）。
- [ ] **A3 核心流程回归测试**
  产出：pytest 级端到端回归（导入论文 → skim/deep read → ask → brief 主链路）。
  输入：审计报告 §7 的缺口清单（现有 85 个测试均不覆盖主流程）。
  出口条件：主用户流程可在本地/CI 重复运行并通过；后续每个 Stage 的改动以它兜底。
- [ ] **A4 Research State 人工校验样本**
  产出：一个预置研究问题 + 少量论文的 Claim/Evidence/SourceVersion 小样本（人工校验过）。
  出口条件：样本可被 Phase 3（D2）迁移直接消费。
- [ ] **A5 设计①：Research State 最小数据契约**
  内容：ResearchQuestion/Claim/Evidence/SourceVersion/Relation/Judgment/History/ResearchRun 的字段、ID、draft/confirmed/invalidated 转换规则。
  出口条件：文档获确认，能直接指导 D1 建模。
- [ ] **A6 设计②：Application command/query 清单与调用映射**
  内容：把 151 个 HTTP handlers、MCP tools、agent tools 映射到有限的用例集合（设计文档 §5.1 命令/查询表）。
  出口条件：每个现有入口都有映射目标；无覆盖的用例显式列入"暂不迁移"。
- [ ] **A7 设计③：统一 Job 状态机与迁移说明**
  内容：`TaskTracker`、`BatchJob`、APScheduler、worker heartbeat 如何收敛到 durable job；lease、cancel/retry/pause/resume、恢复语义。
  输入：审计报告 §2/§3/§6。
  出口条件：文档获确认，能直接指导 C1–C5。
- [ ] **A8 设计④：PM Research Terminal 架构**
  内容：Pi SDK adapter、capability metadata、确定性命令、permission profiles、主题、领域 renderer 与 fallback 契约。
  出口条件：文档获确认，能直接指导 E1–E6。
- [ ] **A9 设计⑤：HTTPS identity/token flow**
  内容：GitHub Web 登录、CLI device authorization、MCP OAuth discovery、PaperMind token 与本地模型 provider 凭据的边界。
  出口条件：文档获确认，能直接指导 E2/E7–E9 与 F5。

## Stage B — Phase 1：application command/query

阶段出口条件：Web、MCP 对同一能力调用同一个 application handler。

- [ ] **B1 application 层骨架**：建立 commands/queries 目录结构、handler 协议与依赖注入约定；repository/provider 只允许在 application 层内使用。
- [ ] **B2 只读切片①：SearchPapers + GetPaper**：对应 HTTP 路由改为调用 application handler，返回保持兼容，前端不动。
- [ ] **B3 只读切片②：GetResearchQuestion/ListClaims/GetClaimEvidence**：同上，覆盖研究状态读取面。
- [ ] **B4 MCP 工具改调 application handlers**：`apps/api/mcp.py` 工具不再直接引用 deps/service（审计 §1.6）。
- [ ] **B5 agent tools 改调 application handlers**：`packages/ai/tools/registry.py` 保留参数与返回语义，handler 业务下沉（设计文档 §5.5）。
- [ ] **B6 其余查询全量迁移**：按 A6 映射清单逐个推进，每批一个提交。
- [ ] **B7 命令面迁移**：ImportPaper/CreateResearchQuestion/StartSkim/StartDeepRead/StartEmbedding 等写路径走 application command，长任务入口统一提交 job（为 Stage C 铺路）。

## Stage C — Phase 2：durable jobs

阶段出口条件：API/worker 任意重启后，任务状态可解释、可恢复且不会静默丢失。

- [ ] **C1 batch consumer 移出 API 进程**：API lifespan 不再启动任务消费（审计 §1.5，现仅 API 进程消费 `batch_jobs`，worker 不参与）。
- [ ] **C2 job 状态持久化**：统一 job store 落库，取代内存 `TaskTracker`（10 分钟 TTL、重启即丢）与心跳文件的权威地位；前端三套轮询端点（`/tasks/active`、`/tasks/{id}`、`/ingest/references/status`）收敛到统一 job 查询。
- [ ] **C3 scheduler 只入队**：APScheduler 触发后只提交 job，由 executor 领取执行；不再进程内直跑。
- [ ] **C4 控制语义**：实现 cancel/retry/pause/resume REST 端点 + lease/心跳续约/超时（当前无任何 cancel 端点，取消仅翻转标志不中断线程——审计 §6）。
- [ ] **C5 崩溃恢复**：替换 `recover_stale_running` 的"running 一律置 failed"破坏性恢复，改为 lease 过期后可重入；同一 paper 不再被多路径并发处理（幂等键）。

## Stage D — Phase 3：Research State 垂直切片

阶段出口条件：同一 Claim 能从 Web/API 追溯到精确证据、生成活动和历史版本；无证据坐标的模型输出不进入 confirmed 状态。

- [ ] **D1 数据契约落地**：按 A5 设计建模 + migration。
- [ ] **D2 样本迁移**：迁移 A4 的预置研究问题与少量论文，不批量回填历史数据。
- [ ] **D3 ResearchRun 生成待验证 Claim**：强制证据坐标与完整 provenance（source version、任务、时间、模型、策略版本）。
- [ ] **D4 查询实现**：GetResearchQuestion、ListClaims、GetClaimEvidence、DiffResearchState。
- [ ] **D5 Research Object 基础导出**：至少 JSON + Markdown，含校验值与 provenance 摘要。
- [ ] **D6 领域事件**：append-only outbox/event log 记录 Claim 与 SourceVersion 的关键状态变化（设计文档 §4.7 事件表）。
- [ ] **D7 confirmed 规则落地**：author/PaperMind/user 判断来源区分；无证据输出只能 draft/pending verification。

## Stage E — Phase 4：PM Research Terminal 与 MCP 一等化

阶段出口条件：不打开 Web，也能在 `pm` 终端和确定性命令中完成搜索、查看 Claim/Evidence、比较研究状态、触发处理、查看进度、取消任务和导出。

- [ ] **E1 `@papermind/cli` 骨架**：TypeScript/Node 包，同进程嵌入 Pi SDK，加载 PaperMind extension；`pm` 无参数进入交互终端，`pm -p` 一次性调用。
- [ ] **E2 远程登录**：`pm login --endpoint`，PaperMind token 与本地模型 provider 凭据分开保存/撤销。
- [ ] **E3 确定性子命令 + `--json`**：查询面优先（papers/questions/claims/evidence/diff/export），稳定退出码，无 ANSI 污染。
- [ ] **E4 capability metadata**：HTTP、Pi tools、CLI commands、MCP tools 复用同一 schema/scope/risk/async 语义（设计文档 §5.1/§3.2）。
- [ ] **E5 领域 renderer 与主题**：Paper/Claim/Evidence/Research Diff/Job/Research Pack 卡片，`papermind-dark/light`，非 TTY 退化为 Markdown/plain text。
- [ ] **E6 permission profiles**：默认 research profile；`--workspace`/`--coding` 显式开启；destructive 动作需服务端 policy + 终端确认双重把关。
- [ ] **E7 MCP 远程化**：唯一 transport 为公网 HTTPS Streamable HTTP；OAuth protected resource metadata、token audience/scope 校验；resources 与 tools 划分。
- [ ] **E8 MCP 凭据升级**：静态 token 改为可撤销、可轮换、分 scope 的凭据。
- [ ] **E9 CLI device authorization**：PaperMind 自己签发一次性 device code，浏览器完成上游登录；CLI 只拿 PaperMind token，上游 provider token 不下发。

## Stage F — Phase 5：前端瘦身与 Demo

阶段出口条件：个人站与 Demo 数据完全隔离；Demo 在模型不可用时仍能展示完整预计算流程。

- [ ] **F1 删除无关入口与重复状态管理**（含审计发现的前端可经 `POST /tasks/track` 在服务端内存"造任务"这类口子）。
- [ ] **F2 Web 只调 application API**。
- [ ] **F3 生产构建内嵌或反代提供**：删除独立前端容器（compose 中的 nginx 服务）。
- [ ] **F4 Demo 独立实例**：独立数据库、文件卷、配置与模型额度；取代 2026-05-08 旧 Demo 方案。
- [ ] **F5 GitHub 登录 + 临时身份**：最小身份映射、TTL 清理、用户/IP/全局三维限额。
- [ ] **F6 三段式演示旅程**：匿名看 Claim/Evidence → 登录看研究状态变化 → `pm login` + `pm demo` 复现并导出 Research Pack。

## Stage G — Phase 6：语言与存储决策门

- [ ] **G1 重测资源基线**：对照 A2 记录，定位剩余成本来源（Python control plane / 重依赖 / 数据库 / 具体任务）。
- [ ] **G2 决策记录**：是否迁移 Go control plane；个人服务用 SQLite 还是 PostgreSQL。出口条件：任何迁移都有测量证据和独立回滚路径，否则维持现状。

## 变更记录

- 2026-09-02：建立路线图；完成 A1 审计。
