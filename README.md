<div align="center">

<br/>

<img src="https://img.shields.io/badge/PaperMind-AI_Research_Workflow-667eea?style=for-the-badge&labelColor=1a1a2e" alt="PaperMind" height="42"/>

<br/><br/>

**AI 驱动的学术论文研究工作流平台**

*从「搜索论文」进化为「理解领域」*

<br/>

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React_18-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://typescriptlang.org)
[![Tailwind](https://img.shields.io/badge/Tailwind_CSS_v4-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white)](https://tailwindcss.com)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white)](https://sqlite.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Version](https://img.shields.io/badge/Version-v3.0-667eea?style=flat-square)](CHANGELOG)

<br/>

<img src="https://img.shields.io/badge/LLM-OpenAI_%7C_Anthropic_%7C_ZhipuAI-blueviolet?style=for-the-badge" alt="LLM Support"/>

<br/><br/>

> 通过自动化 Agent 和 LLM，将海量文献转化为结构化的知识图谱，
> 辅助研究者完成从「每日追踪」到「深度调研」的全过程。

</div>

---

## ✨ 核心能力

<table>
<tr>
<td width="50%">

### 🤖 AI Agent 对话

- SSE 流式对话，Claude 风格交互
- 22+ 工具链自动调度（搜索、入库、分析、生成、写作）
- 用户确认机制 + 实时进度反馈
- 论文候选筛选 → 用户挑选 → 选择性入库
- AI 关键词建议：自然语言描述 → arXiv 搜索词
- **对话历史持久化**：localStorage 存储，切换对话秒级恢复

</td>
<td width="50%">

### 📄 智能论文管理

- ArXiv 增量抓取 + 主题订阅（自定义频率与时间）
- **论文去重检测**：避免重复粗读/嵌入/精读，节省 token
- **递归抓取**：自动向更早期延伸，保证每次都有新论文
- 粗读 / 精读 / 向量嵌入全流程（并行加速）
- 论文库分页 + 按主题 / 收录日期 / 收藏分类导航
- **按需下载 PDF**：入库时不下载，精读时才拉取，节省带宽

</td>
</tr>
<tr>
<td width="50%">

### 🔍 RAG 知识问答

- 向量检索 + 全文检索双路召回
- 跨论文综合分析
- 答案自动生成 Artifact 卡片
- 引用证据可追溯

</td>
<td width="50%">

### 🕸️ 引用图谱 & 参考文献导入

- **丰富引用详情**（Semantic Scholar 全字段：作者/会议/引用数/摘要）
- **参考文献一键入库**：批量选择 → arXiv 全量/SS 元数据双通道导入
- 力导向图可视化（单篇引用网络 / 主题互引网络）
- 全局概览（桥接论文 / 研究前沿 / 共引聚类）
- 领域洞察（时间线 / 演化 / 质量 / 研究空白一键查询）

</td>
</tr>
<tr>
<td width="50%">

### 📚 Wiki 自动生成

- 主题 Wiki / 论文 Wiki
- 多轮 LLM 大纲→章节生成
- **异步任务追踪**：实时进度条，生成完成后自动刷新
- Canvas 侧面板实时预览
- 生成内容持久化 + 历史查看

</td>
<td width="50%">

### 🎯 个性化推荐 & 趋势

- 基于阅读历史的论文推荐
- 热点关键词 + 新兴方向检测
- 今日研究速览着陆页
- **每日简报异步生成**：提交后轮询进度，完成自动展示

</td>
</tr>
<tr>
<td width="50%">

### ✍️ 学术写作助手

- **13 种写作工具**：中转英、英转中、中/英文润色、缩写、扩写
- 逻辑检查、去 AI 味、图/表标题生成
- 实验数据分析、Reviewer 视角审视、图表推荐
- Agent 内置写作工具，对话中直接调用
- Prompt 模板来自 [awesome-ai-research-writing](https://github.com/Leey21/awesome-ai-research-writing)

</td>
<td width="50%">

### 📖 沉浸式 PDF 阅读器

- 连续滚动阅读，IntersectionObserver 页码追踪
- 缩放 / 全屏 / 页码跳转 / 键盘快捷键
- **混合加载策略**：优先本地文件，无本地则代理 arXiv 在线 PDF（解决 CORS）
- **选中文本 → AI 解释 / 翻译 / 总结**
- 右侧 AI 侧栏，Markdown + LaTeX 渲染

</td>
</tr>
<tr>
<td width="50%">

### 🔬 多模态深度分析

- PDF 图表提取 + Vision 模型解读
- 推理链深度分析（5 步推理 + 3 维评分）
- 研究空白识别（引用稀疏区域 + 方法矩阵）
- LLM 成本全链路追踪（completion / embedding / vision）

</td>
<td width="50%">

### ⚙️ 全局任务追踪系统

- 所有长任务（Wiki / 简报 / 图表分析 / 粗读）统一异步化
- 实时进度条（前端 2s 轮询）
- Pipeline 追踪：覆盖所有操作 + token 消耗
- 任务完成后自动刷新 UI，无需手动刷新页面

</td>
</tr>
</table>

---

## 📸 界面预览

<table>
<tr>
<td align="center" width="50%">
<strong>🤖 AI Agent 对话主页</strong><br/><br/>
<img src="scripts/screenshots/full/01-01-agent-home.png" alt="Agent Home" width="100%"/>
<br/><sub>智能 Agent 对话 · 论文推荐 · 热点追踪 · 一站式研究入口</sub>
</td>
<td align="center" width="50%">
<strong>📄 论文库管理</strong><br/><br/>
<img src="scripts/screenshots/full/03-03-papers-list.png" alt="Papers List" width="100%"/>
<br/><sub>主题分类 · 按日期分组 · 阅读状态 · 批量操作</sub>
</td>
</tr>
<tr>
<td align="center" width="50%">
<strong>📋 论文详情 & 分析</strong><br/><br/>
<img src="scripts/screenshots/full/20-paper-detail-direct.png" alt="Paper Detail" width="100%"/>
<br/><sub>粗读 / 精读 / 图表解读 / 推理链 · 一键多维分析</sub>
</td>
<td align="center" width="50%">
<strong>📖 沉浸式 PDF 阅读器</strong><br/><br/>
<img src="scripts/screenshots/full/21-pdf-reader.png" alt="PDF Reader" width="100%"/>
<br/><sub>连续滚动 · 缩放全屏 · 选中文本 AI 解释 · arXiv 在线代理</sub>
</td>
</tr>
<tr>
<td align="center" width="50%">
<strong>🕸️ 知识图谱 & 引文分析</strong><br/><br/>
<img src="scripts/screenshots/full/08-09-graph.png" alt="Graph Explorer" width="100%"/>
<br/><sub>领域时间线 · 引用树 · 质量评估 · 演化趋势 · 研究空白</sub>
</td>
<td align="center" width="50%">
<strong>📊 Dashboard 系统看板</strong><br/><br/>
<img src="scripts/screenshots/full/13-14-dashboard.png" alt="Dashboard" width="100%"/>
<br/><sub>论文统计 · 成本分析 · Pipeline 活动 · 系统健康</sub>
</td>
</tr>
<tr>
<td align="center" width="50%">
<strong>📚 Wiki 自动生成</strong><br/><br/>
<img src="scripts/screenshots/full/11-12-wiki.png" alt="Wiki" width="100%"/>
<br/><sub>主题 Wiki / 论文 Wiki · LLM 多轮生成 · 历史回溯</sub>
</td>
<td align="center" width="50%">
<strong>🌙 暗色主题</strong><br/><br/>
<img src="scripts/screenshots/full/16-17-dark-theme.png" alt="Dark Theme" width="100%"/>
<br/><sub>全局暗色模式 · 护眼阅读 · 一键切换</sub>
</td>
</tr>
</table>

---

## 🏗️ 架构总览

```
┌─────────────────────────────────────────────────────────┐
│                   Frontend (React 18)                    │
│ Agent│Papers│Wiki│Graph│Brief│Collect│Writing│...       │
│   ┌─ 路由懒加载 ─ Vite 代码分割 ─ useMemo 优化 ─┐      │
│   └─ AgentSessionContext (SSE 跨页保活) ─────────┘      │
└───────────────────────┬─────────────────────────────────┘
                        │ REST + SSE
┌───────────────────────┴─────────────────────────────────┐
│                    FastAPI Backend                        │
├───────────┬──────────┬───────────┬──────────────────────┤
│  Agent    │ Pipeline │   RAG     │   Graph / Wiki /     │
│  Service  │  Engine  │ Service   │   Brief / Recommend  │
├───────────┴──────────┴───────────┴──────────────────────┤
│        Global TaskTracker (统一异步任务 + 进度追踪)       │
├─────────────────────────────────────────────────────────┤
│           Unified LLM Client (连接复用 + TTL 缓存)       │
│         OpenAI  │  Anthropic  │  ZhipuAI               │
├─────────────────────────────────────────────────────────┤
│   SQLite (WAL + 索引优化)  │  ArXiv  │  Semantic Scholar│
└─────────────────────────────────────────────────────────┘
              │
    ┌─────────┴──────────┐
    │  APScheduler Worker │
    │  按主题独立调度      │
    │  (每小时 dispatch)  │
    └────────────────────┘
```

---

## 🚀 快速开始

### 前置要求

- Python 3.11+
- Node.js 18+
- LLM API Key（OpenAI / Anthropic / 智谱 任选其一）

### 1️⃣ 后端

```bash
# 克隆项目
git clone <repo-url> && cd PaperMind

# 创建虚拟环境
python -m venv .venv && source .venv/bin/activate

# 安装依赖
pip install -e ".[llm,pdf]"

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入 API Key

# 初始化数据库（含 Alembic 迁移）
python scripts/local_bootstrap.py

# 启动 API 服务
uvicorn apps.api.main:app --reload --port 8000
```

### 2️⃣ 前端

```bash
cd frontend
npm install
npm run dev
# 🌐 打开 http://localhost:5173
```

### 3️⃣ 后台调度器（可选）

```bash
# 启动定时任务（按主题独立调度 + 每日简报 + 每周图谱维护）
python -m apps.worker.main
```

### 4️⃣ Docker 一键部署（生产）

```bash
cp .env.example .env
# 编辑 .env 填入所有 Key（含 SITE_URL=https://你的域名）

docker compose up -d --build
# 三容器：backend / worker / frontend(nginx)
```

---

## ⚙️ 环境变量

> 完整模板参见 `.env.example`

| 变量 | 说明 | 默认值 |
|:-----|:-----|:------:|
| `LLM_PROVIDER` | LLM 提供商 | `zhipu` |
| `ZHIPU_API_KEY` | 智谱 API Key | — |
| `LLM_MODEL_SKIM` | 粗读模型 | `glm-4.7` |
| `LLM_MODEL_DEEP` | 精读模型 | `glm-4.7` |
| `LLM_MODEL_VISION` | 视觉模型（PDF 精读） | `glm-4.6v` |
| `EMBEDDING_MODEL` | 嵌入模型 | `embedding-3` |
| `SITE_URL` | 生产域名（邮件链接用） | `http://localhost:5173` |
| `COST_GUARD_ENABLED` | 成本守卫 | `true` |
| `DAILY_BUDGET_USD` | 每日预算（美元） | `2.0` |
| `DAILY_CRON` | 每日简报 Cron（UTC） | `0 21 * * *` |
| `WEEKLY_CRON` | 每周图谱 Cron（UTC） | `0 22 * * 0` |

也可通过前端 **Settings** 页面动态管理多个 LLM 配置，在线切换。

> **调度说明**：论文收集不再依赖全局 CRON，每个订阅主题可独立设置频率和时间。

---

## 🗂️ 项目结构

```
PaperMind/
├── apps/
│   ├── api/                  # FastAPI 入口 & 路由
│   └── worker/               # APScheduler 按主题独立调度
├── packages/
│   ├── ai/                   # 核心 AI 能力
│   │   ├── agent_service     #   Agent 对话引擎
│   │   ├── agent_tools       #   Agent 工具定义（22 个）
│   │   ├── pipelines         #   论文处理流水线（并行）
│   │   ├── rag_service       #   RAG 检索问答
│   │   ├── graph_service     #   引用图谱 & Wiki
│   │   ├── figure_service    #   PDF 图表提取 + Vision 解读
│   │   ├── reasoning_service #   推理链深度分析
│   │   ├── brief_service     #   每日简报（含推荐 + 趋势）
│   │   ├── recommendation    #   个性化推荐 + 趋势检测
│   │   ├── writing_service   #   学术写作助手（13 种 Prompt 模板）
│   │   ├── keyword_service   #   AI 关键词建议
│   │   ├── daily_runner      #   定时任务编排
│   │   ├── cost_guard        #   成本控制
│   │   └── prompts           #   Prompt 模板
│   ├── domain/               # 领域枚举 & Pydantic Schema
│   │   └── task_tracker      #   全局异步任务追踪器（统一生命周期）
│   ├── integrations/         # 外部集成
│   │   ├── llm_client        #   统一 LLM 客户端（复用 + 缓存）
│   │   ├── arxiv_client      #   ArXiv API
│   │   └── semantic_scholar  #   Semantic Scholar API
│   ├── storage/              # 数据层
│   │   ├── models            #   SQLAlchemy ORM
│   │   ├── repositories      #   数据仓储
│   │   └── db                #   数据库引擎 + 迁移
│   └── config.py             # 应用配置
├── frontend/
│   └── src/
│       ├── components/       # UI 组件库（PDF 阅读器、Graph 三面板、Toast）
│       ├── contexts/         # React Context（Agent 会话 + 对话历史）
│       ├── hooks/            # 自定义 Hooks（useConversations 等）
│       ├── pages/            # 页面组件（懒加载）
│       ├── services/         # API 服务层
│       └── types/            # TypeScript 类型
├── infra/                    # Alembic 数据库迁移
├── scripts/                  # 初始化 & 工具脚本
├── .env.example              # 环境变量模板
└── pyproject.toml            # Python 依赖定义
```

---

## 📡 API 速览

<details>
<summary><strong>📋 系统 & 论文</strong></summary>

| 方法 | 路径 | 说明 |
|:----:|:-----|:-----|
| GET | `/health` | 健康检查 |
| GET | `/system/status` | 系统状态总览 |
| GET | `/papers/latest` | 论文列表（**分页** + 状态 / 主题 / 日期筛选） |
| GET | `/papers/folder-stats` | 文件夹统计（含按日期分组） |
| GET | `/papers/recommended` | 个性化推荐论文 |
| GET | `/papers/{id}` | 论文详情 |
| GET | `/papers/{id}/pdf` | **PDF 文件流**（浏览器内阅读） |
| GET | `/papers/{id}/pdf-proxy` | **arXiv PDF 代理**（解决 CORS） |
| GET | `/papers/{id}/similar` | 相似论文 |
| POST | `/papers/{id}/ai/explain` | **AI 文本解释 / 翻译 / 总结** |
| GET | `/papers/{id}/figures` | 图表解读结果 |
| POST | `/papers/{id}/figures/analyze` | 触发图表解读（Vision） |
| POST | `/papers/{id}/reasoning` | 推理链深度分析 |
| GET | `/today` | 今日研究速览 |

</details>

<details>
<summary><strong>🤖 AI Agent</strong></summary>

| 方法 | 路径 | 说明 |
|:----:|:-----|:-----|
| POST | `/agent/chat` | Agent 对话（SSE 流式） |
| POST | `/agent/confirm/{action_id}` | 确认工具执行 |
| POST | `/agent/reject/{action_id}` | 拒绝工具执行 |
| GET | `/agent/conversations` | 对话历史列表 |
| GET | `/agent/conversations/{id}/messages` | 单条对话完整消息 |

</details>

<details>
<summary><strong>⚡ AI 流水线</strong></summary>

| 方法 | 路径 | 说明 |
|:----:|:-----|:-----|
| POST | `/pipelines/skim/{paper_id}` | 粗读 |
| POST | `/pipelines/deep/{paper_id}` | 精读 |
| POST | `/pipelines/embed/{paper_id}` | 向量嵌入 |
| GET | `/pipelines/runs` | 运行记录 |
| POST | `/ingest/arxiv` | ArXiv 论文摄入 |
| POST | `/ingest/references` | **参考文献一键导入**（后台任务） |
| GET | `/ingest/references/status/{task_id}` | 导入进度轮询 |

</details>

<details>
<summary><strong>🔍 RAG & 图谱</strong></summary>

| 方法 | 路径 | 说明 |
|:----:|:-----|:-----|
| POST | `/rag/ask` | RAG 检索问答 |
| GET | `/graph/citation-tree/{paper_id}` | 引文树 |
| GET | `/graph/citation-detail/{paper_id}` | **丰富引用详情**（SS 全字段） |
| GET | `/graph/citation-network/topic/{id}` | 主题级引用网络 |
| POST | `/graph/citation-network/topic/{id}/deep-trace` | 主题深度溯源 |
| GET | `/graph/overview` | 全局概览（节点/边/主题统计） |
| GET | `/graph/bridges` | 桥接论文（跨主题引用） |
| GET | `/graph/frontier` | 研究前沿（高引+高被引） |
| GET | `/graph/cocitation-clusters` | 共引聚类分析 |
| GET | `/graph/timeline` | 领域时间线 |
| GET | `/graph/evolution/weekly` | 演化分析 |
| GET | `/graph/research-gaps` | 研究空白识别 |
| GET | `/graph/quality` | 图谱质量评估 |

</details>

<details>
<summary><strong>📚 Wiki & 简报 & 趋势</strong></summary>

| 方法 | 路径 | 说明 |
|:----:|:-----|:-----|
| POST | `/tasks/wiki/topic` | **异步**生成主题 Wiki（返回 task_id） |
| GET | `/wiki/paper/{paper_id}` | 论文 Wiki |
| POST | `/brief/daily` | **异步**生成每日简报（返回 task_id） |
| GET | `/generated/list` | 生成内容历史 |
| GET | `/generated/{content_id}` | 内容详情 |
| GET | `/trends/hot` | 热点关键词 |
| GET | `/trends/emerging` | 新兴趋势 |

</details>

<details>
<summary><strong>⏱️ 任务追踪</strong></summary>

| 方法 | 路径 | 说明 |
|:----:|:-----|:-----|
| GET | `/tasks/active` | 所有活跃任务列表 |
| GET | `/tasks/{task_id}` | 单任务状态查询 |
| GET | `/tasks/{task_id}/result` | 任务结果获取 |

</details>

<details>
<summary><strong>✍️ 写作助手</strong></summary>

| 方法 | 路径 | 说明 |
|:----:|:-----|:-----|
| GET | `/writing/templates` | 获取全部写作模板列表 |
| POST | `/writing/process` | 执行写作操作（翻译/润色/去AI味等） |

</details>

<details>
<summary><strong>⚙️ 配置 & 管理</strong></summary>

| 方法 | 路径 | 说明 |
|:----:|:-----|:-----|
| GET | `/topics` | 主题列表（含调度配置） |
| POST | `/topics` | 创建主题（含频率/时间） |
| PATCH | `/topics/{id}` | 更新主题 |
| POST | `/topics/suggest-keywords` | AI 关键词建议 |
| GET | `/settings/llm-providers` | LLM 配置列表 |
| POST | `/settings/llm-providers` | 新增 LLM 配置 |
| POST | `/settings/llm-providers/{id}/activate` | 激活配置 |
| GET | `/actions` | 入库行动记录列表 |
| GET | `/metrics/costs` | 成本统计（含 Agent 消耗） |
| POST | `/jobs/daily/run-once` | 手动触发每日任务 |
| POST | `/jobs/graph/weekly-run-once` | 手动触发图谱维护 |

</details>

---

## 🖥️ 前端页面

| 页面 | 路由 | 说明 |
|:-----|:-----|:-----|
| **Agent** | `/` | AI 对话主界面 + 今日研究速览（推荐、热点、统计）+ 对话历史侧边栏 |
| **Papers** | `/papers` | 论文库（分页），按主题 / 收录日期 / 收藏筛选，批量操作 |
| **Paper Detail** | `/papers/:id` | 详情 + 粗读 / 精读 / 嵌入 + **PDF 阅读器** + 图表解读 + 推理链 |
| **Collect** | `/collect` | 论文收集 + 订阅管理（频率/时间/AI 关键词建议） |
| **Writing** | `/writing` | 学术写作助手（13 种工具 + Prompt 模板） |
| **Wiki** | `/wiki` | Wiki 异步生成 + 实时进度条 + Canvas 侧面板 + 历史 |
| **Graph** | `/graph` | **三面板**：全局概览 / 引文分析（含一键入库） / 领域洞察 |
| **Brief** | `/brief` | 每日简报异步生成 + 实时进度 + 历史查看 |
| **Dashboard** | `/dashboard` | 系统看板 + 成本统计 |
| **Pipelines** | `/pipelines` | 流水线运行记录 |
| **Operations** | `/operations` | 摄入 / 同步 / 任务触发 |

---

## ⚡ 性能优化

| 类别 | 优化 |
|------|------|
| **前端首屏** | 路由懒加载（Agent 页直接加载，其余 `React.lazy`），Vite `manualChunks` 分割 vendor/markdown/icons |
| **前端渲染** | Context value `useMemo`，列表 `useMemo` + `useCallback`，关键组件 `React.memo` |
| **SSE 流** | RAF 批量 flush 减少 setItems 调用，跨页面保活不断流 |
| **LLM 调用** | OpenAI 客户端连接复用，配置 30s TTL 缓存，120s 请求超时 |
| **数据库** | SQLite WAL + `synchronous=NORMAL` + 64MB cache + `temp_store=MEMORY` |
| **查询** | 关键列索引（created_at, read_status），向量检索候选池 500 上限 |
| **分页** | 论文列表后端分页（page + page_size），按日期分组统计 |
| **论文处理** | embed ∥ skim 并行，3 篇论文同时处理；入库不下载 PDF 节省带宽 |
| **去重** | 论文入库前检测重复，跳过已处理论文避免浪费 token |
| **成本追踪** | LLM `trace_result` 集中式追踪，覆盖全链路 completion / embedding / vision |

---

## 📋 更新日志

### v3.0 (2026-02-28) — 稳定性全面升级

**新功能**
- Agent 对话历史完整持久化（localStorage + 工具调用/artifact 全记录）
- PDF arXiv 在线代理，解决 CORS 无法阅读在线论文问题
- 论文去重检测，避免重复处理浪费 token
- 递归抓取更早期论文，保证每次订阅都有新内容
- 全局任务追踪系统（Wiki / 简报 / 图表分析全部异步化）
- 每日简报前端实时轮询进度，生成完成自动展示
- `SITE_URL` 配置支持，邮件链接正确指向生产域名

**Bug 修复**
- 修复点击历史对话不显示内容（React state 异步竞态）
- 修复 Wiki 生成一秒失败（progress_callback 签名不匹配）
- 修复 Agent 对话历史 `async for` 迭代同步 generator 报错
- 修复 `agent_messages` 表缺少 `paper_id / markdown / metadata_json` 列
- 修复 nginx 非法正则 location 导致前端容器 crash
- 修复 nginx `.mjs` MIME type 缺失导致 PDF.js worker 加载失败
- 修复 `brief_service` logger 未定义 / 死代码 / LLM 调用方法错误
- 修复 FastAPI `Query(regex=...)` deprecated 警告
- 修复 `repositories.py` 多处导入缺失 / 方法误删 / 代码混入
- 修复定时任务 `DetachedInstanceError`（Session 关闭后访问 ORM 对象）
- 修复 Semantic Scholar API 429 限速重试策略

### v2.8 (历史)

后端重构 + Agent 智能化 + 全局任务追踪 + 系统稳健性全面升级

### v2.7 (历史)

多源引用 + 相似度地图 + 迭代 RAG + 深度体验优化

---

## 🔧 开发

```bash
# 后端 lint
python -m ruff check .

# 前端类型检查
cd frontend && npx tsc --noEmit

# 数据库迁移（新表需要写迁移文件）
cd infra && alembic revision --autogenerate -m "描述"
alembic upgrade head
```

---

## 🙏 致谢

- **[awesome-ai-research-writing](https://github.com/Leey21/awesome-ai-research-writing)** — 写作助手的 Prompt 模板库来源，由 MSRA、Seed、SH AI Lab 等顶尖研究机构的研究员实战打磨

---

## 📄 License

[MIT](LICENSE)

---

<div align="center">

**Built with ❤️ by Color2333**

*PaperMind — 让 AI 帮你读论文，让知识触手可及。*

</div>
