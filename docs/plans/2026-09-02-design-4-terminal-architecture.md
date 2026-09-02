# 设计④：PM Research Terminal downstream 架构

状态：**待确认**（重构路线图 A8；六份设计之第四份）

日期：2026-09-02

依据：[PaperMind 2026 形态与重构设计](./2026-09-02-papermind-2026-rearchitecture.md) §3.2（PM Research Terminal / Pi downstream fork policy / 主题渲染 / 权限 profile）§11 设计④；现状：`apps/cli`（Python typer 版 pm：login/logout/me/doctor + 设备码授权）。

范围：定义 `pm` 终端的 upstream 基线、patch policy、product profile、裁剪顺序、包结构、确定性命令面、capability metadata、permission profiles、主题与领域 renderer、fallback 契约。出口条件：能直接指导 E1/E2。

## 1. 现状与目标形态

- **现状**：`apps/cli` 是 Python typer CLI——`pm login --endpoint`（设备码授权，服务端 `/auth/device/*` 已实现并有测试）、`pm logout`、身份查看、连通性体检；`pm.spec` 用 PyInstaller 打包多平台独立可执行文件。
- **目标**：`pm` = 以 Pi 为 upstream 的 PaperMind downstream 发行版，TypeScript/Node 同进程组合：命令解析 + 裁剪后的 Pi agent core/TUI + PaperMind extension（tools/renderers/确认 UI）+ 主题；同时交付 npm 包（`@papermind/cli`）与 standalone executable（基于 Pi 上游构建流程）。
- **过渡**：Python 版 pm 的确定性子命令在 TS 版命令面对齐前保持可用；设备码授权协议（PaperMind 自己签发 device code、浏览器完成上游登录、CLI 只拿 PaperMind token）原样复用——这部分已实现，是设计⑥的既有资产。

## 2. Downstream fork 基线与 patch policy

按设计文档 §3.2 fork policy 落实为可执行准则：

```text
独立仓库 PaperMind-Terminal
├── upstream/          earendil-works/pi @ pinned release tag（记录在 UPSTREAM_BASELINE 文件）
├── patches/           有序 patch stack（0001-*.patch …，每条一个关注点）
├── product/           PaperMind product profile（开关清单，见 §4）
├── extension/         @papermind/pi-extension（本设计 §5）
├── themes/            papermind-dark / papermind-light
└── release/           版本化 npm 包 + standalone 构建流水线
```

维护规则：

1. 保留完整 Git 历史、MIT copyright/license notice 与第三方 notices。
2. 每次 PM release 记录：upstream 基线 tag、patch 清单、未合并的上游安全/provider 修复（RELEASE_NOTES 模板固定三节）。
3. **patch stack 纪律**：只改 coding-agent 产品层与 TUI 层；除非扩展点缺失，不改底层模型协议、agent event schema、session format。单 patch 只做一件事，可独立 revert。
4. 同步节奏：每个 PM release 前检查上游 release；安全修复 72h 内评估合入。同步前运行契约测试（§8）。
5. 裁剪顺序（硬规则）：**product profile 开关 → build pruning → source pruning**。稳定前不做物理删除底层源码（防止无法同步上游）。

## 3. 包与进程结构（同进程，无子进程 RPC 长期架构）

```text
@papermind/cli（npm 包入口 pm）
├── bin/pm              命令解析：无参数→TUI；-p→一次性；子命令→确定性路径；--json→机器输出
├── terminal/           裁剪后的 Pi agent session/TUI（downstream 包）
├── extension/          @papermind/pi-extension
│   ├── https-client    typed 客户端（唯一 PaperMind 连接方式：公网 HTTPS application API）
│   ├── auth-adapter    PaperMind token 加载/刷新/撤销（与模型 provider 凭据分离，§7）
│   ├── tools/          PaperMind tools（由 capability contract 派生，§6）
│   ├── renderers/      Paper/Claim/Evidence/Diff/Job/Research Pack 卡片（§7）
│   └── confirm-ui      确认弹窗（服务端 policy 是最终授权，UI 确认不绕过）
└── themes/             papermind-dark / light + 用户自定义主题加载（全局/项目/CLI 参数）
```

不通过 Python 包导入服务端 AI/PDF/数据库模块；Pi RPC 仅作为测试/嵌入备用路径。

## 4. Product profile 与裁剪清单

| 开关 | 默认 | 说明 |
| --- | --- | --- |
| coding tools（bash/edit/read…） | **off** | `pm --coding` 显式开启（§6 profiles） |
| 默认 Pi 内置 tools | off | 只加载 PaperMind 受控工具集 |
| session/compaction/model 接入 | on | Pi 核心能力保留 |
| 通用 TUI 主题 | 替换 | PaperMind 主题为默认 |
| telemetry/遥测 | off | 个人部署无遥测 |

source pruning（稳定后）候选：demo/cost 收集、与 coding 场景绑定的示例与默认 prompt。

## 5. 确定性命令面 v1（映射设计②用例）

```bash
pm login --endpoint URL / pm logout / pm whoami / pm doctor     # 现有（复用设备码协议）
pm papers search "query" [--json]
pm paper show <paper-id> [--format md]
pm questions show <question-id> [--json]
pm claims list --question <id> [--status ...] [--json]
pm claims show <claim-id>            # 含证据卡
pm diff --question <id> [--since 30d] [--json]
pm export <question-id> --format research-pack [--json]
pm brief today [--json]
pm ask "自然语言问题"                 # 走本地 Pi + 远程受控工具
pm jobs list / show <id> [--json]    # Stage C 后接 Job graph
pm jobs cancel <id> / tasks retry <id>
pm queue pause / resume
pm demo                              # Demo 引导教程（Phase 6）
```

输出契约（验收标准 §PM Research Terminal）：

- `--json`：无 ANSI、无装饰文本、无截断展示副本——canonical result 原样输出；稳定退出码（0 成功 / 2 用法错误 / 3 未登录 / 4 服务端业务错误 / 5 网络错误）。
- 非 TTY（pipe）自动退化为清晰 Markdown/plain text；颜色不是唯一状态信号；窄终端保留状态词与证据坐标。
- TUI、plain、JSON 三态下核心语义一致（canonical result 唯一事实）。

## 6. Capability metadata 与 permission profiles

**capability metadata**（E5 种子，application 层维护，adapters 派生）：

```json
{
  "name": "get_claim_evidence",
  "kind": "query",
  "risk": "read_only",
  "required_scope": "research:read",
  "supports_async": false,
  "input_schema": {},
  "output_schema": {},
  "render_hint": "claim_evidence_card",
  "surfaces": {"terminal": "command+tool", "local_ui": "ClaimEvidencePanel", "full_web": "route", "mcp": "resource", "json": "ClaimEvidenceResult"}
}
```

规则：CLI 子命令、Pi tool、MCP tool、HTTP 路由全部从同一 metadata 派生或薄封装；`render_hint` 指向终端 renderer，renderer 只接受 canonical structured result。

**permission profiles**：

| profile | 能力 | 开关 |
| --- | --- | --- |
| `research`（默认） | PM tools + 本地导出写（仅 cwd 之外明确路径需确认） | 默认 |
| `--workspace .` | 增加当前目录内研究文件读写 | 显式 |
| `--coding` | 完整 Pi coding tools | 显式；**Demo 永不开放** |

destructive/高成本 PaperMind command：服务端 policy 校验（scope/预算）+ 终端确认 UI **双重**把关；本地确认不能绕过服务端权限。工具结果限制大小并支持分页/资源引用，不把整本 PDF 或全量日志注入模型 context。

## 7. 主题与领域 renderer

- 六类卡片：Paper Card（标题/作者/年份/来源/版本/阅读状态/短 ID）、Claim Card（结论/状态/判断来源/置信提示/证据数）、Evidence Card（论文/页码/section/短引用/证据方向/"在 Web 中打开"深链）、Research Diff（新增/加强/削弱/冲突/取代/失效 + 原因）、Job View（阶段/进度/耗时/成本/重试/错误）、Research Pack View（对象清单/校验值/provenance 摘要）。
- 渲染规则：canonical tool result 是结构化数据，renderer 只负责显示；`--json` 路径完全绕过 renderer；深链（`open`/`o`）指向 Local UI / Full Web 的精确证据位置（鉴权 URL，不暴露内部路径）。
- `papermind-dark/light` 为默认两主题；允许用户安装自定义 Pi theme；主题关闭/模型不可用/TUI 不可用时，确定性 CLI 仍完整工作。

## 8. 测试策略（终端契约测试）

1. **JSON 契约**：每个确定性命令的 `--json` 输出跑 schema 断言（由 capability metadata 的 output_schema 生成）；无 ANSI 转义断言。
2. **退出码表**：五类退出码逐个触发验证。
3. **非 TTY fallback**：pipe 模式输出为纯文本/Markdown，语义与 JSON 等价（同一 canonical result）。
4. **Pi 上游同步契约**：agent loop/session/provider/TUI snapshot + PaperMind renderer 快照测试，upstream 升级前后对比。
5. **权限 profile**：默认 profile 下 coding tools 不可达；`--coding` 需显式；Demo profile 永无 coding。

## 9. E1/E2 实施顺序

1. E1a：建 PaperMind-Terminal 独立仓库，固定 upstream tag，product profile 关闭 coding tools，跑通未裁剪 build。
2. E1b：build pruning → standalone `pm` 可启动空壳 TUI。
3. E2a：`@papermind/cli` 命令骨架 + auth-adapter（复用 `/auth/device/*`）+ `--json` 契约测试框架。
4. E2b：第一批确定性命令（papers/questions/claims/evidence/diff/export——只读切片，对应设计② B2/B3 能力）。
5. E2c：Pi extension tools + renderer + 主题（读写与任务命令在 Stage C Job 面就绪后接入）。

## 10. 待确认决策点

1. **独立仓库时机**：PaperMind-Terminal 仓库在 E1a 即建立，还是先在本仓库 `terminal/` 目录原型、稳定后搬出？提案：直接独立仓库（patch stack/Git 历史从一开始就干净）。
2. **Python 版 pm 的退役节奏**：TS 版命令对齐一个退役一个，还是维护到 Phase 4 出口一次性替换？提案：对齐一个退一个（`pm login` 等先退役）。
3. **standalone executable 分发**：npm 包之外是否第一版就出 Homebrew/安装器？提案：第一版 npm + GitHub Release 二进制即可，安装器后置。
4. **capability metadata 存放**：application 层 Python 定义 + 构建期导出 JSON（TS 侧消费），还是独立 JSON 为源？提案：Python 为源、构建期导出（单一事实源在服务端）。

## 变更记录

- 2026-09-02：初版（A8）。
