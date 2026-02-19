# PaperMind - AI 研究工作流平台

**版本:** 2.7  
**日期:** 2026-02-19  
**作者:** color2333  
**核心愿景:** 从"搜索论文"进化为"理解领域"。通过自动化 Agent 和 LLM，将海量文献转化为结构化的知识图谱，辅助研究者完成从"每日追踪"到"深度调研"的全过程。

---

## 1. 用户画像

| 角色 | 描述 | 核心需求 |
|------|------|---------|
| **领域探索者** | 对某个细分领域不熟悉 | 快速理清发展脉络、经典必读论文和最新动态 |
| **资深研究员** | 清楚自己关注什么 | 每日自动化筛选最新论文，过滤噪音，看精读报告 |
| **细节挖掘者** | 需要查找公式、代码细节 | 阅读 PDF 时快速查找、寻找相似技术方案 |

---

## 2. 功能模块与实现状态

### 模块 A: 数据获取与自动化 ✅ 已实现

| 功能 | 状态 | 说明 |
|------|------|------|
| ArXiv API 抓取 | ✅ | 支持关键词搜索、批量入库、**三种排序（最新/相关性/最近更新）**、429重试 |
| **OpenAlex + Semantic Scholar 双源** | ✅ | OpenAlex 为主力（10 req/s），SS 为兜底，自动 fallback |
| **参考文献一键入库** | ✅ | 从引用详情批量导入：arXiv 全量通道 + SS 元数据通道，自动去重、建引用边、下载 PDF |
| 智能调度 | ✅ | **按主题独立调度**，每小时检查，支持日/两次/工作日/周频率 |
| **手动抓取（后台执行）** | ✅ | 立即返回 + 轮询状态，不再超时阻塞 |
| PDF 按需下载 | ✅ | 论文详情页一键下载 PDF，无 PDF 时精读/图表自动禁用 |
| 一键嵌入粗读 | ✅ | 运维面板一键处理所有未读论文（embed + skim 并行） |
| 主题订阅 | ✅ | 支持自定义频率、执行时间（北京时间）、AI 关键词建议 |
| 并行处理 | ✅ | 论文间并发（3篇同时）+ 单篇内 embed∥skim 并行 |
| 论文筛选流程 | ✅ | Agent 搜索后展示候选列表，用户筛选后才入库 |
| 入库行动记录 | ✅ | 6种行动类型（手动/自动/Agent/订阅/初始/参考文献导入），完整追溯 |

### 模块 B: AI 阅读引擎 ✅ 已实现

| 功能 | 状态 | 说明 |
|------|------|------|
| 粗读 (Skim) | ✅ | 标题+摘要 → 一句话总结、创新点、相关度评分、关键词提取、中文翻译 |
| 精读 (Deep Dive) | ✅ | PDF 全文 + Vision 模型 → 方法论、实验、消融、审稿风险 |
| 向量嵌入 | ✅ | 摘要+结论 Embedding，支持语义检索 |
| 成本控制 | ✅ | CostGuard 按预算自动降级模型 |
| LLM 多 Provider | ✅ | OpenAI / Anthropic / 智谱，数据库动态配置，30s TTL 缓存 |

### 模块 C: 知识图谱与脉络 ✅ 已实现

| 功能 | 状态 | 说明 |
|------|------|------|
| **丰富引用详情** | ✅ | Semantic Scholar 丰富字段（作者/年份/会议/引用数/摘要），在库匹配+自动建边 |
| **引用网络可视化** | ✅ | 力导向图（react-force-graph-2d），单篇/主题模式，节点大小按引用缩放 |
| **全局概览面板** | ✅ | 库概览 + 桥接论文 + 研究前沿 + 共引聚类，四维度分析 |
| **领域洞察面板** | ✅ | 时间线/演化/质量/研究空白 一键并行查询，折叠展示 |
| 主题级引用网络 | ✅ | 主题内论文互引分析，Hub 识别，深度溯源 |
| 领域时间线 | ✅ | 按关键词 + PageRank + seminal_score |
| 演化分析 | ✅ | 按年聚合 + LLM 趋势总结 |
| Topic Wiki | ✅ | 大纲 → 逐章节生成 → 概述汇总，Canvas 侧面板展示 |
| Paper Wiki | ✅ | 单篇论文百科生成 |

### 模块 D: 向量记忆与问答 ✅ 已实现

| 功能 | 状态 | 说明 |
|------|------|------|
| 向量化存储 | ✅ | SQLite 内嵌 embedding，Paper 表直接存储 |
| 语义相似推荐 | ✅ | 基于 embedding 余弦距离 Top-K，候选池限制 500 |
| 跨文档 RAG 问答 | ✅ | 全文检索 + 向量检索 → LLM 综合回答 |
| **多轮迭代 RAG** | ✅ | 自动评估答案质量，不满意则补充检索（最多 3 轮），Agent 显示迭代进度 |
| **论文相似度地图** | ✅ | UMAP 降维 2D 散点图，按主题着色、按阅读状态调大小，点击跳转 |
| RAG 报告持久化 | ✅ | 生成 Artifact 卡片并存入 GeneratedContent |

### 模块 E: AI Agent 对话系统 ✅ 已实现

| 功能 | 状态 | 说明 |
|------|------|------|
| SSE 流式对话 | ✅ | 实时文本流 + 工具调用进度 |
| 工具调用链 | ✅ | 搜索/入库/粗读/嵌入/RAG/Wiki/简报/订阅管理/AI关键词建议 |
| 用户确认机制 | ✅ | 写操作需用户确认后执行 |
| 实时进度条 | ✅ | 工具执行过程流式进度反馈 |
| 会话持久化 | ✅ | localStorage 存储，跨页面状态保持 |
| 自动生成标题 | ✅ | 首次对话自动生成会话标题 |
| 能力标签 | ✅ | 输入框前置能力选择 |
| AI 关键词建议 | ✅ | 自然语言描述 → LLM 生成 arXiv 搜索关键词 |
| **用户画像注入** | ✅ | system prompt 自动注入关注领域、精读历史、库状态，实现个性化对话 |

### 模块 F: 个性化推荐与趋势 ✅ 已实现

| 功能 | 状态 | 说明 |
|------|------|------|
| 用户兴趣画像 | ✅ | 基于已读论文 embedding 聚类中心 |
| 个性化推荐 | ✅ | 未读论文按余弦相似度排序推荐 |
| 热点关键词 | ✅ | 近期论文关键词频率分析 |
| 趋势检测 | ✅ | 两周期对比检测新兴方向 |
| 今日研究速览 | ✅ | Agent 着陆页展示推荐、热点、统计 |

### 模块 G: 前端界面 ✅ 已实现

| 页面 | 功能 |
|------|------|
| Agent（主页） | AI 对话，Manus 风格工具调用 UI，今日研究速览 |
| Papers | **分页 + 文件夹分类导航**：按主题/收藏/最近7天/收录日期/未分类分组，双栏布局 |
| Paper Detail | 详情 + **一键深度分析** + 粗读/精读/嵌入/相似论文 + **图表原图** + **PDF 按需下载** + 中文翻译 |
| Wiki | 主题/论文 Wiki 生成，Canvas 侧面板 |
| Daily Brief | 每日简报生成与历史 |
| Collect | 论文收集 + 主题订阅管理 + **手动抓取（后台轮询）** + **未读徽章** |
| Writing | 14 种写作模板 + **6 种支持多模态图片输入**（图标题/表标题/实验分析/审稿/OCR 提取） |
| Graph Explorer | **三面板架构**（全局概览/引文分析/领域洞察），引用图谱力导向图，**参考文献一键入库** |
| Dashboard | 系统看板 + **全覆盖 LLM 成本追踪**（含阶段中文标签） |
| Settings | LLM 配置统一管理 |

### 模块 I: 沉浸式 PDF 阅读器 ✅ 已实现

| 功能 | 状态 | 说明 |
|------|------|------|
| 连续滚动阅读 | ✅ | react-pdf v10 全页渲染，IntersectionObserver 检测当前页码 |
| 缩放/全屏 | ✅ | 50%~300% 缩放，浏览器全屏，键盘快捷键 (Ctrl+/-/0) |
| 页码跳转 | ✅ | 工具栏输入页码跳转，底部进度条实时显示 |
| AI 解释 | ✅ | 选中文本 → AI 解释术语、公式含义 |
| AI 翻译 | ✅ | 选中文本 → 中文翻译（保留术语原文） |
| AI 总结 | ✅ | 选中文本 → 提炼核心观点 |
| AI 侧边栏 | ✅ | 右侧可收起面板，结果历史，Markdown + LaTeX 渲染，复制 |
| 深色主题 | ✅ | 专属深色背景 UI，PDF 页面阴影，工具栏半透明毛玻璃 |

### 模块 H: 多模态深度理解 ✅ 已实现（Phase 5 完整）

| 功能 | 状态 | 说明 |
|------|------|------|
| PDF 图表提取 | ✅ | PyMuPDF 自动提取 Figure/Table 区域，过滤小图标 |
| Vision 模型解读 | ✅ | 图片 base64 + 专业 prompt → GLM-4.6V 生成中文解读 |
| 图表类型推断 | ✅ | 自动识别 figure/table/algorithm/equation |
| Caption 提取 | ✅ | 正则匹配 Figure/Table/Algorithm 标题 |
| 整页渲染回退 | ✅ | 内嵌图片提取不足时，对含图表页面做 2x 高分辨率渲染 |
| 解读结果持久化 | ✅ | ImageAnalysis 数据模型，按论文存储 |
| Agent 工具集成 | ✅ | `analyze_figures` 工具，需用户确认后执行 |
| 前端展示 | ✅ | PaperDetail 图表解读标签页，折叠卡片 + Markdown 渲染 |
| 推理链深度分析 | ✅ | 5步推理（问题→方法→理论→实验→影响），创新性/严谨性/影响力评分 |
| 推理链前端 | ✅ | 折叠面板展示推理过程、方法链、实验链、评分仪表盘、优劣势对比 |
| 研究空白识别 | ✅ | 引用网络稀疏区域分析 + LLM 推理，3-5 个空白 + 方法矩阵 + 趋势 |
| 研究空白前端 | ✅ | GraphExplorer 新标签页，空白卡片、方法对比表、趋势三栏布局 |

### 技术栈

| 层 | 技术 |
|----|------|
| 前端 | React 18 + Vite + TypeScript + Tailwind CSS v4 |
| 后端 | FastAPI + SQLAlchemy + SQLite (WAL) |
| LLM | OpenAI / Anthropic / 智谱 (GLM-4.6V + GLM-4.7) |
| 调度 | APScheduler（按主题独立调度） |
| 外部 API | ArXiv API, Semantic Scholar API |

### 性能优化（v2.5）

| 领域 | 优化项 |
|------|--------|
| 前端 | 路由懒加载（React.lazy + Suspense），首屏只加载 Agent 页 |
| 前端 | Vite manualChunks 分割 react-vendor / markdown / icons |
| 前端 | AgentSessionContext value useMemo 防止不必要的全局重渲染 |
| 前端 | Papers 列表 **后端分页**（page + page_size），前端不再全量加载 |
| 前端 | Sidebar groupByDate useMemo |
| 后端 | LLM 配置 30s TTL 缓存，避免每次调用查库 |
| 后端 | OpenAI 客户端连接复用（按 key+url 缓存），设置 120s timeout |
| 后端 | SQLite PRAGMA synchronous=NORMAL + cache_size=64MB + temp_store=MEMORY |
| 后端 | 关键列索引：papers.created_at, prompt_traces.created_at, pipeline_runs.created_at, papers.read_status |
| 后端 | 向量检索候选池限制 500 条，避免全表加载 |
| 后端 | **LLM 成本追踪全覆盖**：`trace_result` 集中式追踪，覆盖 completion/embedding/vision 全链路 |

---

## 3. 下阶段优化蓝图

### Phase 5: 多模态深度理解（第一梯队）

#### 5.1 图表/公式智能识别 ✅ 已完成

- **目标**：从 PDF 中自动提取 Figure/Table/公式，逐个送 Vision 模型解读
- **产出**：图表说明卡片、类型推断、Caption 提取、中文解读
- **实现文件**：
  - `packages/ai/figure_service.py` — 图表提取与 Vision 解读核心服务
  - `packages/storage/models.py` — `ImageAnalysis` 数据模型
  - `packages/integrations/llm_client.py` — `vision_analyze()` 多模态调用
  - `apps/api/main.py` — `GET/POST /papers/{id}/figures` 接口
  - `packages/ai/agent_tools.py` — `analyze_figures` Agent 工具
  - `frontend/src/pages/PaperDetail.tsx` — 图表解读标签页 + FigureCard 组件

#### 5.2 推理链深度分析 (Reasoning Chain) ✅ 已完成

- **目标**：引入类 o1/DeepSeek-R1 的分步推理，提升论文分析深度
- **产出**：方法论推导链、实验结果验证链、创新性多维评估、优劣势分析、未来建议
- **实现文件**：
  - `packages/ai/prompts.py` — `build_reasoning_prompt()` 多步推理 prompt
  - `packages/ai/reasoning_service.py` — 推理链核心服务（上下文收集、PDF 文本、LLM 调用、结果持久化）
  - `apps/api/main.py` — `POST /papers/{id}/reasoning` 接口
  - `packages/ai/agent_tools.py` — `reasoning_analysis` Agent 工具
  - `frontend/src/pages/PaperDetail.tsx` — 推理链折叠面板（评分概览、推理步骤、方法链、实验链、优劣势、建议）

#### 5.3 研究空白识别 (Research Gap Detection) ✅ 已完成

- **目标**：分析引用网络的稀疏区域，发现未被充分探索的研究方向
- **产出**：跨论文方法对比矩阵、引用稀疏方向检测、趋势分析、研究建议报告
- **实现文件**：
  - `packages/ai/prompts.py` — `build_research_gaps_prompt()` 研究空白识别 prompt
  - `packages/ai/graph_service.py` — `detect_research_gaps()` 引用网络稀疏区域分析
  - `apps/api/main.py` — `GET /graph/research-gaps` 接口
  - `packages/ai/agent_tools.py` — `identify_research_gaps` Agent 工具
  - `frontend/src/pages/GraphExplorer.tsx` — 研究空白标签页（空白卡片、方法矩阵、趋势三栏、网络统计）

---

### Phase 6: 知识增强检索（第二梯队）

#### 6.1 GraphRAG（图谱增强检索）— 渐进式改进

- **目标**：在现有 RAG 基础上渐进融入图谱结构信息，提升宏观问题回答质量
- **策略**：不另起炉灶，在 `rag_service.py` 上迭代演进，新旧检索能力并存
- **产出**：论文社区检测与社区摘要、分层检索（社区→论文→片段）
- **实现路径**：
  - 在现有 `rag_service.py` 中增加图谱上下文注入
  - 用 `networkx` Louvain 算法做社区检测，结果缓存
  - 查询时先匹配社区摘要，再在社区内精搜，与现有向量检索结果合并
  - 渐进式切换：A/B 模式，用户可选择是否启用图谱增强

#### 6.2 多智能体协作系统 — 效果优先

- **目标**：在效果可验证的前提下，将单 Agent 拆分为多个专业 Agent
- **原则**：不为拆而拆，先验证多 Agent 在特定场景（如综述生成）中的效果提升，再逐步扩展
- **角色设计**：

  | Agent | 职责 | 工具权限 |
  |-------|------|---------|
  | 搜索员 | 查找和筛选论文 | search, arXiv ingest |
  | 分析师 | 深度阅读和评审 | skim, deep_read, RAG |
  | 写作者 | 生成 Wiki、简报、综述 | generate_wiki, brief |
  | 审稿人 | 质量把关与反馈 | 只读 + 反馈 |

- **实现路径**：
  - 先在综述生成场景试点：写作者 + 审稿人 双 Agent 迭代
  - 验证效果后再扩展到完整的 Orchestrator 模式
  - 保留单 Agent 作为默认模式，多 Agent 作为高级选项

#### 6.3 自动化学术综述生成

- **目标**：生成接近发表质量的学术综述文档
- **产出**：多轮迭代写作（大纲→初稿→审核→修改→终稿）、自动引用标注、LaTeX/Word 导出
- **实现路径**：
  - 新建 `packages/ai/survey_writer.py`
  - 多轮 LLM 调用 + 自我审核循环
  - 自动插入 `[Author, Year]` 格式引用
  - 用 `python-docx` 或 `pylatex` 导出

#### 6.4 论文代码关联与复现辅助

- **目标**：自动关联论文的开源实现，辅助实验复现
- **产出**：GitHub 仓库关联、伪代码提取、复现步骤指南
- **实现路径**：
  - 集成 Papers with Code API
  - `agent_tools.py` 新增 `find_code_repo` 工具
  - 精读流程增加代码块检测步骤

---

### Phase 7: 体验打磨与智能推送（第三梯队）

#### 7.1 智能论文监控与推送

- **目标**：基于语义（非关键词）的智能论文发现与推送
- **产出**：
  - 语义订阅：跟已读论文向量相似的新论文自动推送
  - 突破性论文检测：引用量急增、被多社区引用的论文自动标记
  - 多渠道推送：邮件 + 飞书/Telegram
- **实现路径**：
  - 推荐引擎 + 每日 arXiv 扫描
  - 异常检测算法标记热门论文
  - 集成飞书/Telegram Webhook

#### 7.2 Agent 交互体验深度优化

- **目标**：打磨单人使用体验至极致
- **产出**：
  - 对话记忆增强：跨会话记住用户的研究偏好和历史结论
  - 主动提醒：基于订阅主题有新进展时主动推送
  - 快捷操作：支持更多自然语言快捷指令
- **实现路径**：
  - 用户画像持久化存储
  - 定时任务检测新论文与用户画像匹配度
  - Agent system prompt 动态注入用户偏好上下文

---

## 4. 实施路线图总览

```
已完成 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 1: 基础设施与每日追踪         ✅ ArXiv 抓取、粗读、HTML 日报
Phase 2: 深度阅读与 RAG            ✅ PDF 精读、向量化、RAG 问答
Phase 3: 知识图谱与脉络            ✅ 引用树、时间线、Wiki 生成
Phase 4: AI Agent + 前端重构       ✅ SSE 流式对话、工具链、Claude 风格 UI
Phase 4.5: 个性化推荐 + 调度增强   ✅ 推荐引擎、热点趋势、按主题独立调度、AI 关键词
Phase 4.6: 性能优化                ✅ 路由懒加载、LLM 客户端复用、SQLite 调优、索引
Phase 4.7: UI 大改 + 文件夹导航    ✅ 6页完全重构、文件夹分类、图谱自动加载、LaTeX、收藏
Phase 5.1: 图表/公式智能识别       ✅ PyMuPDF 提取 + Vision 解读 + 持久化 + 前端展示
Phase 5.2: 推理链深度分析          ✅ 5步推理链 + 3维评分 + 方法/实验验证链 + 折叠面板
Phase 5.3: 研究空白识别            ✅ 引用网络稀疏区域 + 方法矩阵 + 趋势分析 + Agent工具
Phase 5.4: PDF 沉浸式阅读器        ✅ react-pdf 连续滚动 + AI 解释/翻译/总结侧栏
Phase 5.5: 论文库分页 + 日期分类   ✅ 后端分页 API + 按收录日期分组 + LLM 成本全覆盖
Phase 5.6: 增强引用分析 + 图谱重构 ✅ SS丰富引用详情 + 力导向图 + 全局概览/引文/洞察三面板
Phase 5.7: 参考文献一键入库         ✅ arXiv全量+SS元数据双通道 + 去重 + 引用边 + 行动记录 + 后台进度

下阶段 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 6: 知识增强检索（2-3周）
  → GraphRAG + 多智能体协作 + 自动综述 + 代码关联

Phase 7: 体验打磨与智能推送（远期）
  → 智能论文监控推送 + Agent 交互体验深度优化
```

---

## 5. 已确认决策

| # | 问题 | 决策 |
|---|------|------|
| 1 | 多智能体 vs 单 Agent 增强 | 可以做多 Agent，但效果优先，先试点再扩展 |
| 2 | GraphRAG 社区粒度 | 在现有 RAG 基础上渐进改进，新旧并存 |
| 3 | 本地模型部署 | ❌ 不做，无 GPU 资源 |
| 4 | 协作需求 | ❌ 不做，专注单人体验优化 |
| 5 | MCP 生态 | ❌ 不做，当前无实际需求 |
| 6 | 开发优先级 | 基础体验优化 > 高级特性，功能完美度 > 功能数量 |
| 7 | 定时调度模型 | 按主题独立调度（每小时 dispatch），弃用全局单一 cron |
| 8 | AI 关键词建议 | 同时支持 /collect 页面和 Agent 对话 |
