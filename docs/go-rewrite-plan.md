# PaperMind 2.1 — Go 全量重写计划（绞杀者模式 · 全量清点版）

> 决策：backend/worker 全量迁 Go。方式：绞杀者渐进替换——每条路由/handler
> 独立迁移、独立验证；Go 未覆盖的路由自动反代 Python，任何时刻可整体回退。
> 本版计划经全量清点修订：191 个 API 端点 / 19 个路由器 / packages 面积
> 全部映射到 Phase，无遗漏项。

## 接缝（零改动保证）

- **入口**：frontend nginx `/api/` → `goserver:8080`（compose 挂载
  `infra/nginx.goserver.conf`，前端镜像零重建）
- **回退**：Go 未实现的路由透明反代 `backend:8000`（SSE 立即冲刷，"/" 全量兜底）
- **验收**：每条路由迁移后用原前端/CLI 真机回归 + golden test（同请求双栈 diff 响应）

## 清点基线（2026-10-09）

- API：191 端点 / 19 路由器（papers 20 · graph 20 · jobs 17 · settings 16 ·
  sensemaking 13 · durable_state 13 · topics 12 · auth 11 · pipelines 10 ·
  content 10 · agent 9 · tags 8 · llm_configs 6 · cs_feeds 6 · translate 5 ·
  research 5 · writing 4 · system 4 · github_auth 2）
- Worker/智能体：packages/ai ~7.8k 行（11 服务）+ task_handlers ~1.2k
- 集成：arxiv/biorxiv/dblp/ieee/openalex/S2/SMTP 等 20 个 client
- 硬骨头（诚实标注）：UMAP/sklearn 散点、PDF 视觉提取、191 端点行为对齐

## Phase 0 ✅（已完成上线，db4fc9c + #91/#92）

骨架 + 绞杀者接缝 + 设备码授权全流程（start/poll/info/authorize/deny）
+ API 令牌签发 + folder-stats + python-jose 兼容测试。

## Phase 1 — 读面（papers 20 + tags 8 + research 5）

- [ ] /papers/latest（port list_papers 全过滤查询）
- [ ] /papers/{id}（详情 + 研究状态聚合）
- [ ] /papers/search-multi（arXiv/S2/IEEE/OpenAlex/bioRxiv 聚合——5 个 channel 移植）
- [ ] /papers/folder-stats（✅ 已移植）
- [ ] tags CRUD / research 只读面 / diff

## Phase 2 — 任务与订阅面（jobs 17 + topics 12 + cs_feeds 6）

- [ ] jobs/tasks 查询与控制（pause/resume/retry/cancel → Go Core 直连）
- [ ] topics/subscriptions CRUD + ingest 提交
- [ ] cs_feeds 管理
- [ ] durable_state 内部 API 评估（Go Core 直读 PG 后可能整面退役）

## Phase 3 — Worker handler 全移植（packages/ai ~7.8k 行）

- [ ] embed / skim / claims（LLM 经 Pi 网关——Go HTTP 客户端）
- [ ] deep_read（PDF 文本 poppler 外挂 or go-pdfium；视觉页图→网关）
- [ ] ingest arxiv/ieee/cs（HTTP + XML）
- [ ] sync_citations（S2 + openalex）
- [ ] brief / wiki 生成（html/template）
- [ ] 闲时处理器（idle loop + 在途去重 + 补偿配额）
- [ ] 调度器（topic_dispatch / cs_feed / 每日简报 cron → robfig/cron）
- [ ] SMTP 邮件（net/smtp + 模板）

## Phase 4 — Agent 与生成面（agent 9 + content 10 + writing 4）

- [ ] /agent/chat SSE（spawn pm Node 子进程保持不变——Go 只做流转发与会话持久化）
- [ ] pending-actions / conversations CRUD
- [ ] content 读写（generated_contents）
- [ ] writing 辅助（LLM 经网关）

## Phase 5 — 认证全量与配置（auth 余量 6 + github_auth 2 + settings 16 + llm_configs 6 + system 4）

- [ ] Web 登录（站点密码 + JWT 签发/校验全流程——Phase 0 已有 HS256 校验器）
- [ ] GitHub OAuth 回调（http.Get 即可）
- [ ] API 令牌 CRUD / settings 16 端点 / llm_configs CRUD（网关配置的写入口）
- [ ] system（磁盘/版本/健康聚合）

## Phase 6 — 智能深水区（translate 5 + sensemaking 13 + graph 20）

- [ ] translate（LLM 经网关）
- [ ] sensemaking（认知重构流程——LLM 多步）
- [ ] graph 20 端点（networkx 图算法 → gonum 图 + 自研度中心性/社区发现；
      **此 Phase 工作量最大，允许单独排期**）
- [ ] 研究散点：UMAP(scikit-learn) → gonum PCA 降级方案 A/B 决策

## Phase 7 — 收口（删 Python）

- [ ] durable_state 内部 API 退役评估（Go Core 直读 PG 后或留薄壳）
- [ ] Alembic → goose 迁移收口（一次性快照）
- [ ] MCP server 对齐（Go core 已有 mcp_server.go，补齐端点差异）
- [ ] 删除 apps/ + packages/ + Dockerfile.backend；compose 收敛为
      core + goserver + worker(go) + gateway + frontend + postgres
- [ ] golden test：全端点同请求 diff 响应归零

## 验收标准（每 Phase 通用）

1. Go test 绿 + pytest 全量绿（未迁移部分）
2. 真机回归：pm CLI 三形态 + Web 全功能
3. golden test：已迁移端点同请求双栈 diff 响应归零
4. 内存/延迟对比：目标 backend 148MB→<40MB，p99 不升
