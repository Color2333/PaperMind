# PaperSenseMaking 整合 - 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 paper-sense-making 的认知重构理念融入 PaperMind，打造"阅读→理解→重构"的完整论文工作流

**Architecture:**
- 数据层: UserSchema + SensemakingSession 数据模型
- 前端: PdfReader ToolPanel Tab 化 + Canvas MVP 可视化
- 后端: Sensemaking API (Act 1/2/3 流程)
- 翻译: 段落对照翻译 (MVP)

**Tech Stack:** React 18 + TypeScript + FastAPI + SQLite + react-pdf + D3.js

---

## Phase 1: 基础层 (UserSchema + ToolPanel Tab 化)

---

### Task 1: 后端数据模型

**Files:**
- Create: `apps/api/models/sensemaking.py`
- Modify: `apps/api/models/__init__.py` (导出新模型)
- Modify: `apps/api/main.py` (注册路由)
- Test: `tests/test_sensemaking_models.py`

**Step 1: 创建 sensemaking.py 数据模型**

```python
# apps/api/models/sensemaking.py
from sqlalchemy import Column, String, JSON, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from apps.api.models.base import Base
import datetime
import uuid

class UserSchema(Base):
    """用户认知 Schema - 存储用户的学术背景和关注领域"""
    __tablename__ = "user_schemas"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)

    # 研究方向
    research_topics = Column(JSON, default=list)
    # 学术背景
    academic_level = Column(String, nullable=True)
    # 当前挑战
    current_challenges = Column(JSON, default=list)
    # 信仰/立场
    beliefs = Column(JSON, default=list)
    # 知识缺口
    knowledge_gaps = Column(JSON, default=list)

    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联
    sessions = relationship("SensemakingSession", back_populates="user_schema")
    interactions = relationship("SchemaPaperInteraction", back_populates="user_schema")


class SensemakingSession(Base):
    """论文认知重构会话"""
    __tablename__ = "sensemaking_sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    paper_id = Column(String, nullable=False, index=True)
    user_schema_id = Column(String, ForeignKey("user_schemas.id"), nullable=False)

    # 三幕结构
    act1_comprehension = Column(JSON, nullable=True)
    act2_collision = Column(JSON, nullable=True)
    act3_reconstruction = Column(JSON, nullable=True)

    status = Column(String, default="in_progress")
    conversation_history = Column(JSON, default=list)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # 关联
    user_schema = relationship("UserSchema", back_populates="sessions")


class SchemaPaperInteraction(Base):
    """用户 Schema 与论文的交互记录"""
    __tablename__ = "schema_paper_interactions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_schema_id = Column(String, ForeignKey("user_schemas.id"), nullable=False)
    paper_id = Column(String, nullable=False, index=True)

    interaction_type = Column(String, nullable=False)
    cognitive_delta = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # 关联
    user_schema = relationship("UserSchema", back_populates="interactions")
```

**Step 2: 导出新模型**

修改 `apps/api/models/__init__.py`:
```python
from apps.api.models.sensemaking import UserSchema, SensemakingSession, SchemaPaperInteraction

__all__ = [
    # ... existing
    "UserSchema",
    "SensemakingSession",
    "SchemaPaperInteraction",
]
```

**Step 3: 创建 sensemaking 路由**

```python
# apps/api/routes/sensemaking.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from apps.api.models.sensemaking import UserSchema, SensemakingSession, SchemaPaperInteraction
from apps.api.db import get_db

router = APIRouter(prefix="/sensemaking", tags=["sensemaking"])

class UserSchemaCreate(BaseModel):
    name: str
    research_topics: list[str] = []
    academic_level: Optional[str] = None
    current_challenges: list[str] = []
    beliefs: list[str] = []
    knowledge_gaps: list[str] = []

class SensemakingSessionCreate(BaseModel):
    paper_id: str
    user_schema_id: str

# TODO: 实现 CRUD API
```

**Step 4: 注册路由**

修改 `apps/api/main.py`:
```python
from apps.api.routes import sensemaking
app.include_router(sensemaking.router)
```

---

### Task 2: 前端 ToolPanel 组件

**Files:**
- Create: `frontend/src/hooks/useSelectedText.ts`
- Create: `frontend/src/components/ToolPanel/ToolPanel.tsx`
- Create: `frontend/src/components/ToolPanel/ToolPanelTab.tsx`
- Create: `frontend/src/components/ToolPanel/TranslationPanel.tsx`
- Create: `frontend/src/components/ToolPanel/AggregationPanel.tsx`
- Create: `frontend/src/components/ToolPanel/CanvasPanel.tsx`
- Modify: `frontend/src/components/PdfReader.tsx`
- Test: `frontend/src/components/ToolPanel/ToolPanel.test.tsx`

**Step 1: 创建 useSelectedText Hook**

```typescript
// frontend/src/hooks/useSelectedText.ts
import { useState, useCallback, useEffect } from 'react';

export function useSelectedText() {
  const [selectedText, setSelectedText] = useState('');

  useEffect(() => {
    const handler = () => {
      const sel = window.getSelection()?.toString().trim();
      if (sel && sel.length > 2) {
        setSelectedText(sel);
      }
    };
    document.addEventListener('mouseup', handler);
    return () => document.removeEventListener('mouseup', handler);
  }, []);

  return selectedText;
}
```

**Step 2: 创建 ToolPanel Tab 系统**

```typescript
// frontend/src/components/ToolPanel/ToolPanel.tsx
import { useState } from 'react';
import { PanelLeftClose, PanelLeft, Languages, Sparkles, GitBranch } from 'lucide-react';

export type TabId = 'translation' | 'aggregation' | 'canvas';

interface Tab {
  id: TabId;
  label: string;
  icon: React.ReactNode;
}

const TABS: Tab[] = [
  { id: 'translation', label: '翻译', icon: <Languages className="h-4 w-4" /> },
  { id: 'aggregation', label: 'AI聚合', icon: <Sparkles className="h-4 w-4" /> },
  { id: 'canvas', label: 'Canvas', icon: <GitBranch className="h-4 w-4" /> },
];

interface ToolPanelProps {
  selectedText: string;
  paperId: string;
  children: {
    translation: React.ReactNode;
    aggregation: React.ReactNode;
    canvas: React.ReactNode;
  };
}

export function ToolPanel({ selectedText, paperId, children }: ToolPanelProps) {
  const [activeTab, setActiveTab] = useState<TabId>('translation');
  const [collapsed, setCollapsed] = useState(false);

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        className="flex h-full w-12 flex-col items-center gap-2 border-l border-white/10 bg-[#1e1e2e] py-4"
      >
        <PanelLeft className="h-5 w-5 text-white/40" />
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => { setActiveTab(tab.id); setCollapsed(false); }}
            className="rounded p-2 text-white/40 hover:bg-white/10 hover:text-white"
            title={tab.label}
          >
            {tab.icon}
          </button>
        ))}
      </button>
    );
  }

  return (
    <div className="relative flex h-full flex-col border-l border-white/10 bg-[#1e1e2e] transition-all duration-300"
         style={{ width: collapsed ? 48 : 384 }}>
      {/* 头部 */}
      <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
        <div className="flex items-center gap-2">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition-colors ${
                activeTab === tab.id
                  ? 'bg-primary/20 text-primary'
                  : 'text-white/60 hover:bg-white/10 hover:text-white'
              }`}
            >
              {tab.icon}
              <span className="hidden sm:inline">{tab.label}</span>
            </button>
          ))}
        </div>
        <button
          onClick={() => setCollapsed(true)}
          className="rounded p-1.5 text-white/40 hover:bg-white/10 hover:text-white"
        >
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>

      {/* 内容区 */}
      <div className="flex-1 overflow-auto">
        {activeTab === 'translation' && children.translation}
        {activeTab === 'aggregation' && children.aggregation}
        {activeTab === 'canvas' && children.canvas}
      </div>
    </div>
  );
}
```

**Step 3: 改造 PdfReader.tsx**

修改 `frontend/src/components/PdfReader.tsx`:
```typescript
// 1. 添加导入
import { ToolPanel } from './ToolPanel/ToolPanel';
import { TranslationPanel } from './ToolPanel/TranslationPanel';
import { AggregationPanel } from './ToolPanel/AggregationPanel';
import { CanvasPanel } from './ToolPanel/CanvasPanel';
import { useSelectedText } from '@/hooks/useSelectedText';

// 2. 替换右侧 AI Panel
// 旧代码 (line 391-504):
// {/* AI 侧边栏 */}
// <div className={`relative mt-12 border-l ...`}>
//   ...
// </div>

// 新代码:
// 替换为 ToolPanel
<div className={`relative mt-12 border-l border-white/10 transition-all duration-300 ${
  aiPanelOpen ? "w-96" : "w-0"
} overflow-hidden`}>
  {aiPanelOpen && (
    <ToolPanel selectedText={selectedText} paperId={paperId}>
      {{
        translation: <TranslationPanel selectedText={selectedText} paperId={paperId} />,
        aggregation: <AggregationPanel selectedText={selectedText} paperId={paperId} />,
        canvas: <CanvasPanel paperId={paperId} paperTitle={paperTitle} />,
      }}
    </ToolPanel>
  )}
</div>
```

---

### Task 3: TranslationPanel (迁移现有 AI Panel 逻辑)

**Files:**
- Create: `frontend/src/components/ToolPanel/TranslationPanel.tsx`

**Step 1: 创建 TranslationPanel**

```typescript
// frontend/src/components/ToolPanel/TranslationPanel.tsx
import { useState, useCallback } from 'react';
import { Loader2, Copy, Check, Languages } from 'lucide-react';
import Markdown from '@/components/Markdown';
import { paperApi } from '@/services/api';

type AiAction = 'explain' | 'translate' | 'summarize';

interface AiResult {
  action: AiAction;
  text: string;
  result: string;
}

interface TranslationPanelProps {
  selectedText: string;
  paperId: string;
}

export function TranslationPanel({ selectedText, paperId }: TranslationPanelProps) {
  const [aiLoading, setAiLoading] = useState(false);
  const [aiResults, setAiResults] = useState<AiResult[]>([]);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);

  const handleAiAction = useCallback(async (action: AiAction, text?: string) => {
    const t = text || selectedText;
    if (!t) return;
    setAiLoading(true);
    try {
      const res = await paperApi.aiExplain(paperId, t, action);
      setAiResults((prev) => [{ action, text: t.slice(0, 100), result: res.result }, ...prev]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setAiResults((prev) => [{ action, text: t.slice(0, 100), result: `错误: ${msg}` }, ...prev]);
    } finally {
      setAiLoading(false);
    }
  }, [paperId, selectedText]);

  const handleCopy = useCallback((idx: number, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedIdx(idx);
    setTimeout(() => setCopiedIdx(null), 2000);
  }, []);

  const actionLabels: Record<AiAction, { label: string; color: string }> = {
    explain: { label: '解释', color: 'text-amber-600 bg-amber-50' },
    translate: { label: '翻译', color: 'text-blue-600 bg-blue-50' },
    summarize: { label: '总结', color: 'text-emerald-600 bg-emerald-50' },
  };

  return (
    <div className="flex h-full flex-col">
      {/* 快捷操作 */}
      {selectedText && (
        <div className="border-b border-white/10 px-4 py-3">
          <p className="mb-2 text-xs text-white/40">选中文本</p>
          <p className="mb-3 line-clamp-3 rounded-md bg-white/5 p-2 text-xs leading-relaxed text-white/70">
            {selectedText}
          </p>
          <div className="flex gap-2">
            <button onClick={() => handleAiAction('explain')} disabled={aiLoading}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-amber-500/10 py-1.5 text-xs text-amber-300 hover:bg-amber-500/20">
              解释
            </button>
            <button onClick={() => handleAiAction('translate')} disabled={aiLoading}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-blue-500/10 py-1.5 text-xs text-blue-300 hover:bg-blue-500/20">
              翻译
            </button>
            <button onClick={() => handleAiAction('summarize')} disabled={aiLoading}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-emerald-500/10 py-1.5 text-xs text-emerald-300 hover:bg-emerald-500/20">
              总结
            </button>
          </div>
        </div>
      )}

      {/* 结果列表 */}
      <div className="flex-1 overflow-auto px-4 py-3">
        {aiLoading && (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2">
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            <span className="text-xs text-primary">AI 分析中...</span>
          </div>
        )}

        {aiResults.length === 0 && !aiLoading && (
          <div className="flex flex-col items-center gap-3 pt-12 text-center">
            <Languages className="h-10 w-10 text-white/10" />
            <p className="text-sm text-white/40">选中论文文本</p>
            <p className="text-xs text-white/20">即可使用 AI 解释、翻译、总结</p>
          </div>
        )}

        {aiResults.map((r, i) => (
          <div key={i} className="mb-4 overflow-hidden rounded-xl border border-white/[.08]">
            <div className="flex items-center justify-between border-b border-white/[.06] px-3.5 py-2">
              <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium ${r.action === 'explain' ? 'bg-amber-500/10 text-amber-300' : r.action === 'translate' ? 'bg-blue-500/10 text-blue-300' : 'bg-emerald-500/10 text-emerald-300'}`}>
                {actionLabels[r.action].label}
              </span>
              <button onClick={() => handleCopy(i, r.result)} className="rounded-md p-1 text-white/20 hover:bg-white/10">
                {copiedIdx === i ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
              </button>
            </div>
            <div className="border-b border-white/[.04] px-3.5 py-2">
              <p className="line-clamp-2 border-l-2 border-white/10 pl-2.5 text-[11px] leading-relaxed text-white/30 italic">
                {r.text}
              </p>
            </div>
            <div className="px-3.5 py-3">
              <Markdown className="pdf-ai-markdown">{r.result}</Markdown>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

---

### Task 4: AggregationPanel (集成 feat/ieee 多源搜索)

**Files:**
- Create: `frontend/src/components/ToolPanel/AggregationPanel.tsx`

**Step 1: 创建 AggregationPanel**

```typescript
// frontend/src/components/ToolPanel/AggregationPanel.tsx
// 从 feat/ieee 分支迁移 MultiSourceSearchBar 和 SearchResultsList 相关逻辑
// 具体实现略，参考 docs/plans/2026-03-23-multi-source-implementation.md
```

---

## Phase 2: Sensemaking 核心流程 + Canvas MVP

---

### Task 5: CanvasPanel MVP (Before/After 对比视图)

**Files:**
- Create: `frontend/src/components/ToolPanel/CanvasPanel.tsx`
- Create: `frontend/src/components/SensemakingCanvas/DeltaCard.tsx`
- Modify: `apps/api/routes/sensemaking.py`
- Test: `frontend/src/components/SensemakingCanvas/DeltaCard.test.tsx`

**Step 1: 创建 DeltaCard 组件**

```typescript
// frontend/src/components/SensemakingCanvas/DeltaCard.tsx
interface DeltaCardProps {
  label: string;
  content: string;
  variant: 'before' | 'after' | 'delta';
}

export function DeltaCard({ label, content, variant }: DeltaCardProps) {
  const colors = {
    before: 'border-white/20 bg-white/5',
    after: 'border-primary/30 bg-primary/5',
    delta: 'border-amber-500/30 bg-amber-500/5',
  };

  return (
    <div className={`rounded-xl border p-4 ${colors[variant]}`}>
      <p className="mb-2 text-xs font-medium text-white/40">{label}</p>
      <p className="text-sm leading-relaxed text-white/80">{content || '...'}</p>
    </div>
  );
}
```

**Step 2: 创建 CanvasPanel**

```typescript
// frontend/src/components/ToolPanel/CanvasPanel.tsx
import { useState } from 'react';
import { DeltaCard } from '@/components/SensemakingCanvas/DeltaCard';
import { ArrowRight } from 'lucide-react';

interface Act3Reconstruction {
  before: string;
  after: string;
  delta: string;
  one_change: string;
}

interface CanvasPanelProps {
  paperId: string;
  paperTitle: string;
}

export function CanvasPanel({ paperId, paperTitle }: CanvasPanelProps) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [act3, setAct3] = useState<Act3Reconstruction | null>(null);
  const [loading, setLoading] = useState(false);

  // TODO: 从后端加载 session 数据
  const loadSession = async () => {
    setLoading(true);
    // await fetch(`/api/sensemaking/sessions?paper_id=${paperId}`)
    setLoading(false);
  };

  return (
    <div className="flex h-full flex-col gap-4 p-4">
      <div className="text-center">
        <h3 className="text-lg font-medium text-white/90">{paperTitle}</h3>
        <p className="text-xs text-white/40">认知重构工作台</p>
      </div>

      {!act3 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-4">
          <p className="text-sm text-white/60">开始你的认知重构之旅</p>
          <button
            onClick={() => {/* TODO: 启动 Sensemaking 流程 */}}
            className="rounded-full bg-primary/20 px-6 py-2 text-sm text-primary hover:bg-primary/30"
          >
            开始阅读理解
          </button>
        </div>
      ) : (
        <div className="flex flex-1 flex-col gap-4 overflow-auto">
          {/* Before */}
          <DeltaCard label="阅读前" content={act3.before} variant="before" />

          {/* Arrow */}
          <div className="flex items-center justify-center">
            <ArrowRight className="h-5 w-5 text-primary" />
          </div>

          {/* After */}
          <DeltaCard label="阅读后" content={act3.after} variant="after" />

          {/* Delta */}
          <DeltaCard label="认知变化" content={act3.delta} variant="delta" />

          {/* One Change */}
          <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4">
            <p className="mb-2 text-xs font-medium text-emerald-400">我的承诺</p>
            <p className="text-sm text-emerald-300">{act3.one_change}</p>
          </div>
        </div>
      )}
    </div>
  );
}
```

---

### Task 6: Sensemaking API (Act 1/2/3 流程)

**Files:**
- Modify: `apps/api/routes/sensemaking.py`
- Create: `apps/api/services/sensemaking.py`
- Test: `tests/test_sensemaking_api.py`

**Step 1: 实现 SensemakingService**

```python
# apps/api/services/sensemaking.py
from apps.api.models.sensemaking import SensemakingSession, UserSchema
from apps.api.db import get_db
from sqlalchemy.orm import Session
from typing import Optional
import json

class SensemakingService:
    def __init__(self, db: Session):
        self.db = db

    def create_session(self, paper_id: str, user_schema_id: str) -> SensemakingSession:
        session = SensemakingSession(
            paper_id=paper_id,
            user_schema_id=user_schema_id,
            status="in_progress"
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def update_act1(self, session_id: str, act1_data: dict) -> SensemakingSession:
        session = self.db.query(SensemakingSession).filter_by(id=session_id).first()
        session.act1_comprehension = act1_data
        self.db.commit()
        self.db.refresh(session)
        return session

    def update_act2(self, session_id: str, act2_data: dict) -> SensemakingSession:
        session = self.db.query(SensemakingSession).filter_by(id=session_id).first()
        session.act2_collision = act2_data
        self.db.commit()
        self.db.refresh(session)
        return session

    def complete_act3(self, session_id: str, act3_data: dict) -> SensemakingSession:
        session = self.db.query(SensemakingSession).filter_by(id=session_id).first()
        session.act3_reconstruction = act3_data
        session.status = "completed"
        from datetime import datetime
        session.completed_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(session)
        return session

    def get_sessions_by_paper(self, paper_id: str) -> list[SensemakingSession]:
        return self.db.query(SensemakingSession).filter_by(paper_id=paper_id).all()
```

---

## Phase 3: 全文对照翻译 (MVP)

---

### Task 7: 段落对照翻译 API

**Files:**
- Create: `apps/api/routes/translate.py`
- Create: `apps/api/services/translate.py`
- Modify: `frontend/src/components/ToolPanel/TranslationPanel.tsx`
- Test: `tests/test_translate_api.py`

**Step 1: 创建翻译服务**

```python
# apps/api/services/translate.py
from apps.api.services.llm import LLMService

class TranslateService:
    def __init__(self):
        self.llm = LLMService()

    async def translate_paragraph(self, text: str, target_lang: str = "zh") -> str:
        prompt = f"""Translate the following academic text to {target_lang}.
        Maintain the academic tone and technical terminology.

        Text:
        {text}

        Translation:"""

        result = await self.llm.generate(prompt)
        return result

    async def translate_full_paper_segments(self, segments: list[dict], target_lang: str = "zh") -> list[dict]:
        """翻译论文分段

        Args:
            segments: [{"id": "1", "type": "paragraph", "content": "..."}, ...]
            target_lang: 目标语言

        Returns:
            [{"id": "1", "type": "paragraph", "content": "...", "translation": "..."}, ...]
        """
        results = []
        for seg in segments:
            translation = await self.translate_paragraph(seg["content"], target_lang)
            results.append({
                **seg,
                "translation": translation
            })
        return results
```

**Step 2: 创建翻译路由**

```python
# apps/api/routes/translate.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/translate", tags=["translate"])

class TranslateRequest(BaseModel):
    text: str
    target_lang: str = "zh"

class TranslateResponse(BaseModel):
    original: str
    translation: str

@router.post("/selection", response_model=TranslateResponse)
async def translate_selection(req: TranslateRequest):
    """翻译选中文字"""
    # TODO: 实现
    pass

@router.post("/paragraph")
async def translate_paragraph(text: str, target_lang: str = "zh"):
    """翻译段落"""
    # TODO: 实现
    pass

@router.post("/segments")
async def translate_segments(segments: list[dict], target_lang: str = "zh"):
    """翻译论文分段（返回对照翻译）"""
    # TODO: 实现
    pass
```

---

### Task 8: 段落对照翻译前端

**Files:**
- Modify: `frontend/src/components/ToolPanel/TranslationPanel.tsx`

**Step 1: 添加段落对照翻译模式**

```typescript
// frontend/src/components/ToolPanel/TranslationPanel.tsx

interface TranslationPanelProps {
  selectedText: string;
  paperId: string;
}

export function TranslationPanel({ selectedText, paperId }: TranslationPanelProps) {
  const [mode, setMode] = useState<'selection' | 'paragraph'>('selection');
  // ... existing state

  // 段落对照翻译
  const [segments, setSegments] = useState<Array<{
    id: string;
    type: 'paragraph' | 'figure';
    content: string;
    translation?: string;
  }>>([]);

  const handleTranslateFull = async () => {
    // TODO: 调用 /api/translate/segments 获取分段翻译
    const res = await fetch(`/api/papers/${paperId}/segments`);
    const data = await res.json();
    setSegments(data.segments);
    setMode('paragraph');
  };

  return (
    <div className="flex h-full flex-col">
      {/* 模式切换 */}
      <div className="flex gap-2 border-b border-white/10 px-4 py-2">
        <button
          onClick={() => setMode('selection')}
          className={`text-xs ${mode === 'selection' ? 'text-primary' : 'text-white/40'}`}
        >
          划词翻译
        </button>
        <button
          onClick={handleTranslateFull}
          className={`text-xs ${mode === 'paragraph' ? 'text-primary' : 'text-white/40'}`}
        >
          全文对照
        </button>
      </div>

      {/* 模式内容 */}
      {mode === 'selection' ? (
        // 现有划词翻译 UI
        <SelectionTranslation selectedText={selectedText} ... />
      ) : (
        // 段落对照翻译 UI
        <ParagraphTranslation segments={segments} ... />
      )}
    </div>
  );
}
```

---

## 执行选项

**Plan complete and saved to `docs/plans/2026-03-23-paper-sense-making-integration-plan.md`.**

**Two execution options:**

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

**Which approach?**
