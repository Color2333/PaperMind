# PaperMind

AI 驱动的学术论文研究工作流平台，覆盖从论文抓取、粗读精读、向量嵌入、RAG 问答到知识图谱和 Wiki 生成的完整闭环。

## 核心能力

| 模块 | 功能 |
|------|------|
| **论文管理** | ArXiv 增量抓取、主题订阅、阅读状态流转（未读→粗读→精读） |
| **AI 流水线** | Skim（粗读摘要）、Deep-dive（精读分析）、Embed（向量嵌入）、批量操作 |
| **RAG 问答** | 基于论文向量的检索增强问答，支持多轮对话 |
| **引用图谱** | 引用同步、引文树、时间线、领域演化、里程碑论文识别 |
| **Wiki 生成** | 主题 Wiki / 论文 Wiki 自动生成，结果持久化存储，支持历史查看 |
| **每日简报** | 自动汇总最新论文生成 HTML 简报，支持邮件推送，历史简报持久化 |
| **成本管控** | Prompt 追踪、Token 用量统计、每日/单次预算守卫、自动降级 |
| **LLM 多源** | 支持 OpenAI / Anthropic / ZhipuAI（智谱），可动态配置切换 |

## 技术栈

**后端：** Python 3.11+ · FastAPI · SQLAlchemy · SQLite · APScheduler · Pydantic  
**前端：** React 18 · TypeScript · Vite · Tailwind CSS v4 · Lucide React · React Router v6  
**AI：** OpenAI SDK（兼容 ZhipuAI）· RAG · 自定义 Prompt 模板  
**工具链：** Ruff（Lint）· Alembic（Migration）

## 快速开始

### 1. 后端

```bash
# 克隆并进入项目
git clone <repo-url> && cd PaperMind

# 创建 Python 3.11+ 虚拟环境
python -m venv .venv && source .venv/bin/activate

# 安装依赖
pip install -e .
pip install -e ".[llm]"    # LLM 支持（openai 等）
pip install -e ".[pdf]"    # PDF 解析

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key 等

# 初始化数据库
python scripts/local_bootstrap.py

# 启动 API
uvicorn apps.api.main:app --reload
```

### 2. 前端

```bash
cd frontend
npm install
npm run dev
# 浏览器打开 http://localhost:5173
```

### 3. 后台任务调度器（可选）

```bash
python -m apps.worker.main
```

## 环境变量

参见 `.env.example`，关键配置：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_PROVIDER` | LLM 提供商 | `zhipu` |
| `ZHIPU_API_KEY` | 智谱 API Key | — |
| `LLM_MODEL_SKIM` | 粗读模型 | `glm-4.7` |
| `LLM_MODEL_DEEP` | 精读模型 | `glm-4.7` |
| `LLM_MODEL_VISION` | 视觉模型 | `glm-4.6v` |
| `EMBEDDING_MODEL` | 嵌入模型 | `embedding-3` |
| `COST_GUARD_ENABLED` | 成本守卫开关 | `true` |
| `DAILY_BUDGET_USD` | 每日预算 | `2.0` |

也可通过前端 **设置页面** 动态管理多个 LLM 配置，在线切换激活。

## API 概览

### 系统
- `GET /health` — 健康检查
- `GET /system/status` — 系统状态总览

### 论文
- `GET /papers/latest?limit=20&status=unread&topic_id=xxx` — 论文列表（支持状态/主题筛选）
- `GET /papers/{id}` — 论文详情
- `GET /papers/{id}/similar` — 相似论文

### 主题
- `GET /topics` · `POST /topics` · `PATCH /topics/{id}` · `DELETE /topics/{id}`

### AI 流水线
- `POST /pipelines/skim/{paper_id}` — 粗读
- `POST /pipelines/deep/{paper_id}` — 精读
- `POST /pipelines/embed/{paper_id}` — 向量嵌入
- `GET /pipelines/runs` — 运行记录

### RAG 问答
- `POST /rag/ask` — 检索增强问答

### 引用图谱
- `POST /citations/sync/{paper_id}` — 单篇引用同步
- `POST /citations/sync/topic/{topic_id}` — 主题批量同步
- `POST /citations/sync/incremental` — 增量同步
- `GET /graph/citation-tree/{paper_id}` — 引文树
- `GET /graph/timeline?keyword=xxx` — 时间线
- `GET /graph/quality?keyword=xxx` — 图谱质量
- `GET /graph/evolution/weekly?keyword=xxx` — 领域演化
- `GET /graph/survey?keyword=xxx` — 综述生成

### Wiki
- `GET /wiki/paper/{paper_id}` — 论文 Wiki（自动持久化）
- `GET /wiki/topic?keyword=xxx` — 主题 Wiki（自动持久化）

### 生成内容历史
- `GET /generated/list?type=topic_wiki|paper_wiki|daily_brief` — 历史列表
- `GET /generated/{content_id}` — 内容详情
- `DELETE /generated/{content_id}` — 删除记录

### 简报
- `POST /brief/daily` — 生成每日简报（自动持久化）

### 任务调度
- `POST /jobs/daily/run-once` — 手动触发抓取 + 简报
- `POST /jobs/graph/weekly-run-once` — 手动触发周图谱维护

### 成本指标
- `GET /metrics/costs?days=7` — 成本统计

### LLM 配置
- `GET /settings/llm-providers` — 配置列表
- `POST /settings/llm-providers` — 新增配置
- `PATCH /settings/llm-providers/{id}` — 编辑配置
- `DELETE /settings/llm-providers/{id}` — 删除配置
- `POST /settings/llm-providers/{id}/activate` — 激活
- `POST /settings/llm-providers/deactivate` — 全部停用

## 前端页面

| 页面 | 路由 | 功能 |
|------|------|------|
| Dashboard | `/` | 系统状态、论文统计、最近运行、成本可视化 |
| Topics | `/topics` | 主题订阅管理 |
| Papers | `/papers` | 论文列表（状态筛选、主题筛选、批量粗读/嵌入） |
| Paper Detail | `/papers/:id` | 论文详情、粗读/精读/嵌入操作 |
| Pipelines | `/pipelines` | 流水线运行记录 |
| Graph Explorer | `/graph` | 引用图谱可视化探索 |
| Wiki | `/wiki` | 主题/论文 Wiki 生成 + 历史记录查看 |
| Chat | `/chat` | RAG 多轮对话 |
| Daily Brief | `/brief` | 每日简报生成 + 历史简报查看 |
| Operations | `/operations` | 摄入/同步/任务手动触发 |
| Settings | `/settings` | LLM 配置管理（多源切换） |

## 项目结构

```
PaperMind/
├── apps/
│   ├── api/          # FastAPI 入口和路由
│   └── worker/       # APScheduler 后台任务
├── packages/
│   ├── ai/           # AI 流水线、RAG、Wiki、简报、成本守卫
│   ├── domain/       # 领域枚举和 Pydantic Schema
│   ├── integrations/ # ArXiv / Semantic Scholar / LLM / 通知
│   ├── storage/      # SQLAlchemy 模型和 Repository
│   └── config.py     # 应用配置
├── frontend/
│   └── src/
│       ├── components/  # UI 组件库（Card, Button, Modal...）
│       ├── pages/       # 页面组件
│       ├── services/    # API 服务层
│       └── types/       # TypeScript 类型定义
├── infra/            # Alembic 迁移
├── scripts/          # 初始化脚本
├── .env.example      # 环境变量模板
├── pyproject.toml    # Python 依赖
└── TECH_DETAILS.md   # 技术实现细节
```

## License

MIT
