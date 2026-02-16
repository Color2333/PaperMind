<div align="center">

# 🧠 PaperMind

**AI 驱动的学术论文研究工作流平台**

*从「搜索论文」进化为「理解领域」*

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React_18-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://typescriptlang.org)
[![Tailwind](https://img.shields.io/badge/Tailwind_CSS_v4-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white)](https://tailwindcss.com)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

<br/>

<img src="https://img.shields.io/badge/LLM-OpenAI_%7C_Anthropic_%7C_ZhipuAI-blueviolet?style=for-the-badge" alt="LLM Support"/>

</div>

<br/>

> 通过自动化 Agent 和 LLM，将海量文献转化为结构化的知识图谱，辅助研究者完成从「每日追踪」到「深度调研」的全过程。

---

## ✨ 核心能力

<table>
<tr>
<td width="50%">

### 🤖 AI Agent 对话

- SSE 流式对话，Claude 风格交互
- 17 个工具链自动调度
- 用户确认机制 + 实时进度反馈
- 会话持久化 + 跨页面状态保持

</td>
<td width="50%">

### 📄 智能论文管理

- ArXiv 增量抓取 + 主题订阅
- 粗读 / 精读 / 向量嵌入全流程
- 关键词提取 + 中英双语翻译
- 分类标签 + 阅读状态流转

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

### 🕸️ 引用图谱

- 引文树可视化（祖先 / 后代）
- 领域时间线 + 里程碑论文
- 演化趋势分析
- PageRank 经典论文识别

</td>
</tr>
<tr>
<td width="50%">

### 📚 Wiki 自动生成

- 主题 Wiki / 论文 Wiki
- 多轮 LLM 大纲→章节生成
- Canvas 侧面板实时预览
- 生成内容持久化 + 历史查看

</td>
<td width="50%">

### 📊 每日简报 & 成本管控

- 定时自动生成研究简报
- Prompt 追踪 + Token 统计
- 每日 / 单次预算守卫
- 超预算自动降级模型

</td>
</tr>
</table>

---

## 🏗️ 架构总览

```
┌─────────────────────────────────────────────────────┐
│                   Frontend (React 18)                │
│   Agent │ Papers │ Wiki │ Graph │ Brief │ Settings   │
└────────────────────────┬────────────────────────────┘
                         │ REST + SSE
┌────────────────────────┴────────────────────────────┐
│                  FastAPI Backend                      │
├──────────┬──────────┬──────────┬────────────────────┤
│  Agent   │ Pipeline │   RAG    │   Graph Service    │
│ Service  │  Engine  │ Service  │   Wiki / Brief     │
├──────────┴──────────┴──────────┴────────────────────┤
│              Unified LLM Client                      │
│        OpenAI  │  Anthropic  │  ZhipuAI             │
├─────────────────────────────────────────────────────┤
│    SQLite (WAL)  │  ArXiv API  │  Semantic Scholar  │
└─────────────────────────────────────────────────────┘
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

# 初始化数据库
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
# 启动定时任务（每日自动抓取 + 粗读 + 简报生成）
python -m apps.worker.main
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
| `COST_GUARD_ENABLED` | 成本守卫 | `true` |
| `DAILY_BUDGET_USD` | 每日预算（美元） | `2.0` |
| `DAILY_CRON` | 每日任务 Cron | `0 2 * * *` |
| `WEEKLY_CRON` | 每周任务 Cron | `0 3 * * 1` |

也可通过前端 **Settings** 页面动态管理多个 LLM 配置，在线切换。

---

## 🗂️ 项目结构

```
PaperMind/
├── apps/
│   ├── api/                # FastAPI 入口 & 路由
│   └── worker/             # APScheduler 定时任务
├── packages/
│   ├── ai/                 # 核心 AI 能力
│   │   ├── agent_service   #   Agent 对话引擎
│   │   ├── agent_tools     #   Agent 工具定义
│   │   ├── pipelines       #   论文处理流水线
│   │   ├── rag_service     #   RAG 检索问答
│   │   ├── graph_service   #   引用图谱 & Wiki
│   │   ├── brief_service   #   每日简报
│   │   ├── cost_guard      #   成本控制
│   │   └── prompts         #   Prompt 模板
│   ├── domain/             # 领域枚举 & Pydantic Schema
│   ├── integrations/       # 外部集成
│   │   ├── llm_client      #   统一 LLM 客户端
│   │   ├── arxiv_client    #   ArXiv API
│   │   └── semantic_scholar#   Semantic Scholar API
│   ├── storage/            # 数据层
│   │   ├── models          #   SQLAlchemy ORM
│   │   ├── repositories    #   数据仓储
│   │   └── db              #   数据库引擎
│   └── config.py           # 应用配置
├── frontend/
│   └── src/
│       ├── components/     # UI 组件库
│       ├── contexts/       # React Context（Agent 状态）
│       ├── hooks/          # 自定义 Hooks
│       ├── pages/          # 页面组件
│       ├── services/       # API 服务层
│       └── types/          # TypeScript 类型
├── infra/                  # Alembic 数据库迁移
├── scripts/                # 初始化 & 工具脚本
├── .env.example            # 环境变量模板
└── pyproject.toml          # Python 依赖定义
```

---

## 📡 API 速览

<details>
<summary><strong>📋 系统 & 论文</strong></summary>

| 方法 | 路径 | 说明 |
|:----:|:-----|:-----|
| GET | `/health` | 健康检查 |
| GET | `/system/status` | 系统状态总览 |
| GET | `/papers/latest` | 论文列表（支持状态 / 主题筛选） |
| GET | `/papers/{id}` | 论文详情 |
| GET | `/papers/{id}/similar` | 相似论文 |

</details>

<details>
<summary><strong>🤖 AI Agent</strong></summary>

| 方法 | 路径 | 说明 |
|:----:|:-----|:-----|
| POST | `/agent/chat` | Agent 对话（SSE 流式） |
| POST | `/agent/confirm/{action_id}` | 确认工具执行 |
| POST | `/agent/reject/{action_id}` | 拒绝工具执行 |

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

</details>

<details>
<summary><strong>🔍 RAG & 图谱</strong></summary>

| 方法 | 路径 | 说明 |
|:----:|:-----|:-----|
| POST | `/rag/ask` | RAG 检索问答 |
| GET | `/graph/citation-tree/{paper_id}` | 引文树 |
| GET | `/graph/timeline` | 领域时间线 |
| GET | `/graph/evolution/weekly` | 演化分析 |
| GET | `/graph/survey` | 综述生成 |
| GET | `/graph/quality` | 图谱质量评估 |

</details>

<details>
<summary><strong>📚 Wiki & 简报</strong></summary>

| 方法 | 路径 | 说明 |
|:----:|:-----|:-----|
| GET | `/wiki/paper/{paper_id}` | 论文 Wiki |
| GET | `/wiki/topic` | 主题 Wiki |
| POST | `/brief/daily` | 生成每日简报 |
| GET | `/generated/list` | 生成内容历史 |
| GET | `/generated/{content_id}` | 内容详情 |

</details>

<details>
<summary><strong>⚙️ 配置 & 管理</strong></summary>

| 方法 | 路径 | 说明 |
|:----:|:-----|:-----|
| GET | `/topics` | 主题列表 |
| POST | `/topics` | 创建主题 |
| PATCH | `/topics/{id}` | 更新主题 |
| GET | `/settings/llm-providers` | LLM 配置列表 |
| POST | `/settings/llm-providers` | 新增 LLM 配置 |
| POST | `/settings/llm-providers/{id}/activate` | 激活配置 |
| GET | `/metrics/costs` | 成本统计 |
| POST | `/jobs/daily/run-once` | 手动触发每日任务 |
| POST | `/jobs/graph/weekly-run-once` | 手动触发图谱维护 |

</details>

---

## 🖥️ 前端页面

| 页面 | 路由 | 说明 |
|:-----|:-----|:-----|
| **Agent** | `/` | AI 对话主界面，SSE 流式 + 工具调用 + Artifact |
| **Papers** | `/papers` | 论文列表，主题 / 关键词 / 状态筛选，批量操作 |
| **Paper Detail** | `/papers/:id` | 详情 + 粗读 / 精读 / 嵌入，中文翻译 |
| **Collect** | `/collect` | 论文收集 + 主题订阅管理 |
| **Wiki** | `/wiki` | Wiki 生成 + Canvas 侧面板 + 历史 |
| **Graph** | `/graph` | 引用图谱 + 时间线 + 演化分析 |
| **Brief** | `/brief` | 每日简报 + 历史查看 |
| **Dashboard** | `/dashboard` | 系统看板 + 成本统计 |
| **Pipelines** | `/pipelines` | 流水线运行记录 |
| **Operations** | `/operations` | 摄入 / 同步 / 任务触发 |
| **Settings** | `/settings` | LLM 多源配置管理 |

---

## 🔧 开发

```bash
# 后端 lint
python -m ruff check .

# 前端类型检查
cd frontend && npx tsc --noEmit

# 数据库迁移
alembic upgrade head
```

---

## 📄 License

[MIT](LICENSE)

---

<div align="center">

**Built with ❤️ by Bamzc**

*PaperMind — 让 AI 帮你读论文，让知识触手可及。*

</div>
