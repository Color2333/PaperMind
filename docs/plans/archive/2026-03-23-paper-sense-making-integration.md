# PaperSenseMaking 整合设计文档

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 paper-sense-making 的认知重构理念融入 PaperMind，打造"阅读→理解→重构"的完整论文工作流。

**Architecture:**
- **Phase 1**: User Schema 数据模型 + ToolPanel Tab 化改造
- **Phase 2**: SensemakingSession 流程（Act 1/2/3）+ Canvas 可视化
- **Phase 3**: PDF 双栏对照翻译（全文模式）

**Tech Stack:** React 18, FastAPI, SQLite, react-pdf, LLM (GLM-4), Canvas (D3.js/two.js)

---

## 1. 概念映射

### paper-sense-making → PaperMind

| paper-sense-making 概念 | PaperMind 实现 | 位置 |
|------------------------|---------------|------|
| Module 2: PaperSensemaking | PDF 阅读器 + ToolPanel (Sensemaking Tab) | PdfReader.tsx 改造 |
| Module 4: User Schema | UserSchema 数据模型 | 新建 models |
| Module 5: SensemakingCanvas | 右侧面板 Canvas 可视化 | 新建组件 |
| Act 1: Comprehension | Paper 阅读 + 核心观点提取 | ToolPanel Tab |
| Act 2: Collision | 用户 Schema vs Paper 挑战 | ToolPanel Tab |
| Act 3: Reconstruction | Before/After Delta + Canvas | ToolPanel Tab + Canvas |

---

## 2. 数据模型设计

### 2.1 UserSchema (新建)

```python
# apps/api/models/sensemaking.py

class UserSchema(Base):
    """用户认知 Schema - 存储用户的学术背景和关注领域"""
    __tablename__ = "user_schemas"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)  # 预留多用户支持
    name = Column(String, nullable=False)  # Schema 名称，如"深度学习研究"

    # 核心关注点 - 研究方向
    research_topics = Column(JSON, default=list)  # ["深度学习", "强化学习", "NLP"]

    # 学术背景 - 研究层次
    academic_level = Column(String, nullable=True)  # "PhD", "Master", "Industry"

    # 研究阶段 - 当前正在攻克的难题
    current_challenges = Column(JSON, default=list)  # ["如何提升模型泛化性"]

    # 信仰/立场 - 对某些技术路线的看法
    beliefs = Column(JSON, default=list)  # ["Transformer 比 CNN 更好", "LLM 需要符号推理"]

    # 知识缺口 - 想要补充的方向
    knowledge_gaps = Column(JSON, default=list)  # ["因果推理", "神经符号"]

    # Schema 版本，用于追踪变化
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

### 2.2 SensemakingSession (新建)

```python
class SensemakingSession(Base):
    """论文认知重构会话 - 存储完整的认知重构过程"""
    __tablename__ = "sensemaking_sessions"

    id = Column(String, primary_key=True)
    paper_id = Column(String, nullable=False, index=True)
    user_schema_id = Column(String, ForeignKey("user_schemas.id"), nullable=False)

    # 三幕结构数据 (Act 1/2/3)
    act1_comprehension = Column(JSON, nullable=True)
    act2_collision = Column(JSON, nullable=True)
    act3_reconstruction = Column(JSON, nullable=True)

    # 元数据
    status = Column(String, default="in_progress")  # in_progress, completed, abandoned
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # 关联的 AI 对话历史 (可选)
    conversation_history = Column(JSON, default=list)
```

### 2.3 Schema-M-Paper (关联表)

```python
class SchemaPaperInteraction(Base):
    """用户 Schema 与论文的交互记录"""
    __tablename__ = "schema_paper_interactions"

    id = Column(String, primary_key=True)
    user_schema_id = Column(String, ForeignKey("user_schemas.id"), nullable=False)
    paper_id = Column(String, nullable=False, index=True)

    # 交互类型
    interaction_type = Column(String, nullable=False)  # "viewed", "sensemaking_completed", "challenged"

    # 用户对这篇论文的认知变化
    cognitive_delta = Column(JSON, nullable=True)  # {"before": "...", "after": "...", "change": "..."}

    created_at = Column(DateTime, default=datetime.utcnow)
```

---

## 3. 前端架构设计

### 3.1 PDF 阅读器改造

**文件:** `frontend/src/components/PdfReader.tsx` (改造)

```
┌─────────────────────────────────────────────────────────────────┐
│  Toolbar: 标题 | 页码 | 缩放 | 全屏          [选中文字] [工具按钮] │
├─────────────────────────────┬─────────────────────────────────┤
│                             │  ToolPanel (可折叠/展开)          │
│   PDF 阅读区                  │  ┌─────────────────────────────┐ │
│   (连续滚动模式)              │  │ [翻译] [AI聚合] [Canvas]    │ │
│                             │  ├─────────────────────────────┤ │
│                             │  │                             │ │
│                             │  │     活动 Tab 内容区          │ │
│                             │  │     (支持滚动)               │ │
│                             │  │                             │ │
│                             │  └─────────────────────────────┘ │
└─────────────────────────────┴─────────────────────────────────┘
```

**ToolPanel Tab 结构:**

| Tab | 功能 | 状态 |
|-----|------|------|
| 翻译 | 划词翻译 / 全文对照翻译 | 改造 (现有 AI Panel) |
| AI聚合 | 多源搜索 / 论文摘要 | 集成 feat/ieee |
| Canvas | Sensemaking 可视化 | 新开发 |

**关键改造点:**

1. **右侧 AI Panel → TabPanel**
   - 固定宽度 384px → 可拖拽调整
   - 支持 Tab 切换
   - Tab 内容区域独立滚动

2. **选中文字 → 全局状态**
   - 新增 `useSelectedText` hook
   - 选中文字后自动同步到 ToolPanel
   - ToolPanel 各 Tab 都能访问选中文字

3. **PdfReaderProps 扩展**
   ```typescript
   interface PdfReaderProps {
     // ... 现有 props
     userSchemaId?: string;  // 当前用户的 Schema ID
     onSensemakingStart?: (paperId: string) => void;  // 开始认知重构
   }
   ```

### 3.2 新建组件

**1. ToolPanel.tsx** (新建)
```
frontend/src/components/ToolPanel/
├── ToolPanel.tsx        # 主容器，Tab 管理
├── ToolPanelTab.tsx     # Tab 按钮
├── TranslationPanel.tsx # 翻译 Tab 内容
├── AggregationPanel.tsx # AI聚合 Tab 内容 (feat/ieee 迁移)
└── CanvasPanel.tsx      # Canvas Tab 内容
```

**2. SensemakingCanvas.tsx** (新建)
```
frontend/src/components/SensemakingCanvas/
├── SensemakingCanvas.tsx      # Canvas 主组件
├── DeltaVisualization.tsx     # Before/After Delta 可视化
└── CognitiveGraph.tsx         # 认知图谱 (D3.js)
```

**3. UserSchemaEditor.tsx** (新建)
- 用于创建/编辑 User Schema
- 位置: `/settings/schema` 或 `/profile/schema`

---

## 4. 全文对照翻译方案

### 4.1 需求分析

大白想要的"全文对照翻译"：
- 保持原文的排版（段落、标题层级）
- 保持原文的图片、公式、表格位置
- 左边原文，右边翻译，同步滚动

### 4.2 技术挑战

1. **PDF 内容提取**
   - react-pdf 的 Document 渲染后是 Canvas，无法直接获取文本坐标
   - 需要额外解析：pdf.js 的 TextContent API 或 pdfminer

2. **双栏同步滚动**
   - 原文和翻译的段落需要一一对应
   - 用户滚动一边，另一边自动同步
   - 鼠标悬停高亮对应段落

3. **图片/公式处理**
   - 公式通常是图片或 MathML
   - 扫描版 PDF 整个页面都是图片

### 4.3 实现方案 (MVP → Full)

**MVP 方案: 段落对照模式**

```
┌────────────────────┬────────────────────┐
│  Section 1        │  第一部分           │
│  (原文)            │  (翻译)            │
│                    │                    │
│  This is a para... │  这是一段文字...    │
├────────────────────┼────────────────────┤
│  [Figure 1]        │  [Figure 1]        │
│  (原图)            │  (原图)            │
├────────────────────┼────────────────────┤
│  Section 2        │  第二部分           │
│  (原文)            │  (翻译)            │
└────────────────────┴────────────────────┘
```

**实现步骤:**

1. **Phase 1 (MVP)**: 划词翻译
   - 选中文字 → 调用翻译 API → 显示浮层翻译
   - 不改变 PDF 阅读体验

2. **Phase 2**: 段级对照翻译
   - 调用 LLM 翻译文档，返回分段翻译
   - 双栏显示，段落一一对应
   - PDF 渲染为单栏，翻译面板在右侧

3. **Phase 3**: 全文对照翻译
   - 完整保留 PDF 排版
   - 左右分栏同步滚动
   - 图片/公式位置对应

### 4.4 API 设计

```python
# 翻译 API (新增)
@router.post("/papers/{paper_id}/translate")
async def translate_paper(
    paper_id: str,
    mode: str = "selection",  # "selection" | "paragraph" | "full"
    text: str = None,
    target_lang: str = "zh"
):
    """翻译论文内容"""
    # mode=selection: 翻译选中文字
    # mode=paragraph: 翻译整个段落
    # mode=full: 翻译整篇论文 (返回分段翻译结果)
```

---

## 5. Sensemaking 流程设计

### 5.1 Act 1: Comprehension (理解)

**目标:** 提取论文的核心观点，理解论文在说什么

**交互流程:**
1. 用户在 PDF 阅读器中点击 "Canvas" Tab
2. 系统展示论文基本信息 (标题、作者、摘要)
3. 用户选择 "开始阅读" → 进入 Comprehension 模式
4. 系统引导用户:
   - "这篇论文的核心观点是什么？"
   - "作者是如何论证的？"
   - "你从中学习到了什么？"
5. 用户输入，系统记录到 `act1_comprehension`

**数据结构:**
```json
{
  "core_claim": "Transformers are better than CNNs for NLP tasks",
  "learning_mechanism": "Through self-attention mechanism",
  "user_perspective": "I agree because...",
  "notes": ["key point 1", "key point 2"]
}
```

### 5.2 Act 2: Collision (碰撞)

**目标:** 识别论文观点与用户已有认知的冲突/一致

**触发条件:** 需要用户 Schema 信息

**交互流程:**
1. 系统根据 User Schema 推断用户的现有观点
2. 系统展示论文观点 vs 用户观点的对比
3. 用户识别摩擦点 (Friction Points):
   - "论文说 A，我认为 B"
   - "论文论证方法有漏洞"
   - "我的实验数据和论文结论矛盾"
4. 用户表明立场 (Stance): 支持/反对/中立
5. 记录到 `act2_collision`

**数据结构:**
```json
{
  "user_schema_before": "I believe transformers are not suitable for small datasets",
  "paper_challenge": "This paper shows transformers can work well with small data via pre-training",
  "friction_points": [
    "Data efficiency assumption vs my experience"
  ],
  "user_stance": "neutral",
  "user_reasoning": "The pre-training approach is interesting but requires extra resources",
  "probe_exchange": [
    {"role": "user", "content": "What about computational cost?"},
    {"role": "assistant", "content": "..."}
  ]
}
```

### 5.3 Act 3: Reconstruction (重构)

**目标:** 形成新的认知，理解论文如何改变了你对这个领域的理解

**交互流程:**
1. 系统展示 Before State (用户原来的认知)
2. 用户描述 After State (阅读后的新认知)
3. 系统计算 Delta (变化)
4. 用户承诺一个改变 (One Change): "我要在下次实验中尝试..."
5. 保存到 `act3_reconstruction`

**数据结构:**
```json
{
  "before": "Transformers need large datasets to perform well",
  "after": "Transformers can work on small datasets with proper pre-training",
  "delta": "Pre-training democratizes transformer usage",
  "one_change": "I will pre-train on domain-specific corpus before fine-tuning"
}
```

### 5.4 Canvas 可视化

**Delta 可视化:**

```
  Before          Delta           After
┌─────────┐    ┌─────────┐    ┌─────────┐
│ ██████  │ → │ ████    │ → │ ████████│
│ 旧认知   │    │ 变化点  │    │ 新认知   │
└─────────┘    └─────────┘    └─────────┘
```

**认知图谱:**

- 节点: 论文观点、用户信念、冲突点
- 边: 支撑/反对/转化关系
- 颜色: 论文观点(蓝) vs 用户信念(橙) vs 新认知(绿)

---

## 6. 实施计划

### Phase 1: 基础层 (User Schema + ToolPanel Tab 化)

| 任务 | 文件 | 描述 |
|------|------|------|
| T1.1 | `apps/api/models/sensemaking.py` | 新建 UserSchema, SensemakingSession 模型 |
| T1.2 | `apps/api/routes/sensemaking.py` | 新建 CRUD API |
| T1.3 | `frontend/src/hooks/useSelectedText.ts` | 新建选中文字 Hook |
| T1.4 | `frontend/src/components/ToolPanel/` | 新建 ToolPanel 组件 (Tab 化) |
| T1.5 | `frontend/src/components/PdfReader.tsx` | 改造: 集成 ToolPanel |

### Phase 2: 核心功能 (Sensemaking 流程 + Canvas)

| 任务 | 文件 | 描述 |
|------|------|------|
| T2.1 | `frontend/src/components/ToolPanel/CanvasPanel.tsx` | Canvas Tab 内容 |
| T2.2 | `frontend/src/components/SensemakingCanvas/` | Canvas 可视化组件 |
| T2.3 | `apps/api/routes/sensemaking.py` | Act 1/2/3 API 逻辑 |
| T2.4 | `frontend/src/pages/Settings/` | UserSchema Editor 页面 |

### Phase 3: 翻译增强 (全文对照)

| 任务 | 文件 | 描述 |
|------|------|------|
| T3.1 | `apps/api/routes/translate.py` | 翻译 API (段级/全文) |
| T3.2 | `frontend/src/components/ToolPanel/TranslationPanel.tsx` | 翻译 Tab 升级 |
| T3.3 | `frontend/src/components/DualColumnPDF.tsx` | 双栏对照 PDF 组件 |

---

## 7. 优先级建议

1. **T1.1-T1.3**: User Schema 模型 + API (半天)
2. **T1.4-T1.5**: ToolPanel Tab 化 (1天)
3. **T2.1-T2.3**: Sensemaking 流程 + Canvas (2天)
4. **T2.4**: UserSchema Editor (0.5天)
5. **T3.1-T3.3**: 全文对照翻译 (2天)

**预计总工期: 5-6 天**

---

## 8. 确认决策

- [x] **全文对照翻译**: 分期实现
  - **Phase 1 (MVP)**: A - 段落对照模式
  - **Phase 2 (必须实现)**: B - PDF 重渲染模式（完整保留 PDF 排版和图片）
- [x] **Canvas 可视化**: 分期实现
  - **Phase 1 (MVP)**: A - Before/After 简单对比视图
  - **Phase 2 (必须实现)**: B - D3.js 认知图谱（节点+边+动画，可交互）
