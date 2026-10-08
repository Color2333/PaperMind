# 设计⑤：UI Surface Contract（Web inventory + Local PM UI + presentation model）

状态：**待确认**（重构路线图 A9；六份设计之第五份）

日期：2026-09-02

依据：[PaperMind 2026 形态与重构设计](./2026-09-02-papermind-2026-rearchitecture.md) §3.2（可选 Full Web / Local PM UI / 跨界面适配契约 §3.3）、§11 设计⑤；现状：`frontend/src`（React/Vite，16 条路由）。

范围：现有 Web route/capability inventory（retain/merge/local-ui/archive）、canonical presentation model、三个共享 UI 包边界、`pm ui` loopback bridge 安全契约、deep links、Full Web 可选部署 profile。出口条件：能直接指导 F1–F7。

## 1. 现有 Web route/capability inventory（16 条路由）

| 路由 | 页面 | 标记 | 说明 |
| --- | --- | --- | --- |
| `/` | Agent 对话 | **retain** | agent 编排在后端；工具业务经设计② B5 下沉 |
| `/collect` | 采集/入库 | **retain** | 批量选择是高信息密度任务；Demo 不暴露 |
| `/dashboard` | 研究概览 | **merge → `/`** | 与 Agent 首页职责重叠 |
| `/papers` | 论文库 | **retain** | |
| `/papers/:id` | 论文详情（PDF/证据对照） | **retain + local-ui** | Full Web 保留完整版；核心阅读路径由 Local UI「PDF/Evidence 并排」承接 |
| `/graph` | 图谱大画布 | **retain** | 大画布可视化只留 Full Web |
| `/wiki` | Wiki 浏览 | **retain** | |
| `/brief` | 每日简报 | **retain** | |
| `/pipelines` | 任务/流水线 | **local-ui**（Full Web 侧 merge → `/operations`） | 对应 Local UI「Job Monitor」 |
| `/operations` | 运维 | **retain** | Demo 不展示 |
| `/email-settings`、`/settings` | 设置 | **retain** | Demo 不展示 |
| `/writing` | 写作 | **retain** | 完整写作平台只留 Full Web |
| `/statistics` | 统计 | **merge → `/dashboard` 落点 `/`** | 与概览合并 |
| `/device` | CLI 设备码授权 | **retain** | CLI 登录关键页，设计⑥复用 |
| `/briefs` | 重定向 | 保持 | |

规则重申：**不以批量删除作为瘦身方式**；merge 在 F5 执行时逐条迁移跳转并保留旧路径 redirect 一个版本。inventory 一次产出，F1 执行标记、设计⑤/A9 共同引用（本文件即 inventory 权威）。

## 2. Canonical presentation model

- **唯一事实源**：application queries 的 canonical result（plain dict，D4/D5 已定）。
- **TS 类型生成**：capability metadata 的 `output_schema`（Python 为源）构建期导出 JSON → `@papermind/presentation` 的 TS 类型由脚本生成，不手写双份（防漂移；设计④ §6 同源）。
- **view model 只做展示映射**：status/certainty/stance → 标签文案、颜色、排序、折叠规则；禁止重新推导 Claim 状态、证据关系或 job 生命周期（设计文档 §5.1 硬规则）。
- 四界面（Terminal/Local UI/Full Web/MCP）+ JSON 共享同一 canonical result；允许隐藏操作，不允许同一 Claim 在不同界面有不同状态或解释。

## 3. 共享 UI 包边界

```text
@papermind/client        typed HTTPS client + auth types（token 注入、401/403 处理、重试策略）
@papermind/presentation  生成的 TS 类型 + 状态→展示映射（枚举/标签/时序格式化）
@papermind/ui-core       无障碍 React primitives + 领域组件
                         （ClaimCard / EvidenceList / DiffTimeline / JobProgress / ExportPreview）
```

禁止：导入服务端 repository、Python handler、Pi 私有 session 类型；页面级业务状态机不进共享包（Local UI 与 Full Web 信息架构不同，各自持有路由与布局状态）。

## 4. `pm ui` loopback bridge 安全契约（F3）

```text
Browser ──http://127.0.0.1:{random-port}/#/?nonce=...──▶ pm bridge（@papermind/cli 内）
   ◀── 一次性 nonce 换短期 HttpOnly+SameSite=Strict session cookie ──
   bridge ──HTTPS（仅 allowlist application 调用）──▶ PaperMind Core
```

1. **绑定**：仅 `127.0.0.1`/`::1` 随机可用端口；拒绝非 loopback Host 头。
2. **会话**：一次性启动 nonce（URL 中出现一次即失效）→ 短期 session cookie；`pm ui` 退出即销毁内存凭据与本地 session。
3. **CSRF/Origin**：双提交 CSRF token + Origin/Referer 同源校验；不配置宽 CORS。
4. **代理 allowlist**：只放行 capability metadata 声明的 read/query 面；写命令需显式确认后放行且逐次记账；token 只存在于 bridge 进程内存，不进 localStorage、不进 URL（nonce 除外且一次性）。
5. **日志**：不记录完整 bearer token 与带 nonce 的 URL。
6. **无本地后端**：bridge 不运行业务逻辑、不连数据库——它只是带鉴权的转发层。

## 5. Deep links（终端 ↔ Local UI ↔ Full Web）

- 终端卡片 `open`/`o` 动作 → `pm ui --claim <id>` / `--question <id>` / `--job <id>` / `--paper <id>`，bridge 启动后直达 `#/claims/{id}` 等路由。
- Evidence 深链打开个人或 Demo 域名下经鉴权的精确证据位置（Full Web），不暴露内部文件路径。
- Local UI 操作结果立即反映到终端与 Full Web 查询（同一 canonical result，无本地缓存权威副本）。

## 6. Local UI 首版五类界面（F4）

| 界面 | 对应 capability（设计②） | 说明 |
| --- | --- | --- |
| PDF/Evidence 并排定位 | GetPaper + GetClaimEvidence | 左 PDF 右证据卡，locator 高亮 |
| Claim 工作台 | ListClaims + GetClaimEvidence + Confirm/Revise 命令 | 状态/来源/关系/确认与修订 |
| Research Diff | DiffResearchState | 时间轴 + 六类变化 |
| Job Monitor | GetJob/ListJobs（Stage C 后） | 进度/日志/成本/失败/重试 |
| Research Pack | ExportResearchObject | 预览/选择/导出（含校验值） |

不在首版复制：设置后台、订阅配置、邮件管理、ingestion 批量、通用写作平台。

## 7. Full Web 可选部署 profile（F5/F6）

```bash
papermind-server serve --web=full    # Core + MCP + 完整 Web（retain 后的页面）
papermind-server serve --web=demo    # Demo 实例的精简公开页
papermind-server serve --web=none    # 仅 Core + MCP；不挂载任何静态 Web
```

- 生产构建产物由 Core 或同一反向代理提供；不要求常驻独立前端容器（compose 的 nginx 服务在 F6 退役）。
- 新 Research State 能力（question/claim/evidence/history/diff/job）必须提供 Full Web 适配（可查看、可定位 evidence、可执行授权修改）——不能只在 CLI 实现。
- Full Web 逐步改为只调 application API（设计②映射）；页面内重复业务编排删除；三套任务轮询端点（`/tasks/active`、`/tasks/{id}`、`/ingest/references/status`）在前端收敛到统一 Job 查询（C10 后）。
- 隔离提醒：`--web=demo` 只是页面 profile；Demo 隔离仍靠独立实例（G1）。

## 8. Surface contract 测试（F7）

每个新 capability 五面验证（语义一致，不要求像素同构）：

| 面 | 载体 | 测试 |
| --- | --- | --- |
| terminal | pm 子命令/Pi tool | CLI 契约测试（设计④ §8） |
| local_ui | Local UI 面板 | vitest：view model 映射快照（由 canonical result 样本驱动） |
| full_web | Full Web 路由 | vitest + 既有 e2e-full.mjs 演进 |
| mcp | resource/tool | MCP 工具单测 |
| json | canonical result | pytest schema 断言（output_schema） |

一致性断言：对象 ID、状态机、权限 scope、幂等键、provenance 字段五面相同。

## 9. 待确认决策点

1. **merge 方向**：`/dashboard → /`、`/statistics → /dashboard 落点 /`——提案按表格方向执行（F5）。
2. **Local UI 技术栈**：React + Vite（与现有前端同栈，`ui-core` 自然共享）——提案确认。
3. **bridge 语言**：Node，随 `@papermind/cli` 同包分发（同一进程内启动 HTTP 服务）——提案确认。
4. **archive 暂缓**：本期无 archive 项；`/pipelines` 在 Full Web 侧 merge 后旧路由 redirect——确认。

## 变更记录

- 2026-09-02：初版（A9），inventory 基于 frontend/src 当前 16 路由。
