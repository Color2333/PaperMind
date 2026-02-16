# PaperMind 技术细节落地说明

本文严格对应 `PaperMind.md` 的模块 A/B/C/D 与 Phase 1/2/3。

## 模块 A: 数据获取与自动化（Harvester）

- 多源入口
  - 已实现 `ArXiv API` 抓取：`packages/integrations/arxiv_client.py`
  - 已实现 `Semantic Scholar` 引用同步入口：`packages/integrations/semantic_scholar_client.py`
- 调度
  - `APScheduler` 按 `DAILY_CRON` 运行：`apps/worker/main.py`
  - `WEEKLY_CRON` 运行图谱维护任务（批量引用同步 + 增量补边）
  - 增量机制通过 `source_checkpoints` 记录上次抓取点
  - 主题支持配额与重试：`max_results_per_run`、`retry_limit`
- 存储
  - PDF 本地落盘：`PDF_STORAGE_ROOT`
  - 元数据 SQLite：`papers`、`pipeline_runs` 等

## 模块 B: AI 阅读引擎（Reader Agent）

- 粗读（Skim）
  - Prompt 输出结构化 JSON（one_liner / innovations / relevance_score）
  - 相关度阈值决定是否触发 deep dive：`SKIM_SCORE_THRESHOLD`
- 精读（Deep Dive）
  - Vision-first 描述：`packages/ai/vision_reader.py`
  - PDF 文本层 fallback：`packages/ai/pdf_parser.py`（可选 PyMuPDF）
  - 输出 Method/Experiments/Ablation/Reviewer Risks
- 成本保护
  - 预算守卫：`packages/ai/cost_guard.py`
  - 支持单次与日预算降级：`PER_CALL_BUDGET_USD`、`DAILY_BUDGET_USD`
  - 决策落库：`pipeline_runs.decision_note`

## 模块 C: 知识图谱与脉络（Historian）

- 引用边同步
  - `POST /citations/sync/{paper_id}` 从 Scholar 拉取引用关系并写入 `citations`
  - `POST /citations/sync/topic/{topic_id}` 批量按主题同步引用
- 引用树
  - `GET /graph/citation-tree/{paper_id}` 输出祖先/后代边
- 时间线与 seminal
  - `GET /graph/timeline?keyword=...` 输出按年份排序的 timeline + indegree top seminal
  - 当前 seminal 分数使用 `0.65*indegree + 0.35*pagerank*100`
  - 每个节点会返回 `why_seminal` 解释字段，便于可解释性分析
- 图谱质量指标
  - `GET /graph/quality?keyword=...` 返回节点数、边数、密度、连通节点占比、出版时间覆盖率
- 增量维护与演进总结
  - `POST /citations/sync/incremental` 对缺边论文做增量补齐
  - `GET /graph/evolution/weekly?keyword=...` 输出最近年份桶趋势与下周关注点
- 领域综述与 Wiki 化
  - `GET /graph/survey?keyword=...` 生成结构化 survey（overview/stages/reading_list/open_questions）
  - `GET /wiki/paper/{paper_id}` 生成单论文 Wiki markdown
  - `GET /wiki/topic?keyword=...` 生成主题 Wiki markdown

## 模块 D: 向量记忆与问答（Memory & RAG）

- 向量化
  - 目前使用 JSON 存储 embedding（SQLite 模式）
  - Provider 可用时走真实 embedding，否则本地 fallback
- 关联推荐
  - SQLite 模式下使用 Python 余弦距离排序
- 跨文档问答
  - RAG 上下文来源：标题、摘要、粗读摘要、深读片段
  - 检索策略：词法召回 + embedding 语义召回（hybrid）
  - 返回证据片段 `evidence`（paper_id/title/snippet/source）
  - 输出 JSON 规范化 answer

## Phase 路线对照

- Phase 1（基础设施与每日追踪）
  - 已完成：主题订阅、增量抓取、粗读、日报、定时调度
- Phase 2（深度阅读与 RAG）
  - 已完成：Deep Dive 结构化输出、RAG 上下文增强、成本观测
- Phase 3（知识图谱与脉络）
  - 已完成：引用同步、citation tree、timeline + seminal 计算
- Phase 4（macOS 客户端）
  - 当前后端已预留 API，可直接接桌面客户端

## 关键 API 清单

- 主题与抓取：
  - `GET/POST/PATCH/DELETE /topics`
  - `POST /ingest/arxiv`
- 阅读流水线：
  - `POST /pipelines/skim/{paper_id}`
  - `POST /pipelines/deep/{paper_id}`
  - `POST /pipelines/embed/{paper_id}`
- RAG 与推荐：
  - `POST /rag/ask`
  - `GET /papers/{paper_id}/similar`
- 图谱：
  - `POST /citations/sync/{paper_id}`
  - `GET /graph/citation-tree/{paper_id}`
  - `GET /graph/timeline`
- 运维观测：
  - `GET /metrics/costs`
  - `GET /pipelines/runs`
