# PaperMind 2026 形态与重构设计

状态：**设计基线，待实施**

日期：2026-09-02

适用范围：个人阿里云服务、可选完整 Web、公开 Demo、本地 PM UI、PM Research Terminal、远程 MCP 客户端

## 执行摘要

PaperMind 在 2026 年不应继续以“功能不断增加的 AI 论文网站”为主要形态，而应重构为一个**部署在个人服务器上的、provenance-first 的研究记忆与任务运行时**。论文是输入，Claim、Evidence、研究判断及其演化历史才是长期资产；可选完整 Web、本地 PM UI、PM Research Terminal 和 MCP/AI Agent 是面向不同场景的客户端。

本轮不把 PaperMind 商业化，也不建设多租户 SaaS。实际运行边界是：一套经过认证的个人服务部署在现有阿里云和域名下，供本人从不同电脑远程使用；同一台服务器额外运行一个公开、极简的 Demo。Demo 允许访客先匿名浏览预计算样例，再通过 GitHub 登录获得临时、严格限额的体验空间，并用同一身份从 `pm` CLI 连接。Demo 必须拥有独立数据库、文件卷、配置和模型额度，不能接触个人研究数据。

`pm` 采用以 Pi 为上游、由 PaperMind 维护的 downstream terminal distribution：无参数进入 PaperMind 研究 AI 终端，传统子命令保持确定性和可脚本化，`--json` 提供无损机器输出。PaperMind 可以裁剪、改造和重新组合 Pi 的 agent core、TUI、模型、session 与 compaction，但研究数据、权限、证据、任务与可信状态始终属于 PaperMind Core。终端拥有自己的主题和 Paper/Claim/Evidence/diff/job 专用渲染。[24]

现有 Web 不整体删除，而是保留为可选的 Full Web 模块，并逐步适配新的 Research State。与此同时，`pm ui` 在本地启动一个随 CLI 分发的轻量浏览器 UI，通过 loopback bridge 和公网 HTTPS 连接远程 Core；它只保留 PDF/证据对照、Claim 工作台、Research Diff 和任务监控等适合图形界面的高价值交互，不携带本地业务后端或数据库。

重构的优先级是先建立稳定的 application command/query、presentation model 和原子化 durable execution 边界，再让 Full Web、Local UI、PM Research Terminal、MCP 复用它们。长流程不再由某个 Worker 一次性包办，而被表达为 `Job → Task → Attempt → Artifact/Event`：Job 表达用户意图，Task 是可独立领取、重试、取消和审计的工作原子，Attempt 记录每次真实执行。Worker 本身退化为可替换的无状态 Executor。先拆职责、拆依赖并测量资源，再决定是否将轻量服务端控制面迁移到 Go；当前不进行 Python 全量重写。

目标结果：**个人服务可长期稳定运行，公开 Demo 能在一分钟内展示 PaperMind 如何把论文转化为可验证、可演进的研究认知；本地电脑无需安装完整后端，即可通过 `pm`、`pm ui` 或 MCP 使用同一远程研究状态。**

## 1. 背景与已确认边界

### 1.1 已确认目标

- PaperMind 的主要实例部署在个人阿里云服务器上。
- 服务通过现有域名和 HTTPS 从公网访问，不依赖 Tailscale。
- 所有外部 Web、PM Research Terminal 和 MCP 流量都通过 HTTPS；不使用 SSH、SSH tunnel 或本地子进程作为 PaperMind 连接方式。
- 服务主要供本人使用，不做注册、付费、团队协作或商业化运营。
- 本地电脑是远程客户端，不保存或同步服务端数据库。
- 需要一个公网 Demo 网页，但它只展示少量最有代表性的能力，并让访客实际体验远程 PM Research Terminal。
- Demo 使用第三方身份登录；第一版选择 GitHub，微信作为后续可插拔 provider。
- 当前工作的重点是重构业务和运行边界，不是继续扩充页面。
- 现有 Web 不整体删除；它作为可选 Full Web 模块继续存在，新 Research State 能力必须提供对应 Web 适配。
- `pm ui` 是随 CLI 分发的本地轻量 UI，面向高效率证据阅读和 Claim 操作，不保存服务端数据库副本。
- 无任何 Web 部署时，PM Research Terminal 和 MCP 仍能完整访问核心能力。
- `pm` 是以 Pi 源码为上游、由 PaperMind 维护的第一方 Research AI Terminal distribution，而不是在 Python CLI 外再启动一个临时聊天子进程。
- `pm` 同时保留交互 AI、确定性子命令和 `--json` 三种入口；AI 体验不能取代自动化接口。
- PaperMind 凭据与模型 provider 凭据严格分离；个人交互推理默认在本地 Pi，服务端负责研究数据和 durable jobs。
- PaperMind 终端拥有自己的主题、卡片和渐进式详情展示，使 Paper、Claim、Evidence、diff 与 job 在终端中可读、可定位、可操作。
- 所有长流程采用 `ResearchRun → Job → Task → Attempt → Artifact/Event` 分层；原子化对象是 Work Unit，不是 Worker 容器或 Python 函数。
- Scheduler 只创建 Job，Workflow Planner 展开 Task，Dispatcher 分派，Executor 每次执行一个 Task Attempt，Reconciler 负责 lease 过期与恢复。

### 1.2 明确不做

- 不做通用多租户 SaaS、团队 workspace、计费和订阅；Demo 只保留实现隔离与限额所需的最小用户记录。
- 不允许访客长期存储自己的论文库；Demo 数据按 TTL 自动清理。
- 不把个人服务与公开 Demo 共用数据库或文件目录。
- 不把数据库文件同步到本地电脑，也不允许客户端直连数据库。
- 不把物理 worker 的重启、扩缩容权限暴露给 Demo 访客。
- 不在本轮全量重写约 2.9 万行 Python 业务代码。
- 不以完整复刻现有所有页面作为 Demo 或 Local UI 目标。
- 不因前端瘦身而直接删除仍有价值的现有页面；先完成 route/capability 盘点，再按部署 profile 保留或归档。
- 不对 Pi 做无边界复制和随意改写；PaperMind 维护可追溯 downstream fork、上游版本基线和有限 patch stack，保留 MIT copyright/license notice。[24]
- 不让 Pi 的默认 coding tools 自动获得 PaperMind 服务端权限，也不通过 `bash`、SSH 或 Docker 命令控制服务器 worker。
- 不按每个 Task 建一个微服务或常驻 Worker；部署隔离只在资源、安全或依赖确有差异时引入。
- 不承诺跨数据库、模型 provider、邮件和外部下载的全局 exactly-once；采用至少一次执行、幂等副作用和完整 Attempt 记录。

## 2. 当前实现审计

2026-09-02 的仓库快照约有 28,944 行 Python、23,474 行 TypeScript/TSX，共 151 个 HTTP route handler。数字只用于说明当前迁移规模，不作为长期指标。

当前资源和复杂度问题不能简单归因为 FastAPI：

- API 与 worker 复用同一个后端镜像，镜像同时安装 LLM、PDF 和 graph extras；graph extras 包含 NumPy、scikit-learn 和 UMAP。[1]
- SQLite 配置下，Compose 仍要求 PostgreSQL 服务启动；backend 和 worker 各预留 512 MB、上限 2 GB。[2]
- API lifespan 内启动 batch consumer，因此请求入口同时承担任务消费职责。[3]
- `apps/api/deps.py` 在模块加载时构造 Pipeline、RAG、Brief 和 Graph service 单例。[4]
- 前端承担大量轮询和任务状态拼装，任务状态又分散在进程内 tracker、`batch_jobs` 表和 worker 心跳文件中。
- 现有 Worker 内的 APScheduler 会直接执行 topic ingest、daily brief、graph maintenance 和 idle processing，而 `batch_jobs` 又只由 API 进程消费；当前不存在统一的执行原语。[3][19]
- MCP 已能查询论文并触发部分任务，但作为 FastAPI 子应用挂载，工具定义直接引用 API deps 和具体 service。[5]

因此，当前的首要问题是**职责、依赖与状态边界**，而不是 Python 语法或 FastAPI 框架本身。

## 3. 产品形态

### 3.1 总体模型

```text
                              公网 HTTPS
                                   │
        ┌──────────────────┬───────┼───────────────┬────────────────┐
        │                  │       │               │                │
  Full Web / Demo       pm ui      pm        Claude/Codex      other clients
   optional remote   local bridge  terminal     MCP client       HTTPS API
        │                  │       │               │                │
        └──────────────────┴───────┼───────────────┴────────────────┘
                                   │
                    PaperMind Core API
              command/query · auth · job control
                              │
             ┌────────────────┼────────────────┐
             │                │                │
          Database        Object/PDF     Durable Job Store
             │                              Task Queue
             └────────────────┬────────────────┘
                              │
             Planner · Dispatcher · Reconciler
                              │
                    Stateless Executors
                 PDF · LLM · embedding · graph
```

核心原则是：

> 服务器拥有数据和任务；客户端只表达查询、命令与展示需求。

服务器保存的也不只是“论文和 AI 输出”，而是可被重新计算、审计和迁移的研究状态：

```text
ResearchQuestion
├── Claim
│   ├── Evidence → SourceVersion → page/section/figure/table
│   ├── Relation → supports/contradicts/conditional/supersedes
│   ├── Judgment → author / PaperMind / user
│   └── History → created/revised/invalidated
├── ResearchRun → inputs/model/prompt/artifacts
└── Action → watch/read/verify/run/export
```

> AI answer是一种视图，不是事实来源；可追溯的 Claim、Evidence 和 History 才是事实层。

### 3.2 四种一等客户端形态

#### 可选 Full Web

现有 React/Vite Web 不整体删除。它继续承载 PDF 阅读、完整论文管理、证据对照、批量选择、图谱、历史数据和需要大画布的高级功能，但从“PaperMind 必选入口”调整为“可选 Full Web 模块”。

目标部署 profile：

```bash
papermind-server serve --web=full      # Core + MCP + 可选完整 Web
papermind-server serve --web=demo      # 独立 Demo 实例的精简公开页面
papermind-server serve --web=none      # Core + MCP，无服务端 Web
```

`papermind-server` 仅表示服务端部署入口的目标语义，最终命令名可在实现设计中确定；它不属于分发给普通客户端的 `pm` 包。生产构建可以由 Core 或同一反向代理提供，不要求常驻的独立前端容器。

Full Web 的保留原则：

- 先建立现有 route/capability inventory，标记 `retain`、`merge`、`local-ui`、`archive`，禁止直接批量删除。
- 新的 ResearchQuestion、Claim、Evidence、History、Diff 和 Job 必须提供 Web adapter；不能只在 CLI 中实现。
- 现有页面逐步改为调用 application API，不继续维护浏览器专属业务编排。
- Full Web 可以展示比 Local UI 更完整的管理和可视化能力，但不得形成另一套领域状态。
- 未启用 Full Web 时，Core、Local UI、终端和 MCP 的功能与数据不能受到影响。

#### PM Research Terminal

`pm` 是以 Pi 源码为上游的 PaperMind 专用发行版。它保留 Pi 的包边界，在同一个 Node.js/TypeScript 进程内组合命令解析、agent session、PaperMind tools、主题和领域 renderer；PaperMind 可以裁剪 coding-oriented 产品功能并改造 TUI，但不通过 Python 包导入服务端 AI、PDF 或数据库模块，也不通过子进程 RPC 作为长期架构。[6][25]

它同时提供三种互补模式：

```bash
pm                                      # 进入交互式 Research AI Terminal
pm -p "最近一周哪些结论发生了变化？"    # 一次性 AI 调用
pm claims list --question <question-id> # 确定性、可脚本化子命令
pm claims list --question <question-id> --json
```

原则是：

> **AI-first，CLI-complete。**自然语言是主要交互方式，但任何核心能力都保留稳定命令、退出码和机器可读结果。

本地电脑只保存 endpoint、PaperMind 凭据、Pi session 和本地模型 provider 凭据。PaperMind 访问和模型访问是两个独立信任域：

- `pm login --endpoint ...` 获取 PaperMind 自己签发的 token。
- Pi/provider 登录只用于本地模型调用，provider token 默认不上传 PaperMind。
- 个人交互推理优先在本地 Pi 完成，远程 Core 返回受权限控制的研究上下文并执行长任务。
- 公开 Demo 可以使用预计算内容与严格限额的服务端推理，不强迫访客配置模型 provider。

PM Research Terminal 不通过 SSH 登录服务器，不执行远程 shell，也不要求用户配置 tunnel。所有 PaperMind tool call 都通过相同的公网 HTTPS application API。

##### 确定性命令面

```bash
pm login --endpoint https://pm.example.com
pm inbox
pm papers search "speaker diarization"
pm paper show <paper-id> --format md
pm questions show <question-id>
pm claims list --question <question-id>
pm evidence show <claim-id>
pm diff --question <question-id> --since 30d
pm export <question-id> --format research-pack
pm brief today
pm ask "最近收录的工作有哪些相互矛盾的结论？"

pm jobs list
pm jobs logs <job-id> --follow
pm jobs cancel <job-id>
pm jobs retry <job-id>
pm queue pause
pm queue resume
```

第一版同时支持版本化 TypeScript/Node 包（例如 `@papermind/cli`）和基于上游构建流程的 standalone executable。服务端是否迁移 Go 与终端采用 Pi downstream fork 是两个独立决策。

##### Pi downstream fork policy

推荐在独立仓库维护 `PaperMind-Terminal`，而不是把完整 Pi 源码复制进 PaperMind 服务端仓库：

```text
earendil-works/pi <upstream>
        │ pinned release/tag
        ▼
PaperMind-Terminal <downstream fork>
├── upstream-compatible core packages
├── ordered PM patch stack
├── PaperMind product profile
├── PaperMind themes/renderers
└── pm release pipeline
```

维护准则：

- 保留完整 Git 历史、MIT copyright/license notice 和第三方 notices。[24]
- 为每次 PM release 记录上游基线、patch 清单和未合并的安全修复。
- 优先通过 product profile 和 build pruning 隐藏或移除功能，只有确认长期不需要时才 source pruning。
- 优先修改 coding-agent 产品层和 TUI 层；除非扩展点无法满足需求，不改变底层模型协议、agent event schema 和 session format。
- 对上游同步运行 agent loop、session、provider、TUI snapshot 和 PaperMind renderer 契约测试。
- 二创终端可以独立演化，但不得成为 Research State、权限、job 或 provenance 的事实来源。

##### Pi extension 与 capability adapter

PaperMind extension 负责把远程能力注册为 Pi tools、commands 和渲染器。Pi 支持 extension 注册工具、命令、事件、确认 UI 和自定义结果渲染，也允许关闭默认 tools 后只加载产品自己的受控工具集。[19]

extension 不直接导入 Python 或访问数据库：

```text
Pi Agent Session
    │
    ├── @papermind/pi-extension
    │     ├── typed HTTPS client
    │     ├── auth/session adapter
    │     ├── Paper/Claim/Evidence renderers
    │     └── permission + confirmation UI
    │
    └── PaperMind Core application API
```

application 层维护稳定的 capability metadata，至少包括：

```json
{
  "name": "compare_claims",
  "kind": "query",
  "risk": "read_only",
  "required_scope": "research:read",
  "supports_async": false,
  "input_schema": {},
  "output_schema": {},
  "render_hint": "claim_comparison"
}
```

HTTP、MCP、Pi extension 和确定性 CLI 都从同一 capability contract 派生 adapter，但各自可以保留适合其交互方式的呈现。Pi RPC 只作为跨语言原型、测试或未来嵌入其他 UI 的备用路径，不作为 `pm` 主进程架构。[20]

##### PaperMind 终端主题与领域渲染

终端不是把 API JSON 涂上颜色，而是为研究对象建立稳定视觉语法：

- **Paper Card：**标题、作者、年份、来源、版本、阅读状态和短 ID。
- **Claim Card：**结论正文、状态、判断来源、置信/争议提示和 evidence 数量。
- **Evidence Card：**论文、页码、section/Figure/Table、短引用、证据方向与“在 Web 中打开”。
- **Research Diff：**新增、加强、削弱、冲突、取代和失效的 Claim，并解释变化原因。
- **Job View：**阶段、进度、耗时、成本、重试、错误和结果引用。
- **Research Pack View：**将要导出的对象、文件、校验值和 provenance 摘要。

默认提供 `papermind-dark` 与 `papermind-light`，允许用户安装或编写 Pi theme；Pi 支持从全局目录、项目目录、package、settings 或 CLI 参数加载自定义主题。[23] 渲染规则必须满足：

- canonical tool result 始终是结构化数据；主题和 renderer 只负责显示，不能改变业务语义。
- TTY 中使用卡片、折叠和增量进度；pipe 或不支持 TUI 时自动退化为清晰 Markdown/plain text。
- `--json` 输出不包含 ANSI、装饰文本或截断后的展示副本。
- 颜色不能是唯一状态信号；窄终端必须保留 Claim 状态、证据坐标和错误信息。
- Evidence 链接应打开个人或 Demo 域名下经过鉴权的精确证据位置，不暴露内部文件路径。

##### 权限 profile

Pi 原本面向 coding 场景，PaperMind 不默认继承完整本地和远程权限：

```bash
pm                    # 默认 research profile：PM tools + 安全的本地导出
pm --workspace .      # 增加当前目录范围内的研究文件读写
pm --coding           # 用户显式开启完整 coding tools
```

- Demo 禁止 `--coding` profile 和任意本地上传/远程执行工具。
- destructive 或高成本 PaperMind command 同时需要服务端 policy 校验和终端确认；仅有本地 UI 确认不能绕过服务端权限。
- Worker 只通过 `cancel/retry/pause/resume/drain` 等受控 application commands 管理，不能通过 Pi `bash` 转化成 SSH/Docker 控制。
- 工具结果必须限制大小并支持分页/资源引用，避免把整篇 PDF 或超长日志直接注入模型 context。

Demo CLI 应提供一个有起点、有反馈、有结束的引导命令：

```bash
pm login --endpoint https://demo.pm.example.com
pm demo
```

`pm login` 从 PaperMind HTTPS endpoint 获取一次性 device code，提示用户在浏览器打开 `https://demo.pm.example.com/activate`。用户完成 GitHub 登录并确认授权后，CLI 继续通过 HTTPS 轮询 PaperMind，最终得到 PaperMind 自己签发的短期 token。GitHub 官方将 device flow 明确用于 CLI 等 headless 应用，但 PaperMind 不应把 GitHub access token 下发给 CLI 或当成自己的 API token。[12]

`pm demo` 使用登录用户的临时 Demo 空间依次执行：查看一个 ResearchQuestion、展开 Claim 与精确 Evidence、发起一次受限分析、观察 job 进度、查看研究状态 diff、导出 Research Pack。它既是产品演示，也是 CLI 的可执行教程。

#### Local PM UI

`pm ui` 不是简单打开服务器上的 Full Web，而是在本地启动随 `pm` 分发的轻量 UI 和短生命周期 loopback bridge，再用浏览器打开。它面向终端不适合承载、但又不值得部署完整 Web 的高信息密度任务。

```bash
pm ui                                      # 打开本地研究工作台
pm ui --question <question-id>             # 进入指定 ResearchQuestion
pm ui --claim <claim-id>                   # 展开 Claim 与 Evidence
pm ui --job <job-id>                       # 查看实时任务状态
pm ui --no-open                            # 只启动并打印本地地址
```

```text
Browser
  │ http://127.0.0.1:<ephemeral-port>
  ▼
pm loopback bridge
  ├── serves bundled Local UI assets
  ├── holds PaperMind token in process memory
  ├── validates local session/origin/CSRF
  └── proxies only allowlisted application calls
            │ HTTPS
            ▼
       PaperMind Core
```

Local UI 不运行 PaperMind 业务后端，不保存数据库副本，不在浏览器 localStorage 中保存长期 bearer token。bridge 仅绑定 `127.0.0.1`/`::1` 的随机可用端口，校验 Host/Origin/CSRF，并使用一次性启动 nonce 建立本地 session；关闭 `pm ui` 后销毁内存凭据和本地 session。所有远程数据请求最终仍通过 HTTPS 到个人或 Demo Core。

第一版 Local UI 只保留五类高价值界面：

- PDF 与 Evidence 并排定位。
- Claim 工作台：状态、来源、关系、确认与修订。
- Research Diff：研究状态在时间轴上的变化。
- Job Monitor：进度、日志、成本、失败和重试。
- Research Pack：预览、选择与导出。

不在 Local UI 首版复制完整设置后台、订阅配置、邮件管理、全部 ingestion 页面或通用写作平台。终端中的 `open`/`o` 动作应能深链到当前 Paper、Claim、Evidence 或 Job；Local UI 的操作结果也应立即反映到终端、Full Web 和 MCP 查询中。

Local UI 与 Full Web 可以共享：

```text
@papermind/client          typed HTTPS client + auth types
@papermind/presentation    canonical Paper/Claim/Evidence/Job view models
@papermind/ui-core         accessible React primitives + domain components
```

两者拥有不同的信息架构和 route 集合，不共享页面级业务状态。共享包不能导入服务端 repository、Python handler 或 Pi 私有 session 类型。

#### MCP

MCP 是同一 application API 面向 AI Agent 的适配器，不另写业务逻辑：

- 唯一产品 transport 是基于公网 HTTPS 的 Streamable HTTP。
- 个人实例与 Demo 分别提供固定的 `https://<domain>/mcp` endpoint。
- 不向用户提供 SSH、SSH tunnel、本地 transport 或“本地启动 MCP server”的连接说明。
- 论文、简报和分析报告优先表示为 resources。
- skim、deep read、导入、重试和取消等副作用表示为 tools。
- PDF、证据表和任务监控后续可按需提供 MCP Apps 视图。

MCP 当前规范允许使用 Streamable HTTP；公网端点应使用 HTTPS、认证并正确校验 Origin。[7] PaperMind 不因为规范支持其他 transport 就将它们纳入产品路径。MCP Apps 支持将 PDF、图表、表单和实时状态作为渐进式 UI 嵌入兼容客户端，不支持 UI 的客户端仍可退化为文本结果。[8]

远程 MCP 必须实现标准授权发现。PaperMind MCP 是 OAuth protected resource，通过 well-known metadata 声明 authorization server，并校验 token audience、有效期与 scope。[11] GitHub 或微信只是 PaperMind 登录页背后的上游身份提供方；AI 客户端最终拿到的是 PaperMind token，而不是上游 provider token。

PaperMind 内部 job 模型不能依赖某一版 MCP Tasks。2026-07 的 MCP Release Candidate 仍在调整 task lifecycle，因此 MCP Tasks 只能作为外层 adapter。[9]

### 3.3 跨界面适配契约

“所有新功能都要适配”指语义一致，而不是要求四个界面像素级同构。每项新增 capability 在进入实现前必须声明 surface contract：

```json
{
  "capability": "get_claim_evidence",
  "surfaces": {
    "terminal": "claim_evidence_renderer",
    "local_ui": "ClaimEvidencePanel",
    "full_web": "ClaimEvidenceWorkspace",
    "mcp": "resource",
    "json": "ClaimEvidenceResult"
  }
}
```

| 界面 | 主要职责 | 适配要求 |
| --- | --- | --- |
| PM Research Terminal | 自然语言、确定性命令、批处理、快速查看 | 每个核心 capability 有 tool/command 与可读 fallback |
| Local PM UI | 高效证据阅读、Claim 操作、diff 和 job | 只实现高价值图形交互，必须使用 canonical presentation model |
| Full Web | 现有完整功能、历史兼容、高级管理与大画布 | 可选部署，但新 Research State 必须可读写和可追溯 |
| MCP | 外部 Agent 的标准调用入口 | 提供结构化 resource/tool，不依赖任何 UI |
| Demo profile | 一分钟价值展示和受限体验 | 从上述能力挑选垂直切片，不形成独立业务逻辑 |

跨界面必须共享对象 ID、状态机、权限、幂等键和 provenance。允许界面隐藏不适合自己的操作，但不允许同一个 Claim 在不同界面拥有不同状态或解释。

## 4. 2026 重构准则与目标能力

### 4.1 从 Paper-centric 转向 Evidence-native

PaperMind 的领域模型不再以“论文及其摘要”为终点：

- `Paper` 和 `SourceVersion` 是来源；必须保留 DOI/arXiv ID、版本、获取时间与内容校验值。
- `Claim` 是可比较、可修订的最小研究判断，不等同于一段自动摘要。
- `Evidence` 必须指向精确原文位置、图、表、公式、数据或实验结果。
- `Relation` 表达支持、反驳、部分支持、条件成立、复现失败和取代关系。
- `Judgment` 明确区分作者陈述、PaperMind 推断和用户判断。
- `ResearchQuestion` 聚合相关 Claim，形成某个问题当前的研究状态。
- `ResearchRun` 记录输入、模型、prompt/策略版本、时间、成本和产物引用。

Summary、Research Pulse、问答和写作输出都由这些对象生成。它们可以缓存，但不能成为唯一事实副本。

### 4.2 Provenance 是数据要求，不是 UI 装饰

每个重要 Claim 和生成结果至少能够回答：

- 来自哪一个 source version，以及具体页、段、图或表。
- 由哪个任务在什么时间产生，使用了哪些输入和策略版本。
- 哪些内容是原文事实，哪些是模型推断，哪些经过用户确认或修改。
- 当前版本由什么旧版本派生，为什么被更新、取代或失效。

内部模型可借鉴 W3C PROV 的 Entity、Activity、Agent 及 `used`、`wasGeneratedBy`、`wasDerivedFrom` 关系，但第一阶段不要求完整引入 RDF。[15]

硬性规则：

> 没有证据坐标的 AI 判断只能进入草稿或待验证状态，不能成为已确认研究事实。

### 4.3 时间、变化与不确定性是一等对象

PaperMind 必须能回答“现在认为是什么”以及“为什么和以前不同”：

- 跟踪论文新版本、勘误、撤稿、后续工作和用户判断变化。
- 保存 Claim 的创建、修订、取代和失效历史。
- 支持主题 watch、时间范围 diff 和变化原因解释。
- 显式表达 unknown、insufficient-evidence、conflicted 和 conditional，而不是强行生成确定答案。

目标交互包括：

```bash
pm watch "audio-visual diarization"
pm diff --since 30d
pm claims history <claim-id>
```

### 4.4 开放、可迁移、无锁定

用户应能导出完整 Research Object，而不只是聊天文本：

- 原始书目信息、SourceVersion、Claim、Evidence、Relation 和用户 Judgment。
- Markdown、JSON、BibTeX/CSL-JSON 等常用格式。
- 关联论文、数据集、代码、工作流、prompt/策略版本和执行产物。
- 可验证的文件校验值和 provenance 记录。

长期导出结构应与 RO-Crate 兼容，使论文、数据、代码、工作流和 provenance 能组成可携带研究对象。[16] 文献管理层优先考虑 Zotero 双向同步；Zotero Web API 已提供读写、全文、同步、streaming 和 OAuth 能力。[17] DOI 与出版状态元数据通过 Crossref 等标准服务规范化，而不是让每个采集器形成私有格式。[18]

### 4.5 Durable Agent，而不是无限自治

Agent 能够发现变化、建议下一步并提交受控任务，但不能绕过 application commands、权限和审计：

- 所有长任务进入 durable execution system，由持久 Job 展开为原子 Task，并支持进度、取消、重试、恢复和幂等。
- 每个任务具备 scope、资源预算、模型预算、并发和超时策略。
- 自动 watch 可以产生候选 Claim 或待验证事项，不直接覆盖用户确认的研究判断。
- 删除、发布、明显增加成本和改变 confirmed Claim 的动作必须经过对应权限或批准。
- Full Web、Local UI、PM Research Terminal、MCP 观察和控制的是同一个任务与研究状态。

MCP 的协议核心可以无状态，PaperMind 应用本身必须持久化任务与研究状态；不能把 durability 寄托在客户端 session 上。[9]

### 4.6 多模态证据与质量评估

PDF 与多模态能力的目标不是“描述一张图”，而是把证据纳入研究判断：

- Claim 可精确关联 Figure、Table、公式、实验条件和数值。
- 能比较跨论文指标，同时保留数据集、metric、protocol 和实验条件差异。
- 能检查正文陈述与表格数值是否一致，并标记无法可靠解析的内容。
- 每次 Research Run 检查引用覆盖、evidence entailment、反例遗漏、数值一致性和来源完整度。
- 质量结果必须可展开解释，不能只给一个缺少依据的总分。

### 4.7 语义事件流

系统应在 application 层产生稳定的领域事件，例如：

```text
SourceAdded
SourceVersionDetected
EvidenceExtracted
ClaimProposed
ClaimConfirmed
ClaimRevised
ClaimInvalidated
RetractionDetected
ResearchRunCompleted
JobFailed
```

事件用于驱动 History、`pm diff`、watch 通知和外部集成。第一阶段可以使用关系数据库中的 append-only event/outbox 表，不要求立即引入专用 event streaming 基础设施。

### 4.8 能力优先级

| 优先级 | 能力 | 本轮要求 |
| --- | --- | --- |
| P0 地基 | ResearchQuestion/Claim/Evidence/SourceVersion/Relation/History 数据契约 | 先设计、迁移一个垂直切片 |
| P0 地基 | provenance、证据坐标、author/PM/user 判断区分 | 所有新 Research Run 强制遵守 |
| P0 地基 | 原子 durable execution、commands/queries、领域事件 | Job/Task/Attempt/Artifact 统一，所有客户端共用 |
| P0 地基 | Research Object 基础导出和 source versioning | 至少支持 JSON + Markdown |
| P0 地基 | Pi downstream Research Terminal、确定性命令、`--json` 与 permission profiles | 作为第一方 CLI 唯一路线 |
| P0 地基 | canonical presentation model 与 surface contract | 所有新 capability 在实现前声明适配面 |
| P1 差异化 | watch/diff、冲突与条件建模、多模态证据、质量评估 | 进入个人服务与 Demo 主路径 |
| P1 差异化 | Zotero 同步、Crossref 规范化、个人研究策略 | 在 P0 接口稳定后接入 |
| P1 差异化 | Paper/Claim/Evidence/diff/job 专用 renderer、Local UI 与 PaperMind themes | 进入终端、本地工作台与 Demo 主路径 |
| P2 扩展 | 自动假设与任意实验、多人实时协作、学术社交、完整写作平台 | 不进入本轮重构关键路径 |

### 4.9 产品路线约束

PaperMind 不选择“AI Zotero++”作为终局，也不直接跳到不受控的 Autonomous Scientist。目标路线是：

> **Evidence-native Research OS：一个供人和 Agent 共同使用的、provenance-first 的研究记忆。**

自动科研能力只有建立在可验证 Evidence、持久化 Research State 和权限边界之上，才允许逐步增加。

## 5. 目标后端边界

### 5.1 Application 层是唯一能力入口

所有客户端复用同一组 commands 和 queries：

```text
Queries
├── SearchPapers
├── GetPaper
├── GetResearchQuestion
├── ListClaims
├── GetClaimEvidence
├── DiffResearchState
├── GetDailyBrief
├── GetJob
├── ListJobs
└── ExportResearchObject

Commands
├── ImportPaper
├── CreateResearchQuestion
├── ProposeClaim
├── ConfirmClaim
├── ReviseClaim
├── CreateWatch
├── StartSkim
├── StartDeepRead
├── StartEmbedding
├── CancelJob
├── RetryJob
├── PauseQueue
└── ResumeQueue
```

HTTP router、deterministic CLI command、Pi tool、Local/Full Web action 与 MCP adapter 只负责：

1. 解析输入和鉴权。
2. 调用 application command/query。
3. 将 canonical result 转换为对应协议或 presentation model。

它们不得直接组合 repository、模型 SDK 和线程池。React components 和 Pi renderers 也不得自己重新推导 Claim 状态、证据关系或 job 生命周期。

### 5.2 原子化 Durable Execution

原子化的对象是 **Work Unit**，不是 Worker 进程，也不是任意一个 Python 函数。PaperMind 使用五层概念表达研究与执行：

```text
ResearchRun                         领域层：一次可追溯的研究活动
└── Job                             应用层：一个用户意图或计划流程
    ├── Task                        执行层：可独立调度和重放的工作原子
    │   ├── Attempt 1               运行层：一次领取、执行和失败记录
    │   └── Attempt 2
    ├── Task
    └── Artifact / Domain Event     结果层：可引用产物或持久领域变化
```

- `ResearchRun` 说明为何执行、使用哪些论文、模型、策略和输入，并连接 Claim/Evidence provenance。
- `Job` 表达 `StartSkim`、`DeepReadPaper`、`RunTopicResearch` 或 `BuildDailyBrief` 等用户意图，聚合整体状态和预算。
- `Task` 是调度、lease、取消、超时、重试和资源分派的最小持久单元。
- `Attempt` 记录某个 Executor 对 Task 的一次真实执行，包括时间、环境、错误、成本和 lease。
- `Artifact/Event` 是 Task 的输出引用；大结果进入 object storage，领域变化通过 application command 和 transactional outbox 提交。

#### Task 原子边界

一个 Task 必须同时满足：

- **单一有意义副作用：**一次只负责一种主要持久结果，例如登记一个 SourceVersion、解析一份 PDF、生成一次 embedding 或发送一封 brief。
- **独立可执行：**输入由不可变值或稳定 ID/reference 描述，不依赖某个进程的内存、当前目录或隐式调用栈。
- **独立可恢复：**可以被单独领取、超时、取消、重试和转入 dead-letter，不必重跑整个 Job。
- **重放安全：**具有稳定 idempotency key；重复 Attempt 不会制造重复 Paper、Claim、邮件或账单记录。
- **资源有界：**声明 timeout、最大重试、CPU/内存/GPU、网络、provider 和 concurrency class。
- **结果可观察：**输出 Artifact、领域事件或结构化错误；日志、成本、进度与 provenance 能定位到 Task 和 Attempt。
- **版本明确：**记录 capability name、handler version、input schema version 与 policy/model version，使历史任务可解释。

“原子”不等于“越小越好”。普通 helper、数据库查询或纯内存转换不单独建 Task。只有当一步工作值得被独立重试、隔离资源、观察进度或保留 provenance 时，才越过异步边界。

#### 执行语义

跨数据库、模型 provider、邮件和下载服务无法可靠承诺全局 exactly-once。PaperMind 的标准语义是：

> **至少一次执行 + lease fencing + 幂等副作用 + 持久 Attempt + transactional outbox。**

领取 Task 时生成 `lease_token/fencing_token`；只有当前 lease 的持有者能提交最终状态。lease 过期后 Reconciler 可以重新入队，迟到的旧 Attempt 不能覆盖新结果。数据库写入和 outbox event 在同一事务中提交；外部副作用使用 provider idempotency key、内容寻址结果或本地 effect ledger 去重。无法安全重放的 Task 必须标为 `manual_recovery`，不能自动重试。

Task 至少记录：

- `task_id`、`job_id`、capability、handler/schema version 和依赖关系。
- 输入引用、输出引用、幂等键、scope 与权限主体。
- priority、resource class、timeout、retry policy 和预算。
- `queued/leased/running/succeeded/failed/cancelled/dead_letter/manual_recovery` 状态。
- 当前 lease/fencing token、领取和到期时间。
- 每个 Attempt 的 Executor、开始/结束时间、错误分类、日志和成本引用。

#### Workflow 与 fan-out

第一阶段采用**代码定义、状态持久化的 Workflow 模板**，不建设通用可视化 DAG 平台。Planner 根据已完成 Task 和持久结果生成下一批 Task，支持顺序依赖、条件分支和按 Paper fan-out：

```text
RunTopicResearch
├── ResolveSubscription
├── FetchFeed(topic, cursor)
├── UpsertPaper × N
├── DownloadSourceVersion × N
├── ExtractDocument × N
├── SkimPaper × N
├── EmbedPaper × N
├── ProposeClaims × N
└── BuildBrief
```

单篇失败不会抹掉其他 Paper 的成功结果；父 Job 根据 workflow policy 决定继续、降级、部分成功或失败。只有在代码定义模板无法表达真实需求后，才评估持久化动态 DAG。

Job 的状态由子 Task 收敛而来，而不是由 Worker 任意写入：

```text
submitted → planning → queued → running → succeeded
                                  ├──────→ partially_succeeded
                                  ├──────→ failed
                                  └→ cancelling → cancelled
```

取消采用协作式语义：尚未领取的 Task 立即取消，运行中的 Attempt 收到 cancellation request 并在安全检查点退出；超过 grace period 后释放 lease，由 Reconciler 根据 Task 的副作用策略决定重试、失败或 manual recovery。已经提交且不可逆的 Artifact/Event 不回滚，而由补偿 Task 或新的领域事件修正。

#### 运行组件边界

```text
Scheduler          只按时间或事件创建 Job，不执行研究逻辑
Workflow Planner   将 Job 展开为当前可运行的 Task
Dispatcher         按依赖、优先级、资源和并发策略分派 Task
Executor           每次只执行一个 Task Attempt，并续约 lease
Reconciler         回收过期 lease、处理重试、死信与父 Job 收敛
```

API 只负责提交、查询和控制；它不消费 Task，也不启动线程池执行长工作。Executor 是无状态、可替换的运行载体，可以先是同一个 Python 进程池，未来再按 PDF、LLM、embedding、graph 或 GPU 资源类别拆部署。API 或 Executor 重启不得导致任务消失、重复提交领域结果或被静默判定完成。

### 5.3 Job、Task 与 Executor 控制语义

个人用户控制自己的研究意图和执行单元：

- `pause/resume queue`
- `cancel/retry job`
- `cancel/retry task`
- 查看 Job graph、Task/Attempt 进度、日志、成本、产物和错误

建议的确定性命令面：

```bash
pm jobs show <job-id>
pm jobs graph <job-id>
pm jobs cancel <job-id>
pm tasks retry <task-id>
pm tasks logs <task-id> --follow
pm executors list
pm executors drain <executor-id>
```

服务运维控制 Executor pool 和实际进程：

- `drain executor`：停止领取新 Task，允许当前 Attempt 收敛或在超时后释放 lease。
- `restart executor`：部署层操作，不改变 Job/Task 的事实状态。
- 查看 Executor capability、版本、lease、心跳、资源占用和失败率。

Worker 不再是产品层的稳定身份或任务事实来源；它只是 Executor 的部署载体。在个人部署中，研究控制与运维控制可以由同一个账号执行，但 API、scope 和审计语义仍需分开，避免将进程级操作暴露给 Demo。

### 5.4 Python 与其他语言

当前决策是：**不进行全量语言重写。**

第一阶段保留 Python 的领域逻辑、LLM、PDF、embedding 和 graph 实现，通过模块边界和延迟加载减轻 API。只有满足下列条件后才评估 Go Core：

- commands/queries 与 job 协议已经稳定。
- 有基线数据证明 Python 控制面的空闲内存、启动时间或发布方式是主要瓶颈。
- Go 迁移不要求重写 Python executor 内的研究业务。
- 迁移可逐个替换 gateway、scheduler，而不是一次性切换；PM Research Terminal 继续通过协议与服务端语言解耦。

目标可能是 Go control plane + Python executors，但它是测量后的结果，不是重构前提。

### 5.5 现有 Agent Harness 的迁移归属

当前 `packages/agent_core` 已实现流式 agent loop、确认流程、context compaction、tasks 和 subagents；`packages/ai/tools` 已实现 PaperMind tool registry 与 handlers。[21][22] 这些实现是本次边界重构的输入，不应原样复制到新的终端：

保留并迁移到 Core/application 层：

- PaperMind 领域工具的参数、返回语义和业务 handler。
- 服务端权限、确认 challenge、审计、成本记录和 durable job 语义。
- Research State、provenance 以及模型生成产物的验证规则。

交给 PaperMind 的 Pi downstream terminal：

- 本地交互 agent loop、TUI、模型 provider、session、compaction 和 tool rendering。
- slash commands、steering/follow-up、本地技能和终端主题。
- 用户确认的展示与输入；服务端仍负责最终授权。

迁移期间，现有 Python agent loop 可以继续服务 Full Web/Demo，直到对应 adapter 稳定。长期不再以 `packages/ai/tools/registry.py` 作为能力的唯一注册点，而由 application capability contract 分别生成或薄封装 HTTP、MCP、Pi terminal、Local UI 和 Full Web adapters。

## 6. 数据与部署模式

### 6.1 个人服务

个人服务是唯一真实研究数据源：

- 通过现有域名和 HTTPS 访问；服务器不向客户端开放 SSH 控制路径。
- 必须登录后访问 Full Web/API；PM Research Terminal、Local UI 与 MCP 使用独立、可撤销、可轮换的 PaperMind 凭据。
- PDF 和分析数据只保存在服务端。
- PM Research Terminal 和 Local UI 不直连数据库；Local UI 的 loopback bridge 不构成第二个业务后端。
- 备份覆盖数据库、PDF/对象文件和必要配置。

SQLite 适合个人应用、本地应用数据和单文件格式。[10] 但只有在 Core 能统一或串行化关键写入后，SQLite 才是最清晰的默认方案。重构期间不顺便迁移生产数据库：先维持当前实际配置，等 job/写入边界稳定后再选择：

- 单 Core、低并发：SQLite。
- 多 API/worker 直接并发写入或未来扩容：PostgreSQL。

### 6.2 公开 Demo

旧方案 `docs/plans/2026-05-08-demo-site.md` 中的 Vercel + Railway 部署决策由本文取代。现有 `DemoModeMiddleware` 和测试可以复用，但中间件不能替代数据隔离。

即使个人服务和 Demo 位于同一台阿里云服务器，也必须拆成两个实例：

```text
personal.pm.example.com
├── personal container/process
├── personal database
├── personal PDF volume
└── personal credentials

demo.pm.example.com
├── demo container/process
├── seeded demo database
├── demo assets volume
├── demo-only model key and quota
└── demo auth and temporary user records
```

不得通过 URL 参数或前端开关在同一实例中切换 personal/demo workspace。

### 6.3 Demo 登录与授权

Demo 采用渐进式身份门槛：

| 状态 | 能力 | 目的 |
| --- | --- | --- |
| 未登录 | 浏览预计算 Research Pulse、论文样例和 CLI 说明 | 不让登录墙挡住第一印象 |
| GitHub 登录 | 临时 Demo 空间、限额 AI 查询、CLI device authorization | 识别滥用并展示真实闭环 |
| 个人管理员 | 个人服务、完整任务与 worker 管理 | 与 Demo 权限彻底隔离 |

第一版推荐 GitHub 作为网页身份提供方。GitHub 官方支持标准 web application flow，并将 device flow 用于 CLI 等 headless 应用；同时建议最小 scope、短期 token、安全保存凭据和可删除用户数据。[12][13] PaperMind 的 CLI 不直接调用 GitHub device flow，而是调用 PaperMind 自己的 device authorization，再在 PaperMind 网页中完成 GitHub 登录。这样 CLI 只信任 PaperMind endpoint，身份提供方可以替换。

PaperMind 只向 GitHub 请求确认身份所需的最小权限，不请求 repository 权限。登录成功后：

1. 服务端验证 GitHub 用户身份。
2. 保存最小映射：`provider`、`provider_subject`、创建时间和 Demo TTL。
3. 丢弃不再需要的 GitHub token，签发 PaperMind 自己的 session/access token。
4. Full Web、Local UI、PM Research Terminal 和 MCP 都以 PaperMind token 访问同一 Demo 身份。
5. TTL 到期后删除 Demo 任务、输入内容和临时结果；预置公共语料不受影响。

微信网站扫码登录可作为第二 provider，但不作为第一版阻塞项。现有可访问的微信开放平台文档镜像说明，网站微信登录需要开放平台开发者账号、审核通过的网站应用、AppID/AppSecret 和 `snsapi_login` 授权流程；官方当前页面在本次调研中无法直接读取，因此该接入条件需要实施前在微信开放平台重新确认。[14]

## 7. Demo 页面：从网页自然进入 PM Research Terminal 与 Local UI

Demo 的目标不是证明 PaperMind 功能很多，而是让访客先在 30–60 秒内理解价值，再用 2–3 分钟从 PM Research Terminal 或 Local UI 完成同一研究流程：

> PaperMind 能把论文转化为可验证、可演进的研究认知，并让人和 AI 通过同一套接口继续工作。

### 7.1 三段式体验

1. **匿名看见结果**
   - 一个预置研究主题。
   - 最近重要变化、代表 Claim 和一句话研究判断。
   - Claim 清楚关联到具体论文、原文、Figure 或 Table。
   - 无需登录即可展开一个“结论如何被证据支持”的样例。

2. **登录后亲自提问**
   - GitHub 登录后创建临时 Demo 身份。
   - 提供 3–5 个预设问题，也允许严格限额的自由输入。
   - 回答必须附论文证据卡、引用片段、判断来源和不确定性。
   - 至少展示一篇新论文如何支持、限制或改变既有 Claim。
   - 默认优先返回预计算结果，避免访客消耗个人模型额度。

3. **把同一身份带进 `pm`**
   - 登录完成页展示 `pm login --endpoint ...`、`pm demo` 与 `pm ui --question ...`。
   - 页面同步显示终端将要完成的五步，并解释每一步对应的 PaperMind 能力。
   - PM Research Terminal 和 Local UI 返回的 Claim、Evidence、diff 和 job 与网页使用同一个临时 Demo 身份。
   - `pm demo` 最终导出一个受限、可携带的 Research Pack。
   - 最终提示如何连接远程 MCP，但不要求用户配置 SSH 或本地 server。

Demo 页面只需要围绕这三段旅程组织。Research Pulse、Ask PaperMind 和 Paper Sensemaking 是旅程中的内容组件，不再作为三个互不相关的产品页面。

### 7.2 Demo 不展示

- Settings、Operations、Email Settings。
- 完整 worker 管理和定时任务配置。
- 任意 PDF 上传、批量导入和删除操作。
- 完整写作助手。
- 需要长时间等待的实时 deep-read。
- SSH 地址、服务器命令、隧道配置和数据库连接信息。
- 个人服务中的论文、对话、API key 和日志。

### 7.3 Demo 成本与安全

- 公开接口使用 allowlist，而不是仅按 HTTP method 判断写权限。
- 未登录用户只能访问预计算公共内容；所有动态调用必须先登录。
- LLM 调用设置 IP 限额、全局限额、超时和每日硬预算。
- 限额同时绑定用户、IP 和全局预算，不能只依赖任意一个维度。
- 优先使用缓存/预计算结果；额度耗尽时仍可完整浏览静态演示。
- Demo token 不得访问 personal API。
- CLI device code 必须短期、一次性、绑定请求；轮询必须限速。
- 上游 GitHub/微信 token 不得作为 PaperMind token 使用或传给 MCP。
- Nginx/反向代理层分别路由两个域名，不依赖前端隐藏链接。
- 日志不得记录 prompt 中的密钥或完整 bearer token。

## 8. 分阶段迁移

### Phase 0：建立基线

- 记录当前 API、worker、PostgreSQL 和前端容器的空闲 RSS、峰值 RSS、镜像大小和冷启动时间。
- 列出所有长任务入口、状态存储和线程池。
- 为主要用户流程建立端到端回归测试。
- 选定一个预置研究问题，建立人工校验的 Claim/Evidence/SourceVersion 小样本。
- 冻结新增页面，除非它直接服务于重构或 Demo。

**出口条件：**每一项资源问题都有测量值，每一个长任务都有入口与状态归属清单；存在可验证 Research State 的基准样本。

### Phase 1：建立 application command/query

- 从现有 routers、MCP 和 agent tools 中提取用例层。
- 保持 HTTP 返回兼容，先做内部重定向，不大规模改前端。
- repository 和 provider 只在 application/service 内使用。

**出口条件：**Full Web、Local UI、PM Research Terminal 和 MCP 对同一能力调用同一个 application handler；存在第一版 canonical presentation model。

### Phase 2：原子化 durable execution

- 将 API lifespan 内的 batch consumer 移出请求进程。
- 将进程内 `TaskTracker` 的关键状态持久化。
- 建立 `Job → Task → Attempt → Artifact/Event` schema，并明确与 `ResearchRun` 的 provenance 关系。
- 为 Skim、DeepRead、Embedding、Topic Research 和 Daily Brief 定义第一批代码化 Workflow 模板及 Task 原子边界。
- Scheduler 改为只创建 Job；实现 Planner、Dispatcher、通用 Python Executor 和 Reconciler 的最小闭环。
- 实现 lease/fencing、timeout、cancel、retry、pause/resume、dead-letter 和 manual recovery 语义。
- 为数据库写入使用 transactional outbox，为外部副作用建立 idempotency/effect ledger。
- 将前端、CLI 与 MCP 的任务查询统一到 Job graph、Task 和 Attempt 资源接口。

**出口条件：**API/Executor 任意重启后，任务状态可解释、可恢复且不会静默丢失；同一 Task 的重复 Attempt 不会重复提交领域结果；单篇失败无需重跑整个批次。

### Phase 3：迁移 Research State 垂直切片

- 为 `ResearchQuestion`、`Claim`、`Evidence`、`SourceVersion`、`Relation`、`Judgment` 和 `History` 定义最小数据契约。
- 从一个预置研究问题和少量论文迁移，不批量回填全部历史数据。
- 让一个 Research Run 生成待验证 Claim，并保留证据坐标与完整 provenance。
- 实现 `GetResearchQuestion`、`ListClaims`、`GetClaimEvidence`、`DiffResearchState` 和基础 Research Object 导出。
- 通过 outbox/event log 记录 Claim 与 SourceVersion 的关键状态变化。

**出口条件：**同一个 Claim 能从 Web/API 追溯到精确证据、生成活动和历史版本；无证据的模型输出不会进入 confirmed 状态。

### Phase 4：PM Research Terminal 与 MCP 一等化

- 建立独立 `PaperMind-Terminal` downstream fork，固定 Pi 上游基线、保留许可证并维护有序 patch stack。
- 先通过 PaperMind product profile 关闭 coding-oriented 功能，再做 build pruning；不在第一步大面积删除底层源码。
- 建立 TypeScript/Node 的 `@papermind/cli` 和 standalone `pm`，在同进程运行裁剪后的 Pi agent core/TUI，并加载 PaperMind system prompt、主题和 renderer。
- 提供 `pm` 交互终端、`pm -p` 一次性调用、确定性子命令和 `--json` 输出。
- 提供远程登录、endpoint 配置和核心查询/任务命令；PaperMind token 与本地模型 provider token 分离。
- CLI 与 MCP 的唯一 PaperMind 连接方式是公网 HTTPS；不提供 SSH、tunnel 或本地 MCP transport 产品路径。
- 建立 capability metadata，使 HTTP、Pi tools、CLI commands 和 MCP tools 复用输入输出 schema、scope、risk 与 async 语义。
- 实现 Paper、Claim、Evidence、Research Diff、Job 和 Research Pack 专用终端渲染，并提供 dark/light 主题与非 TTY fallback。
- 默认 research permission profile；`--workspace` 与 `--coding` 必须由用户显式开启，Demo 永不开放 coding profile。
- MCP 提供远程 Streamable HTTP endpoint、OAuth protected resource metadata 和 scope 校验。
- 增加资源型接口和统一 job adapter。
- 将个人 MCP 静态 token 升级为可撤销、可轮换、分 scope 的凭据，并实现 MCP OAuth discovery。[11]
- 为 CLI 实现 PaperMind device authorization；上游登录 provider 与 CLI token 解耦。

**出口条件：**不打开 Web，也能在 `pm` AI 终端和确定性命令中完成搜索、查看 Claim/Evidence、比较研究状态、触发处理、查看进度、取消任务和导出；同一结构化结果在主题 TUI、plain/Markdown 与 JSON 模式下语义一致。

### Phase 5：Local UI 与可选 Full Web 适配

- 建立现有 Web route/capability inventory，逐项标记 retain、merge、local-ui 或 archive；不进行整体删除。
- 提取 `@papermind/client`、`@papermind/presentation` 和 `@papermind/ui-core`，让 Local UI 与 Full Web 复用类型、view model 和领域组件。
- 实现 `pm ui` 的 loopback bridge、随机端口、本地 session、origin/CSRF 校验和 HTTPS allowlist proxy。
- Local UI 首版实现 PDF/Evidence、Claim Workspace、Research Diff、Job Monitor 和 Research Pack。
- Full Web 适配 ResearchQuestion、Claim、Evidence、History、Diff 和 Job，并删除页面内重复的业务编排。
- Full Web 构建产物可由 Core 或同一反向代理提供，但 `--web=none` 时服务端不携带或启动 Web。
- 为每个新 capability 建立 Terminal、Local UI、Full Web、MCP 和 JSON surface contract 测试。

**出口条件：**`pm ui` 无本地业务后端或数据库即可操作远程 Research State；Full Web 可选启停；同一 Claim 在所有界面中状态、权限和 provenance 一致。

### Phase 6：公开 Demo

- 建立独立 Demo 数据与部署实例。
- 接入 GitHub 登录、临时 Demo 身份、TTL 清理与组合限额。
- 实现“匿名看 Claim 与证据 → 登录观察研究状态变化 → PM Research Terminal/Local UI 复现并导出”的三段式演示。

**出口条件：**个人站与 Demo 数据完全隔离；Demo 在模型不可用时仍能展示完整预计算流程。

### Phase 7：语言与存储决策门

- 对照 Phase 0 重新测量资源和启动性能。
- 判断剩余成本来自 Python control plane、重依赖、数据库还是具体任务。
- 决定是否迁移 Go Core，以及个人服务使用 SQLite 还是 PostgreSQL。

**出口条件：**任何语言或数据库迁移都有测量证据和独立回滚路径。

## 9. 验收标准

### 架构

- API 进程不执行长任务。
- 所有长任务具有持久化状态、可取消、可重试。
- ResearchRun、Job、Task、Attempt 与 Artifact/Event 各有独立 ID 和清晰关联，不能用单个 `job.status` 隐藏内部执行状态。
- Scheduler 不直接执行业务；Executor 每次只运行一个 Task Attempt；过期 lease 由 Reconciler 恢复。
- Task handler 不依赖进程内隐式状态，重复 Attempt 不会重复写入 Paper、Claim、Evidence 或外部副作用。
- 批量 Job 支持 per-Paper fan-out；单个 Task 失败不会抹掉其他成功结果，也不要求整批重跑。
- Full Web、Local UI、PM Research Terminal、MCP 不重复实现业务流程。
- 核心查询不会导入 PDF、NumPy、scikit-learn 等重依赖。
- SQLite profile 不启动 PostgreSQL；PostgreSQL profile 不携带无效 SQLite 假设。
- Full Web 不是必需部署单元，但可通过部署 profile 完整保留。
- 所有新 capability 都声明并验证 Terminal、Local UI、Full Web、MCP 与 JSON 的 surface contract。

### PM Research Terminal

- `pm` 无参数进入基于 Pi downstream fork 的 PaperMind AI 终端，`pm -p` 支持一次性 AI 调用。
- 每个核心能力同时具备可脚本化子命令、稳定退出码和 `--json` 输出。
- Pi extension 只通过 HTTPS application API 使用 PaperMind，不导入服务端 Python 或直连数据库。
- PaperMind token 与模型 provider token 分开保存、分开发现和分开撤销。
- 默认 research profile 不包含任意 `bash`、SSH、Docker 或服务端 shell 能力。
- Paper、Claim、Evidence、Research Diff、Job 和 Research Pack 有专用 renderer；dark/light 主题可切换。
- 同一 tool result 在 TTY、窄终端、pipe、Markdown/plain text 和 JSON 下保留相同核心语义。
- 主题关闭、模型不可用或交互 TUI 不可用时，确定性 CLI 仍可完整工作。

### Local PM UI

- `pm ui` 只绑定 loopback 随机端口，不监听公网网卡。
- browser 不持久化长期 PaperMind bearer token；bridge 退出后本地 session 失效。
- Local UI 不包含数据库、领域 handler、LLM pipeline 或 durable worker。
- PDF/Evidence、Claim、Research Diff、Job 和 Research Pack 能通过深链在终端与 Local UI 之间切换。
- 在 Full Web 未部署时，Local UI 仍可通过 HTTPS 完成全部目标流程。
- Local UI 与 Full Web 共用 typed client、canonical presentation model 和领域组件，但不复制页面级状态机。

### 可选 Full Web

- 现有页面经过 inventory 后逐项 retain、merge、local-ui 或 archive，不以批量删除作为瘦身方式。
- `--web=full` 能访问保留后的完整 Web；`--web=none` 不影响 Core、MCP、`pm` 和 `pm ui`。
- 新 Research State 能力在 Full Web 中可查看、可定位 evidence、可执行授权范围内的修改。
- Full Web 不维护独有的 Claim、Evidence、Job 或权限语义。

### 研究状态

- 重要 Claim 区分作者陈述、PaperMind 推断与用户判断。
- confirmed Claim 至少关联一个可定位、带 SourceVersion 的 Evidence；无证据输出只能是 draft/pending verification。
- 能查看 Claim 的修订、取代与失效历史，并解释状态变化原因。
- Figure/Table/数值证据保留实验条件，跨论文比较不静默混合不同 protocol。
- 至少可将一个 ResearchQuestion 导出为包含 Claim、Evidence、Relation 和 provenance 的 JSON 与 Markdown。
- 对引用覆盖、证据支持关系、反例遗漏与来源完整度存在可重复的质量检查。

### 个人使用

- 新电脑只安装轻量 `@papermind/cli`/`pm` binary 或配置 MCP endpoint 即可使用。
- PM Research Terminal、Local UI 和 MCP 只需 HTTPS endpoint，不需要服务器 SSH 权限。
- 服务端数据库是唯一事实来源。
- HTTPS 登录、凭据撤销、备份恢复均有可重复步骤。
- 能远程查看 Executor pool 健康、Job graph、Task/Attempt 进度和失败原因。

### Demo

- 未登录即可在一分钟内看懂预计算演示；登录后才能执行动态调用。
- GitHub 登录后能够获得有 TTL 和硬限额的临时 Demo 身份。
- `pm login`、`pm demo` 和 `pm ui --question ...` 能通过 HTTPS 复现网页中的 Claim、Evidence、diff、job 和导出流程。
- 页面围绕 Research Pulse、Ask PaperMind、Paper Sensemaking 和 CLI onboarding 组织，不扩展成完整后台。
- Demo 无法读取或修改个人实例数据。
- LLM 不可用或额度耗尽时，预计算结果仍可访问。
- 首页明确提供源码、部署文档或个人服务介绍的下一步入口。

## 10. 风险与约束

- **重构范围失控：**先保持外部行为兼容，按 adapter 替换内部调用，不同时重做 UI 和领域模型。
- **双实例仍共享秘密：**Demo 使用独立模型 key；最低限度也必须使用独立 scope 和硬预算。
- **第三方登录演化成账号产品：**只保存最小身份映射和 TTL 数据；不建设资料页、社交关系、团队或计费。
- **身份提供方锁定：**PaperMind session 与 provider token 分离，以统一 identity adapter 支持 GitHub 首发、微信后续。
- **CLI token 泄漏：**使用短期、限 scope 的 PaperMind token，支持撤销；不在终端历史、URL 或日志中输出 token。
- **CLI/MCP 演化出第二套 API：**以 application handlers 为唯一能力目录，自动生成或薄封装 adapters。
- **Pi downstream 与上游长期分叉：**独立 fork 固定 upstream tag，维护小而有序的 patch stack；定期同步安全与 provider 修复，不把 PM 领域逻辑写进 Pi core。
- **过早 source pruning 导致无法同步：**先用 product profile 和 build pruning 删除用户可见复杂度，只有稳定后才物理删除底层代码。
- **终端 renderer 吞入业务逻辑：**renderer 只接受 canonical structured result，不能查询数据库、改变状态或重新解释 Claim。
- **Node 安装成为额外门槛：**首版使用版本化 npm 包和清晰安装器；以后只优化分发形态，不重写 Pi harness。
- **AI 模式破坏脚本兼容：**无参数才进入 TUI；传统子命令、stdout/stderr、退出码和 `--json` 保持确定性。
- **Full Web 与 Local UI 分叉：**共享 typed client、presentation model、领域组件和 surface contract 测试；允许信息架构不同，不允许领域语义不同。
- **保留现有 Web 使瘦身失效：**Full Web 使用可选 build/deployment profile；retain 不等于默认加载，archive 不等于立即删除源码。
- **Local UI loopback 被滥用：**只绑定 loopback 随机端口，使用启动 nonce、短期 cookie、Host/Origin/CSRF 校验和 allowlist proxy；token 不进入 URL 或 localStorage。
- **过早 Go 化：**以 Phase 7 决策门阻止无测量依据的重写。
- **公开域名攻击面：**个人服务和 Demo 都经 HTTPS；Demo 限流，个人服务强认证；禁止 token 出现在 URL 和日志中。
- **协议变化：**内部 job schema 保持自主，MCP Tasks 仅在 adapter 层转换。
- **Task 拆分过细：**只把值得独立重试、隔离资源、观察或追溯的步骤设为 Task；纯函数和短数据库操作留在 handler 内。
- **误解 exactly-once：**外部副作用采用至少一次执行与幂等去重；无法安全重放的步骤进入 manual recovery，不自动重试。
- **lease 竞争与迟到写入：**使用 fencing token 拒绝过期 Attempt 提交，Reconciler 只依据持久状态恢复。
- **Workflow 引擎范围失控：**首版只支持代码定义模板、顺序依赖、条件分支和 fan-out，不建设通用 DAG 编辑器。
- **按能力拆服务过早：**先用 resource class 在同一 Executor runtime 内隔离调度，有资源或依赖证据后再拆进程/镜像。
- **领域模型一次做太大：**先迁移一个 ResearchQuestion 垂直切片；Claim ontology、置信度和关系类型只保留完成 Demo 所需的最小集合。
- **把模型推断伪装成事实：**强制保存 judgment origin、evidence status 与 source version；confirmed 状态需要明确规则。
- **Provenance 成为沉重标准工程：**内部先实现必要字段和稳定 ID，保持与 W3C PROV/RO-Crate 的映射能力，不在首版引入完整语义网栈。
- **自动化越权：**watch 和 Agent 默认只产生候选项与受控 job，不能静默覆盖用户确认的 Claim。

## 11. 推荐实施顺序

下一步不是先写终端或重画 Demo，而是完成六份短设计：

1. **Research State 最小数据契约。**定义 ResearchQuestion、Claim、Evidence、SourceVersion、Relation、Judgment、History 与 ResearchRun，以及 draft/confirmed/invalidated 转换规则。
2. **Application command/query 清单与当前调用映射。**把 151 个 HTTP handlers、MCP tools 和 agent tools 映射到有限的用例集合。
3. **原子 Durable Execution 协议与迁移说明。**定义 ResearchRun/Job/Task/Attempt/Artifact、Task 原子边界、Workflow 模板、lease/fencing、幂等/outbox、Reconciler 和 Executor capability；确定 `TaskTracker`、`BatchJob`、APScheduler、后台线程与 worker heartbeat 如何收敛。
4. **PM Research Terminal downstream 架构。**定义 Pi 上游基线、patch policy、product profile、source/build pruning、capability metadata、确定性命令、permission profiles、主题与领域 renderer。
5. **UI Surface Contract。**完成现有 Web inventory，定义 Local UI loopback bridge、canonical presentation model、共享 UI packages、deep links 与 Full Web 可选部署 profile。
6. **HTTPS identity/token flow。**定义 GitHub Web 登录、CLI device authorization、MCP OAuth discovery、PaperMind token、本地模型凭据与 Local UI session 的边界。

这六份设计获确认后，从一个只读垂直切片开始迁移：

```text
SearchPapers + GetPaper + GetResearchQuestion + ListClaims + GetClaimEvidence
    → application handlers
    → typed HTTPS client
    → deterministic CLI command
    → Pi tool + PaperMind renderer
    → Local UI + Full Web adapters
    → MCP adapter
```

第一个切片不涉及长任务，能验证接口边界；随后再迁移 `StartSkim → durable job → Claim/Evidence draft → review/confirm → diff/export`，验证完整研究执行链。

## Sources

[1] [`pyproject.toml`](../../pyproject.toml) — 当前核心、LLM、PDF 与 graph 依赖分组

[2] [`docker-compose.yml`](../../docker-compose.yml) — 当前 backend、worker、PostgreSQL 与前端部署关系

[3] [`apps/api/main.py`](../../apps/api/main.py) — API lifespan 内启动 batch consumer 并挂载 MCP

[4] [`apps/api/deps.py`](../../apps/api/deps.py) — API import 阶段的 service 单例

[5] [`apps/api/mcp.py`](../../apps/api/mcp.py) — 当前 MCP transport、鉴权和工具实现

[6] [Pi SDK](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sdk.md) — 同进程 AgentSession、模型、资源加载、session 与自定义 extension 接口

[7] [MCP Transports, 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) — Streamable HTTP 与远程安全要求

[8] [MCP Apps Overview](https://modelcontextprotocol.io/extensions/apps/overview) — 渐进式交互 UI、PDF 和实时状态场景

[9] [The 2026-07-28 MCP Specification Release Candidate](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/) — MCP Tasks 生命周期仍在演进

[10] [Appropriate Uses For SQLite](https://www.sqlite.org/whentouse.html) — 个人应用、本地数据与单文件应用格式

[11] [MCP Authorization, 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization) — 远程 MCP OAuth、resource metadata 与 token 要求

[12] [Authorizing OAuth Apps](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps) — GitHub Web application flow、CLI device flow 与 expiring tokens

[13] [GitHub OAuth App Best Practices](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/best-practices-for-creating-an-oauth-app) — 最小权限、token 保存、轮换和数据删除

[14] [网站应用微信登录开发指南镜像](https://wdk-docs.github.io/wxopen-docs/website/login.html) — 微信网站登录的应用审核、AppID/AppSecret 与 OAuth2 流程；实施前需在官方平台复核

[15] [W3C PROV-O](https://www.w3.org/TR/prov-o/) — Entity、Activity、Agent 与 provenance chain 的标准模型

[16] [RO-Crate 1.3 Specification](https://www.researchobject.org/ro-crate/specification.html) — 可携带 Research Object 与 provenance 的长期兼容方向

[17] [Zotero Web API v3](https://www.zotero.org/support/dev/web_api/v3/) — 文献读写、全文、同步、streaming 与 OAuth 接口

[18] [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) — DOI、works 与出版元数据规范化入口

[19] [Pi Extensions](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md) — 自定义 tools、commands、events、UI、theme 相关扩展与默认工具覆盖能力

[20] [Pi RPC Mode](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc.md) — 跨进程 JSONL 协议及其与同进程 SDK 的适用边界

[21] [`packages/agent_core/loop.py`](../../packages/agent_core/loop.py) — 当前 PaperMind 流式 agent loop 与 confirmation 实现

[22] [`packages/ai/tools/registry.py`](../../packages/ai/tools/registry.py) — 当前 PaperMind tool registry、schema 与 handler dispatch

[23] [Pi Themes](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/themes.md) — 自定义 TUI theme、加载位置、选择与热更新机制

[24] [Pi MIT License](https://github.com/earendil-works/pi/blob/main/LICENSE) — downstream 修改、分发与 copyright/license notice 要求

[25] [Pi Repository and Packages](https://github.com/earendil-works/pi) — agent core、AI/provider、TUI、coding agent 与 standalone build 的上游包边界
