

以下我为你起草的 **Product Requirements Document (PRD)**，项目代号暂定为 **PaperMind**。

---

# Product Requirements Document: PaperMind

**版本:** 1.0
**日期:** 2026-02-16
**状态:** 规划中
**核心愿景:** 从“搜索论文”进化为“理解领域”。通过自动化 Agent 和 LLM，将海量文献转化为结构化的知识图谱，辅助研究者完成从“每日追踪”到“深度调研”的全过程。

---

## 1. 用户画像 (User Personas)

* **P1: 领域探索者 (The Newcomer):** 对某个细分领域（如“深度学习中的对比学习”）不熟悉，需要快速理清发展脉络、经典必读论文和最新动态。
* **P2: 资深研究员 (The Tracker):** 清楚自己关注什么，需要每日自动化筛选最新 ArXiv 论文，过滤噪音，只看高质量的 Deep Read 报告。
* **P3: 细节挖掘者 (The Engineer):** 需要在阅读论文 PDF 时，快速查找公式含义、代码实现细节，并寻找与当前论文相似的其他技术方案。

---

## 2. 核心功能模块 (Functional Requirements)

### 模块 A: 数据获取与自动化 (The Harvester)

部署在 Linux 服务器上的后台服务，负责“吞吐”信息。

* **A1. 多源抓取 (Multi-Source Crawling):**
* 支持 **ArXiv** (API) 作为即时来源。
* 支持 **Semantic Scholar / Google Scholar** (通过 API 或 SerpApi) 获取引用数据、影响因子和历年经典论文。
* 支持 **Github** 抓取关联代码库。


* **A2. 智能调度 (Scheduler):**
* 支持 Crontab 风格的定时任务（如每日凌晨 2:00 执行）。
* 增量更新机制：自动记录上次抓取时间点，避免重复。


* **A3. 原始存储 (Raw Storage):**
* 自动下载 PDF 文件至本地对象存储（MinIO 或本地文件系统）。
* 元数据存入关系型数据库 (PostgreSQL)。



### 模块 B: AI 阅读引擎 (The Reader Agent)

系统的核心大脑，分为两级阅读模式。

* **B1. 粗读模式 (Triage/Skim):**
* **输入:** 论文标题、摘要。
* **处理:** 使用轻量级 LLM (如 GPT-4o-mini / Claude 3 Haiku)。
* **输出:** 结构化摘要（一句话总结、核心创新点、相关度打分）。
* **决策:** 如果相关度 > 阈值，触发“精读模式”并下载 PDF。


* **B2. 精读模式 (Deep Dive):**
* **输入:** 论文 PDF 全文。
* **处理:**
* **PDF 解析:** 使用多模态大模型 (Vision-Language Model) 直接“看”PDF，或使用 Nougat/PyMuPDF 提取文本、公式和图表。
* **深度分析:** 提取 Method、Experiments (SOTA 对比数据)、Ablation Study 结论。
* **批判性思考:** 让 Agent 扮演审稿人，指出论文的潜在弱点或假设限制。





### 模块 C: 知识图谱与脉络 (The Historian)

解决“系统性了解一个领域”的需求。

* **C1. 引用树构建 (Citation Tree):**
* 给定一篇论文，自动向上追溯其“祖先”（它基于什么理论），向下寻找其“后代”（谁改进了它）。


* **C2. 领域脉络生成 (Timeline Generation):**
* **输入:** 关键词（如 "Transformer Architecture"）。
* **输出:** 一条时间轴，标记出 Seminal Papers（开山之作），并生成一份综述（Survey），解释技术演进路线（例如：RNN -> LSTM -> Attention -> Transformer）。


* **C3. 知识库 Wiki 化:**
* 自动将上述信息组织成类似于 Notion 的页面，每篇论文是一个节点，节点间有链接。



### 模块 D: 向量记忆与问答 (The Memory & RAG)

解决“以文搜文”和“全库问答”需求。

* **D1. 向量化 (Embedding):**
* 论文入库时，自动对“摘要”和“结论”进行 Embedding 处理。
* 支持存入向量数据库 (ChromaDB / pgvector)。


* **D2. 关联推荐:**
* 当阅读 Paper A 时，侧边栏自动推荐“语义相似”的 Top 5 论文，即使它们没有直接引用关系。


* **D3. 跨文档问答 (Chat with Library):**
* 用户提问：“这个领域中解决过拟合常用的方法有哪些？”
* 系统检索库中所有相关片段，综合回答。



### 模块 E: 用户界面 (Client Interfaces)

* **E1. Web 端 (Demo/Dashboard):**
* 技术栈: Streamlit (快速原型) 或 Next.js (正式版)。
* 功能: 每日日报展示、领域脉络图谱可视化（使用 ECharts/D3.js）、全文搜索。


* **E2. macOS 客户端 (Native Reader):**
* 技术栈: SwiftUI (原生性能) 或 Tauri。
* **沉浸式阅读器:**
* 左侧: PDF 原文渲染。
* 右侧: AI 助手 Copilot。支持**划词解释**（选中一段话，AI 解释公式或术语）、**笔记同步**。




* **E3. 每日简报 (Notification):**
* 支持 HTML 邮件推送。
* 支持 IM 推送（Telegram/飞书）。



---

## 3. 技术架构设计 (System Architecture)

### 3.1 总体架构图

[Client Layer: Web / macOS / Mobile]
⬇️ (REST API / WebSocket)
[API Gateway: FastAPI]
⬇️
[Core Services]
├── Orchestrator (LangChain/LangGraph): 管理 Agent 流程
├── Crawler Service: 负责 ArXiv/Scholar API 调用
├── Analysis Service: 调用 LLM 进行总结
└── Vector Service: 负责 RAG 检索
⬇️
[Infrastructure]
├── LLM Provider: OpenAI / Anthropic / Local LLM (Ollama)
├── Database: PostgreSQL (元数据 + 关系)
├── Vector DB: pgvector 或 ChromaDB
├── Graph DB (可选): NetworkX (内存级) 或 Neo4j
└── File Store: Local PDF storage

### 3.2 关键数据结构 (Schema 示意)

**Table: Papers**

* `id`: UUID
* `title`: Varchar
* `arxiv_id`: Varchar
* `pdf_path`: Varchar
* `publication_date`: Date
* `embedding`: Vector(1536)
* `read_status`: Enum (Unread, Skimmed, DeepRead)
* `metadata`: JSONB (作者, 会议, 引用数)

**Table: Analysis_Reports**

* `paper_id`: FK
* `summary_md`: Text (粗读总结)
* `deep_dive_md`: Text (精读报告)
* `key_insights`: JSONB (关键点列表)

**Table: Citations (Adjacency List)**

* `source_paper_id`: FK
* `target_paper_id`: FK
* `context`: Text (引用的上下文，即引用那句话说了什么)

---

## 4. 实施路线图 (Roadmap)

### Phase 1: 基础设施与每日追踪 (The Foundation)

* **目标:** Linux 服务器跑起来，每天能收到新论文推送。
* **任务:**
1. 搭建 PostgreSQL + pgvector 环境。
2. 开发 ArXiv 爬虫与 PDF 下载器。
3. 实现 LLM "粗读" Agent。
4. 输出 HTML 日报。



### Phase 2: 深度阅读与 RAG (The Brain)

* **目标:** 能读懂 PDF，能问答。
* **任务:**
1. 集成 PDF 解析工具 (Nougat/PyMuPDF)。
2. 实现 "精读" Agent (Method/Exp 提取)。
3. 搭建 Web 界面 (Streamlit)，实现 RAG 问答。



### Phase 3: 知识图谱与脉络 (The Context)

* **目标:** 能够生成 "从起源到现状" 的树状图。
* **任务:**
1. 对接 Semantic Scholar API 获取引用数据。
2. 开发图算法，计算 Seminal Papers。
3. Web 端增加可视化图表组件。



### Phase 4: macOS 客户端 (The Experience)

* **目标:** 优雅的本地阅读体验。
* **任务:**
1. 使用 Swift/Tauri 开发桌面端。
2. 实现 PDF 阅读器与 API 的交互。



---

## 5. 待确认问题 (Open Questions)

1. **LLM 成本控制:** 精读 PDF 会消耗大量 Token。是否需要引入本地小模型（如 DeepSeek/Llama-3）来处理非关键步骤（如格式化）？
2. **PDF 解析精度:** 对于复杂的双栏排版和公式，单纯的提取文本效果可能不好。是否优先采用 Vision 方案（截屏喂给 GPT-4V）？

---

这是否符合你心中的构想？如果没有问题，我们可以直接进入 **Phase 1** 的技术选型和数据库设计阶段。