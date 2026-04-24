# PaperMind

**AI 驱动的学术论文研究工作流平台**

*从「搜索论文」进化为「理解领域」*

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React_18-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://typescriptlang.org)
[![Tailwind](https://img.shields.io/badge/Tailwind_CSS_v4-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white)](https://tailwindcss.com)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white)](https://sqlite.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![LLM](https://img.shields.io/badge/LLM-OpenAI_%7C_Anthropic_%7C_ZhipuAI-blueviolet?style=flat-square)]()

> 让 AI 成为你的研究助理 —— 自动追踪、智能分析、知识图谱、学术写作，一站式搞定！

---

## 🚀 快速开始

### Docker 部署（生产推荐）

```bash
# 1️⃣ 克隆项目
git clone https://github.com/Color2333/PaperMind.git && cd PaperMind

# 2️⃣ 配置环境变量
cp .env.example .env
vim .env  # 至少填写 LLM API Key

# 3️⃣ 一键部署
docker compose up -d --build

# 4️⃣ 访问服务
# 🌐 前端：http://localhost:3002
# 📡 后端 API: http://localhost:8002
# 📚 API 文档：http://localhost:8002/docs
```

### 本地开发

```bash
# 1️⃣ 克隆项目
git clone https://github.com/Color2333/PaperMind.git && cd PaperMind

# 2️⃣ 一键初始化（推荐）
python scripts/dev_setup.py

# 或手动初始化：
python -m venv .venv && source .venv/bin/activate
pip install -e ".[llm,pdf]"
cp .env.example .env
vim .env  # 填入 LLM API Key
python scripts/local_bootstrap.py

# 3️⃣ 启动后端
uvicorn apps.api.main:app --reload --port 8000

# 4️⃣ 启动前端
cd frontend && npm install && npm run dev
# 🌐 打开 http://localhost:5173
```

### 站点认证（可选）

```bash
# 在 .env 中设置密码即可启用全站认证
AUTH_PASSWORD=your_password_here
AUTH_SECRET_KEY=your_random_secret_key
```

---

## 🎯 这是什么？

PaperMind 是一个面向科研工作者的 AI 增强平台，帮你从「搜索论文」进化为「理解领域」。

| 😫 以前 | 😎 现在 |
|:--------|:--------|
| 每天手动刷 arXiv，怕错过重要论文 | 自动订阅主题，新论文推送到邮箱 |
| 读论文从摘要开始，不知道值不值得精读 | AI 粗读打分，快速筛选高价值论文 |
| 想了解领域发展，不知道从哪篇读起 | 知识图谱可视化，一眼看清引用脉络 |
| 写论文卡壳，不知道怎么表达 | 学术写作助手，润色/翻译/去 AI 味 |
| 文献综述耗时耗力，整理几百篇头大 | Wiki 自动生成，一键产出领域综述 |

---

## ✨ 核心能力

### 🧠 认知重构工作流 (PaperSenseMaking)

「阅读→理解→重构」的完整论文工作流：

- 📝 **Act 1 理解** —— 摘要 + 关键发现，厘清论文核心
- ⚡ **Act 2 碰撞** —— 冲突 + 疑问，与已有知识对话
- 🔄 **Act 3 重构** —— 前后对比 + 认知变化，形成新认知
- 📖 **全文对照翻译** —— 段落级中英对照，支持两种模式
  - ⚡ **快速翻译**：1-2 分钟，PyMuPDF 分段 + 并发翻译
  - 📐 **布局保留**：3-5 分钟，PDFMathTranslate 完整排版（公式/图表保留）

### 🤖 AI Agent 对话

你的智能研究助理，自然语言交互搞定一切：

- 💬 **SSE 流式对话** —— Claude 风格，实时响应
- 🔧 **工具链** —— 搜索/入库/分析/生成/写作自动调度
- ✅ **用户确认机制** —— 重要操作等你点头再执行
- 📜 **对话历史持久化** —— 切页面不丢上下文
- 🎯 **AI 关键词建议** —— 描述研究方向 → 自动生成搜索词

### 📄 智能论文管理

从收录到精读，全流程自动化：

- 🔄 **多源订阅** —— ArXiv 关键词 + CSFeeds 论文源双重抓取
- 🚫 **论文去重检测** —— 避免重复处理浪费 token
- 📦 **递归抓取** —— 自动延伸更早期论文
- ⚡ **并行处理** —— 粗读/精读/嵌入三管齐下
- 💾 **按需下载 PDF** —— 入库不下载，精读才拉取

### 🕸️ 引用图谱

可视化你的研究领域：

- 🌳 **引用树** —— 单篇论文引用网络
- 🌐 **主题图谱** —— 跨主题引用关系
- 🌉 **桥接论文** —— 发现跨领域的核心工作
- 🔬 **研究前沿** —— 高被引 + 高引用的热点
- 📊 **共引聚类** —— 相关研究自动分组

### 📚 Wiki 自动生成

一键生成领域综述：

- 📖 **主题 Wiki** —— 输入关键词，输出完整综述
- 📄 **论文 Wiki** —— 单篇论文深度解读
- 📊 **实时进度条** —— 异步生成，自动刷新
- 📜 **历史版本** —— 所有生成内容可追溯

### 🔍 论文订阅源（CSFeeds）

发现你研究领域最重要的论文来源：

- 🎯 **关键词订阅** —— arXiv 关键词自动追踪
- 📡 **论文源订阅** —— 直接订阅 CSFeeds 热门论文
- 📬 **邮件推送** —— 新论文自动发送到邮箱
- ⏰ **按主题独立调度** —— 每个主题独立抓取频率

### ✍️ 学术写作助手

来自顶尖研究机构的写作工具：

- 🌏 **中转英 / 英转中** —— 学术级翻译
- ✨ **润色（中/英）** —— 更地道的学术表达
- 🤖 **去 AI 味** —— 降低 AI 检测率
- 📊 **图表推荐 / 标题生成** —— 实验数据可视化建议

### 📖 沉浸式 PDF 阅读器

专注阅读，AI 随叫随到：

- 📜 **连续滚动** —— IntersectionObserver 页码追踪
- 🔍 **缩放/全屏/跳转** —— 键盘快捷键支持
- 🌐 **arXiv 在线代理** —— 无本地 PDF 也能读
- ✨ **选中即问** —— AI 解释/翻译/总结

### 🔐 站点安全认证

保护你的研究资产：

- 🔑 **站点密码** —— 简单可靠，适合个人/小团队
- 🎫 **JWT Token** —— 7 天有效期，自动续期
- 🛡️ **全站保护** —— 所有 API 都需要认证

### ⚙️ LLM 模型管理

灵活控制成本，按场景分配模型：

- 📊 **统一配置** —— 默认使用 GLM-4.7（文本）+ GLM-4.6V（视觉）
- 🔄 **一键切换** —— 在设置页面随时切换配置
- 🎯 **场景映射** —— 所有文本任务自动使用 GLM-4.7
- 💰 **成本优化** —— 单一模型配置，避免管理复杂度
- 📈 **Token 追踪** —— 所有 API 调用自动记录成本和用量

**默认模型配置**：
- 文本任务（粗读/精读/翻译/写作）：GLM-4.7
- 视觉任务（图表分析/OCR）：GLM-4.6V
- 降级备用：GLM-4.7

---

## 🏗️ 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                     Frontend (React 18)                      │
│  Agent │ Papers │ Wiki │ Graph │ Brief │ Collect │ Writing  │
│         路由懒加载 · Vite 代码分割 · SSE 跨页保活            │
└─────────────────────────┬───────────────────────────────────┘
                          │ REST + SSE (JWT Auth)
┌─────────────────────────┴───────────────────────────────────┐
│                      FastAPI Backend                         │
├─────────────┬─────────────┬─────────────┬───────────────────┤
│   Agent     │   Pipeline  │    RAG      │  Graph / Wiki /   │
│   Service   │   Engine    │   Service   │  Brief / Write    │
├─────────────┴─────────────┴─────────────┴───────────────────┤
│         Global TaskTracker (异步任务 + 实时进度)             │
│         右下角悬浮面板 · 分类图标 · 完成历史                │
├─────────────────────────────────────────────────────────────┤
│           Unified LLM Client (连接复用 + TTL 缓存)           │
│            OpenAI  │  Anthropic  │  ZhipuAI                 │
├─────────────────────────────────────────────────────────────┤
│   SQLite (WAL)  │  ArXiv API  │  Semantic Scholar API       │
└─────────────────────────────────────────────────────────────┘
                            │
              ┌────────────┴────────────┐
              │   APScheduler Worker    │
              │   按主题独立调度         │
              │   每日简报 / 每周图谱    │
              └─────────────────────────┘
```

---

## ⚙️ 环境变量

| 变量 | 说明 | 默认值 |
|:-----|:-----|:------:|
| `LLM_PROVIDER` | LLM 提供商 (openai/anthropic/zhipu) | `zhipu` |
| `ZHIPU_API_KEY` | 智谱 API Key | — |
| `OPENAI_API_KEY` | OpenAI API Key | — |
| `ANTHROPIC_API_KEY` | Anthropic API Key | — |
| `LLM_MODEL_SKIM` | 粗读模型 | `glm-4.7` |
| `LLM_MODEL_DEEP` | 精读模型 | `glm-4.7` |
| `LLM_MODEL_VISION` | 视觉模型 | `glm-4.6v` |
| `EMBEDDING_MODEL` | Embedding 模型 | `embedding-3` |
| `SITE_URL` | 生产域名 | `http://localhost:3002` |
| `AUTH_PASSWORD` | 站点密码（留空禁用认证） | — |
| `AUTH_SECRET_KEY` | JWT 密钥 | — |
| `COST_GUARD_ENABLED` | 成本守卫 | `true` |
| `DAILY_BUDGET_USD` | 每日预算 | `2.0` |
| `OPENALEX_EMAIL` | OpenAlex 邮箱（用于 API） | — |
| `IEEE_API_ENABLED` | 启用 IEEE 搜索 | `false` |
| `IEEE_API_KEY` | IEEE API Key | — |
| `SEMANTIC_SCHOLAR_API_KEY` | Semantic Scholar API Key | — |

> 完整配置见 `.env.example`

---

## 📡 API 速览

<details>
<summary><strong>🔐 认证</strong></summary>

| 方法 | 路径 | 说明 |
|:----:|:-----|:-----|
| POST | `/auth/login` | 登录获取 JWT Token |
| GET | `/auth/status` | 查询认证状态 |

</details>

<details>
<summary><strong>🤖 AI Agent</strong></summary>

| 方法 | 路径 | 说明 |
|:----:|:-----|:-----|
| POST | `/agent/chat` | Agent 对话（SSE 流式） |
| POST | `/agent/confirm/{id}` | 确认工具执行 |
| POST | `/agent/reject/{id}` | 拒绝工具执行 |

</details>

<details>
<summary><strong>📄 论文管理</strong></summary>

| 方法 | 路径 | 说明 |
|:----:|:-----|:-----|
| GET | `/papers/latest` | 论文列表（分页） |
| GET | `/papers/{id}` | 论文详情 |
| POST | `/pipelines/skim/{id}` | 粗读 |
| POST | `/pipelines/deep/{id}` | 精读 |
| POST | `/pipelines/embed/{id}` | 生成嵌入向量 |

</details>

<details>
<summary><strong>🕸️ 知识图谱</strong></summary>

| 方法 | 路径 | 说明 |
|:----:|:-----|:-----|
| GET | `/graph/citation-tree/{id}` | 引文树 |
| GET | `/graph/overview` | 全局概览 |
| GET | `/graph/bridges` | 桥接论文 |
| GET | `/graph/frontier` | 研究前沿 |
| GET | `/graph/cocitation` | 共引聚类 |

</details>

<details>
<summary><strong>📚 Wiki</strong></summary>

| 方法 | 路径 | 说明 |
|:----:|:-----|:-----|
| POST | `/wiki/topic` | 生成主题综述 |
| GET | `/wiki/topic/{id}` | 获取主题 Wiki |
| POST | `/wiki/paper/{id}` | 生成论文解读 |
| GET | `/wiki/history` | Wiki 生成历史 |

</details>

<details>
<summary><strong>📡 订阅源</strong></summary>

| 方法 | 路径 | 说明 |
|:----:|:-----|:-----|
| GET | `/cs-feeds/` | 列表订阅源 |
| POST | `/cs-feeds/subscribe` | 订阅论文源 |
| POST | `/cs-feeds/fetch` | 手动触发抓取 |

</details>

---

## ⚡ 性能优化

| 类别 | 优化策略 |
|------|----------|
| **首屏** | KaTeX 字体 CDN + PDF Worker CDN + 重型库懒加载（-2.7MB） |
| **前端** | 路由懒加载 · `useMemo`/`useCallback` · React.memo · RAF batching |
| **数据库** | SQLite WAL · 批量聚合查询 · Citation 索引 |
| **图谱** | list_lightweight 轻量加载 · 90% 内存削减 |
| **LLM** | 连接复用 · 30s TTL 缓存 · 指数退避重试 |
| **任务** | 统一进度回调 · 粒度化进度报告 · 分类图标 |

---

## 📋 更新日志

### v3.2 (2026-03-19) — 性能优化 + 全局任务系统重构

**性能优化**
- KaTeX 字体 + PDF Worker 改为 CDN，首屏 -2.7MB
- ForceGraph2D / react-pdf / react-markdown 懒加载
- topic_stats N+1 查询改为批量聚合（401次→4次）
- Citation 字段加索引，图谱查询加速
- graph_service 全量加载改为轻量模式，内存 -90%
- HTTP 客户端复用 + LLM 指数退避重试
- 50+ 处 index-as-key 修复

**任务系统重构**
- 统一进度回调签名（message, current, total）
- TaskManager 合并到 global_tracker
- fetch / cs_feed / weekly / figure_analysis 进度粒度增强
- GlobalTaskBar 改为右下角悬浮面板（分类图标/颜色/历史）
- ActiveTask 增加 category 字段

**其他**
- CSFeeds 论文订阅源功能完善
- Agent 对话体验优化
- 前端状态管理优化，减少无效重渲染

### v3.1 (2026-03-01) — 安全认证 + 稳定性增强

**新功能**
- 🔐 站点密码认证 —— JWT Token 保护所有 API
- 📄 PDF Token 认证 —— 文件访问也安全
- 🔄 SSE 认证 —— Agent 对话等 SSE 请求携带认证

**Bug 修复**
- 修复 TypeScript 编译失败
- 恢复 GZipMiddleware 响应压缩
- 恢复 logging_setup 统一日志格式

<details>
<summary>查看历史版本</summary>

### v3.0 (2026-02-28) — 稳定性全面升级
### v2.8 — 后端重构 + Agent 智能化
### v2.7 — 多源引用 + 相似度地图
### v2.5 — 知识图谱可视化
### v2.0 — Agent 对话系统
### v1.0 — 基础论文管理

</details>

---

## 🔧 开发

```bash
# 后端 lint
python -m ruff check .

# 前端类型检查
cd frontend && npx tsc --noEmit

# 数据库迁移
cd infra && alembic revision --autogenerate -m "描述"
alembic upgrade head
```

---

## 🙏 致谢

- **[awesome-ai-research-writing](https://github.com/Leey21/awesome-ai-research-writing)** — 写作助手 Prompt 模板来源
- **[ArXiv](https://arxiv.org)** — 开放论文平台
- **[Semantic Scholar](https://www.semanticscholar.org)** — 引用数据来源
- **[CSFeeds](https://csarxiv.org)** — 论文源订阅服务
- **[learn-claude-code](https://github.com/shareAI-lab/learn-claude-code)** — Agent Harness 工程体系启发，s01-s12 渐进式解构：Loop → Tools → Planning → Subagents → Skills → Context → Tasks → Background → Teams → Protocols → Autonomous
- **[PaperSenseMaking](https://github.com/edu-ai-builders/paper-sense-making)** — 论文阅读「阅读→理解→重构」工作流设计灵感

---

<div align="center">

**Built with ❤️ by [Color2333](https://github.com/Color2333)**

*PaperMind — 让 AI 帮你读论文，让知识触手可及。*

[![Star](https://img.shields.io/github/stars/Color2333/PaperMind?style=social)](https://github.com/Color2333/PaperMind/stargazers)

</div>
