# PaperMind 2.1 — Go 全量重写计划（绞杀者模式）

> 决策：backend/worker 全量迁 Go。方式：绞杀者渐进替换——每个路由/handler
> 独立迁移、独立验证，Python 在全部迁移完成前保持可用（Go 未覆盖的路由
> 自动反代到 Python）。

## 接缝（零改动保证）

- **入口**：frontend nginx `/api/` → `goserver:8080`（compose 挂载
  `infra/nginx.goserver.conf`，前端镜像零重建）
- **回退**：Go 未实现的路由透明反代 `backend:8000`（SSE 立即冲刷）
- **验收**：每条路由迁移后用原前端/CLI 真机回归，行为逐字节对齐

## Phase 0（已完成，db4fc9c）

- 服务骨架：chi 式路由（stdlib pattern）+ lib/pq + golang-jwt/v5
- 设备码授权全流程移植（start/poll/info/authorize/deny）：
  SHA-256 哈希 / 15min 过期 / 5s 节流 / approved 首轮签发 API 令牌，
  python-jose 签名兼容性测试
- folder-stats 移植；未移植路由反代回退；server/Dockerfile（~15MB 静态二进制）

## Phase 1（读路径）

- [ ] GET /papers/latest（port list_papers 查询：page/status/topic/search）
- [ ] GET /papers/{id}（详情+研究状态）
- [ ] GET /questions/* /claims/* /diff（研究状态读面）
- [ ] GET /jobs /tasks（Go Core 本就在同进程——直接查库替代反代）

## Phase 2（写路径 + 任务提交）

- [ ] POST /ingest/*（submit_job → Go Core 本直连）
- [ ] topics/subscriptions CRUD
- [ ] settings/tokens 管理端点
- [ ] POST /auth/web/*（GitHub OAuth 回调 + JWT 签发，替换 Python web 会话）

## Phase 3（worker handler 移植）

- [ ] embed_paper（HTTP 调网关，Go 天然适配）
- [ ] sync_citations_*（S2 HTTP + 限流）
- [ ] ingest_arxiv / cs_feed（HTTP + XML）
- [ ] deep_read（PDF 文本：poppler 外挂 or go-pdfium；视觉：页图→网关）
- [ ] brief / wiki 生成（LLM + html/template）

## Phase 4（研究计算决策点）

- [ ] 研究状态散点图：UMAP(scikit-learn) → gonum PCA 降级 or 保留微 Python sidecar
- [ ] 全量切换：nginx /api/ 直接去掉 backend 反代
- [ ] 删除 Python（apps/ + packages/）

## 验收标准（每 Phase 通用）

1. pytest 全量绿（未迁移部分）；Go test 绿（已迁移部分）
2. 真机回归：pm CLI 三形态 + Web 全功能
3. 内存/延迟对比报告（目标：backend 148MB→<40MB，p99 延迟不升）
