# 多源聚合论文搜索 - 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现多源聚合论文搜索，支持用户在主题级别配置多个渠道，并行搜索后合并去重展示

**Architecture:**
- 前端：GlobalChannelProvider 管理全局默认 + TopicChannelSelector 分组配置 + MultiSourceSearchBar 搜索 + SearchResultsList 展示
- 后端：search_multi API 并行多渠道 + suggest_channels 智能推荐 + ChannelWorkerPool 并行抓取 + Aggregator 合并去重
- 数据层：TopicQuota 主题配额 + PaperSource 论文来源追踪

**Tech Stack:** React 18 + TypeScript + FastAPI + SQLite + asyncio

---

## 实施阶段

### Phase 1: 前端基础架构

---

### Task 1: GlobalChannelProvider

**Files:**
- Create: `frontend/src/contexts/ChannelContext.tsx`
- Modify: `frontend/src/App.tsx` (添加 Provider)
- Test: `frontend/src/contexts/__tests__/ChannelContext.test.tsx`

**Step 1: 创建 GlobalChannelProvider**

```typescript
// frontend/src/contexts/ChannelContext.tsx
import { createContext, useContext, useState, useCallback, ReactNode } from 'react';

export interface Channel {
  id: string;
  name: string;
  description: string;
  isFree: boolean;
  cost?: string;
  category: 'general' | 'cs' | 'biomed' | 'preprint';
  status: 'available' | 'error' | 'rate_limited' | 'disabled';
  quota?: { used: number; limit: number };
}

interface ChannelContextValue {
  channels: Channel[];
  defaultChannels: string[];  // 默认: ['arxiv']
  getChannel: (id: string) => Channel | undefined;
  updateChannelStatus: (id: string, status: Channel['status']) => void;
  setDefaultChannels: (channels: string[]) => void;
}

const ChannelContext = createContext<ChannelContextValue | null>(null);

export function ChannelProvider({ children }: { children: ReactNode }) {
  const [channels, setChannels] = useState<Channel[]>(INITIAL_CHANNELS);
  const [defaultChannels, setDefaultChannels] = useState<string[]>(['arxiv']);

  const getChannel = useCallback((id: string) =>
    channels.find(c => c.id === id), [channels]);

  const updateChannelStatus = useCallback((id: string, status: Channel['status']) => {
    setChannels(prev => prev.map(c => c.id === id ? { ...c, status } : c));
  }, []);

  const setDefault = useCallback((ids: string[]) => {
    setDefaultChannels(ids);
    // TODO: 持久化到后端
  }, []);

  return (
    <ChannelContext.Provider value={{
      channels, defaultChannels, getChannel,
      updateChannelStatus, setDefaultChannels: setDefault
    }}>
      {children}
    </ChannelContext.Provider>
  );
}

export const useChannels = () => {
  const ctx = useContext(ChannelContext);
  if (!ctx) throw new Error('useChannels must be used within ChannelProvider');
  return ctx;
};

const INITIAL_CHANNELS: Channel[] = [
  { id: 'arxiv', name: 'ArXiv', description: '...', isFree: true, category: 'general', status: 'available' },
  { id: 'openalex', name: 'OpenAlex', description: '...', isFree: true, category: 'general', status: 'available' },
  { id: 'semantic_scholar', name: 'Semantic Scholar', description: '...', isFree: true, category: 'cs', status: 'available' },
  { id: 'dblp', name: 'DBLP', description: '...', isFree: true, category: 'cs', status: 'available' },
  { id: 'ieee', name: 'IEEE Xplore', description: '...', isFree: false, category: 'cs', status: 'available' },
  { id: 'biorxiv', name: 'bioRxiv', description: '...', isFree: true, category: 'preprint', status: 'available' },
];
```

**Step 2: 添加 Provider 到 App.tsx**

在 App.tsx 导入并包裹 Router:
```typescript
import { ChannelProvider } from '@/contexts/ChannelContext';

// 在 Router 外包裹
<ChannelProvider>
  <Router />
</ChannelProvider>
```

**Step 3: 提交**

```bash
git add frontend/src/contexts/ChannelContext.tsx frontend/src/App.tsx
git commit -m "feat(channel): add GlobalChannelProvider context"
```

---

### Task 2: TopicChannelSelector 分组折叠面板

**Files:**
- Modify: `frontend/src/components/topics/TopicChannelSelector.tsx`
- Test: `frontend/src/components/topics/__tests__/TopicChannelSelector.test.tsx`

**Step 1: 重写为分组折叠面板**

```tsx
// 分组结构
const CHANNEL_GROUPS = [
  { id: 'general', name: '通用搜索', channels: ['arxiv', 'openalex'] },
  { id: 'ai', name: 'AI/ML 增强', channels: ['semantic_scholar'] },
  { id: 'cs', name: 'CS 会议专用', channels: ['dblp'] },
  { id: 'paid', name: '付费渠道', channels: ['ieee'] },
  { id: 'preprint', name: '预印本', channels: ['biorxiv'] },
];

// 分组折叠组件
function ChannelGroup({ group, selected, onToggle, disabled }: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const groupChannels = useChannels().channels.filter(c => group.channels.includes(c.id));

  return (
    <div className="border rounded-lg">
      <button onClick={() => setCollapsed(!collapsed)} className="w-full flex items-center justify-between p-3">
        <span>{collapsed ? '▶' : '▼'} {group.name}</span>
        <span>{selected.filter(id => group.channels.includes(id)).length}/{groupChannels.length}</span>
      </button>
      {!collapsed && (
        <div className="p-3 pt-0 space-y-2">
          {groupChannels.map(channel => (
            <ChannelCard
              key={channel.id}
              channel={channel}
              selected={selected.includes(channel.id)}
              onToggle={() => onToggle(channel.id)}
              disabled={disabled}
            />
          ))}
        </div>
      )}
    </div>
  );
}
```

**Step 2: 提交**

```bash
git add frontend/src/components/topics/TopicChannelSelector.tsx
git commit -m "feat(ui): rewrite TopicChannelSelector as collapsible groups"
```

---

### Task 3: MultiSourceSearchBar

**Files:**
- Create: `frontend/src/components/search/MultiSourceSearchBar.tsx`
- Modify: `frontend/src/services/api.ts` (添加 suggest-channels)
- Test: `frontend/src/components/search/__tests__/MultiSourceSearchBar.test.tsx`

**Step 1: 创建搜索栏组件**

```tsx
function MultiSourceSearchBar({
  onSearch,
  loading
}: {
  onSearch: (query: string, channels: string[]) => void;
  loading: boolean;
}) {
  const [query, setQuery] = useState('');
  const [selectedChannels, setSelectedChannels] = useState<string[]>(['arxiv']);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const { channels } = useChannels();

  // 获取渠道推荐
  const fetchSuggestions = useCallback(async (q: string) => {
    if (!q.trim()) { setSuggestions([]); return; }
    const res = await api.get('/papers/suggest-channels', { query: q });
    setSuggestions(res.recommended || []);
  }, []);

  const handleSearch = () => {
    onSearch(query, selectedChannels);
  };

  return (
    <div className="space-y-3">
      {/* 搜索输入框 */}
      <div className="flex gap-2">
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="输入关键词，如 machine learning"
          className="flex-1 border rounded-lg px-4 py-2"
        />
        <button onClick={handleSearch} disabled={loading}>
          {loading ? '搜索中...' : '搜索'}
        </button>
      </div>

      {/* 推荐渠道提示 */}
      {suggestions.length > 0 && (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <span>推荐渠道:</span>
          {suggestions.map(id => (
            <span key={id} className="bg-blue-100 px-2 py-0.5 rounded">
              {channels.find(c => c.id === id)?.name}
            </span>
          ))}
        </div>
      )}

      {/* 渠道快捷选择 */}
      <ChannelQuickSelect
        selected={selectedChannels}
        onChange={setSelectedChannels}
      />
    </div>
  );
}
```

**Step 2: 提交**

```bash
git add frontend/src/components/search/MultiSourceSearchBar.tsx
git commit -m "feat(search): add MultiSourceSearchBar with channel suggestions"
```

---

### Task 4: SearchResultsList 合并结果列表

**Files:**
- Create: `frontend/src/components/search/SearchResultsList.tsx`
- Create: `frontend/src/components/search/PaperDetailDrawer.tsx`
- Test: `frontend/src/components/search/__tests__/SearchResultsList.test.tsx`

**Step 1: 创建结果列表组件**

```tsx
interface SearchResult {
  id: string;
  title: string;
  authors: string[];
  year: number;
  venue: string;
  citations?: number;
  abstract?: string;
  sources: { channel: string; externalId: string }[];
}

function SearchResultsList({
  results,
  loading,
  channelStats
}: {
  results: SearchResult[];
  loading: boolean;
  channelStats: Record<string, { total: number; new: number; error?: string }>;
}) {
  const [selectedPaper, setSelectedPaper] = useState<SearchResult | null>(null);
  const [filterChannel, setFilterChannel] = useState<string | null>(null);

  const filtered = filterChannel
    ? results.filter(p => p.sources.some(s => s.channel === filterChannel))
    : results;

  return (
    <div className="space-y-4">
      {/* 渠道统计 + 筛选 */}
      <div className="flex items-center gap-4">
        {Object.entries(channelStats).map(([ch, stat]) => (
          <div key={ch} className="text-sm">
            <span className="font-medium">{ch}:</span> {stat.total}
            {stat.error && <span className="text-red-500"> ({stat.error})</span>}
          </div>
        ))}
        <select
          value={filterChannel || ''}
          onChange={e => setFilterChannel(e.target.value || null)}
          className="ml-auto border rounded px-2 py-1"
        >
          <option value="">全部渠道</option>
          {Object.keys(channelStats).map(ch => (
            <option key={ch} value={ch}>{ch}</option>
          ))}
        </select>
      </div>

      {/* 结果列表 */}
      {loading ? (
        <div>加载中...</div>
      ) : (
        <div className="space-y-3">
          {filtered.map(paper => (
            <PaperCard
              key={paper.id}
              paper={paper}
              onClick={() => setSelectedPaper(paper)}
            />
          ))}
        </div>
      )}

      {/* 详情抽屉 */}
      {selectedPaper && (
        <PaperDetailDrawer
          paper={selectedPaper}
          onClose={() => setSelectedPaper(null)}
        />
      )}
    </div>
  );
}
```

**Step 2: 提交**

```bash
git add frontend/src/components/search/SearchResultsList.tsx
git commit -m "feat(search): add SearchResultsList with channel filtering"
```

---

### Phase 2: 后端多源搜索 API

---

### Task 5: search_multi API

**Files:**
- Modify: `apps/api/routers/papers.py`
- Create: `packages/integrations/aggregator.py`
- Test: `tests/test_search_multi.py`

**Step 1: 实现 Aggregator**

```python
# packages/integrations/aggregator.py
from dataclasses import dataclass
from typing import List
from .base import Paper

@dataclass
class AggregatedPaper:
    paper: Paper
    sources: List[dict]  # 各渠道元数据

class ResultAggregator:
    def __init__(self):
        self.results: List[AggregatedPaper] = []

    def add_results(self, channel: str, papers: List[Paper], metadata: dict):
        for paper in papers:
            existing = self._find_existing(paper)
            if existing:
                existing.sources.append({'channel': channel, **metadata})
            else:
                self.results.append(AggregatedPaper(
                    paper=paper,
                    sources=[{'channel': channel, **metadata}]
                ))

    def _find_existing(self, paper: Paper) -> AggregatedPaper | None:
        # 1. DOI 精确匹配
        for result in self.results:
            if result.paper.doi and paper.doi == result.paper.doi:
                return result
        # 2. Title 相似度匹配
        # ...
        return None

    def get_sorted_results(self) -> List[AggregatedPaper]:
        # 按相关性 + 新鲜度 + 渠道权重排序
        return sorted(self.results, key=lambda r: (
            -r.paper.relevance_score if r.paper.relevance_score else 0,
            -len(r.sources)  # 多源优先
        ))
```

**Step 2: 添加 search_multi 路由**

```python
@router.post("/papers/search-multi")
async def search_multi(
    query: str,
    channels: List[str] = ['arxiv'],
    max_results_per_channel: int = 50,
    topic_id: Optional[str] = None
):
    # 1. 检查 IEEE 配额
    quota_ok = await check_ieee_quota(topic_id, len(channels))
    if not quota_ok and 'ieee' in channels:
        channels.remove('ieee')

    # 2. 并行调用各渠道
    tasks = []
    for ch in channels:
        client = ChannelRegistry.get_client(ch)
        tasks.append(client.search(query, max_results=max_results_per_channel))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 3. 聚合结果
    aggregator = ResultAggregator()
    for ch, result in zip(channels, results):
        if isinstance(result, Exception):
            logger.error(f"Channel {ch} failed: {result}")
            continue
        aggregator.add_results(ch, result.papers, result.metadata)

    # 4. 返回
    return {
        'papers': aggregator.get_sorted_results(),
        'channel_stats': aggregator.get_stats()
    }
```

**Step 3: 提交**

```bash
git add packages/integrations/aggregator.py apps/api/routers/papers.py
git commit -m "feat(api): add search-multi endpoint with result aggregation"
```

---

### Task 6: suggest_channels API

**Files:**
- Modify: `apps/api/routers/papers.py`
- Create: `packages/worker/smart_router.py`
- Test: `tests/test_suggest_channels.py`

**Step 1: 实现 SmartRouter**

```python
# packages/worker/smart_router.py
from typing import List, Tuple

CHANNEL_KEYWORDS = {
    'arxiv': ['ml', 'machine learning', 'deep learning', 'neural', 'transformer', 'nlp', 'cv'],
    'semantic_scholar': ['ai', 'ml', 'citation', 'tldr', 'summary'],
    'dblp': ['nips', 'icml', 'cvpr', 'iccv', 'acl', 'emnlp', 'neurips', 'conference'],
    'ieee': ['ieee', 'signal processing', 'wireless', '5g', '6g', 'iot'],
    'biorxiv': ['crispr', 'gene', 'protein', 'biology', 'bioinformatics', 'neuroscience'],
    'openalex': ['*'],  # 全学科
}

def suggest_channels(query: str, available_channels: List[str]) -> Tuple[List[str], List[str], str]:
    """
    返回: (recommended, alternatives, reasoning)
    """
    query_lower = query.lower()
    recommended = []
    alternatives = []
    reasoning_parts = []

    for channel, keywords in CHANNEL_KEYWORDS.items():
        if channel not in available_channels:
            continue

        score = 0
        for kw in keywords:
            if kw == '*' or kw in query_lower:
                score += 1

        if score > 0:
            if score >= 2:
                recommended.append(channel)
                reasoning_parts.append(f"{channel} 匹配度高")
            else:
                alternatives.append(channel)

    # 确保至少有一个
    if not recommended and available_channels:
        recommended = ['arxiv']
        reasoning_parts.append("默认使用 arXiv")

    return recommended, alternatives, "; ".join(reasoning_parts)
```

**Step 2: 添加路由**

```python
@router.get("/papers/suggest-channels")
async def suggest_channels(query: str):
    from packages.worker.smart_router import suggest_channels

    # 获取可用的渠道
    available = ChannelRegistry.list_available()

    recommended, alternatives, reasoning = suggest_channels(query, available)

    return {
        'recommended': recommended,
        'alternatives': alternatives,
        'reasoning': reasoning
    }
```

**Step 3: 提交**

```bash
git add packages/worker/smart_router.py apps/api/routers/papers.py
git commit -m "feat(api): add suggest-channels endpoint for smart routing"
```

---

### Phase 3: Worker 重构

---

### Task 7: ChannelWorkerPool

**Files:**
- Create: `packages/worker/channel_pool.py`
- Modify: `apps/worker/daily_runner.py`
- Test: `tests/test_channel_pool.py`

**Step 1: 实现 ChannelWorkerPool**

```python
# packages/worker/channel_pool.py
import asyncio
from dataclasses import dataclass
from typing import List, Optional
from packages.integrations.registry import ChannelRegistry
from packages.integrations.aggregator import ResultAggregator

@dataclass
class ChannelResult:
    channel: str
    papers: List[Paper]
    metadata: dict
    error: Optional[str] = None

class ChannelWorkerPool:
    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)

    async def fetch_all(
        self,
        query: str,
        channels: List[str],
        max_per_channel: int = 50
    ) -> List[ChannelResult]:
        tasks = [
            self._fetch_channel(ch, query, max_per_channel)
            for ch in channels
        ]
        return await asyncio.gather(*tasks)

    async def _fetch_channel(
        self,
        channel: str,
        query: str,
        max_results: int
    ) -> ChannelResult:
        async with self.semaphore:
            try:
                client = ChannelRegistry.get_client(channel)
                result = await asyncio.wait_for(
                    client.search(query, max_results=max_results),
                    timeout=30.0
                )
                return ChannelResult(
                    channel=channel,
                    papers=result.papers,
                    metadata=result.metadata
                )
            except asyncio.TimeoutError:
                return ChannelResult(channel, [], {}, error="timeout")
            except Exception as e:
                return ChannelResult(channel, [], {}, error=str(e))
```

**Step 2: 集成到 daily_runner**

```python
# apps/worker/daily_runner.py
async def run_topic(topic: Topic, channels: List[str]):
    pool = ChannelWorkerPool(max_concurrent=3)

    results = await pool.fetch_all(
        query=topic.query,
        channels=channels,
        max_per_channel=topic.max_results_per_run
    )

    # 聚合
    aggregator = ResultAggregator()
    for result in results:
        if result.error:
            logger.warning(f"Channel {result.channel} failed: {result.error}")
            continue
        aggregator.add_results(result.channel, result.papers, result.metadata)

    # 去重入库
    await store_results(topic.id, aggregator.get_sorted_results())
```

**Step 3: 提交**

```bash
git add packages/worker/channel_pool.py apps/worker/daily_runner.py
git commit -m "feat(worker): add ChannelWorkerPool for parallel fetching"
```

---

### Task 8: QuotaManager

**Files:**
- Create: `packages/worker/quota_manager.py`
- Modify: `packages/storage/models.py`
- Test: `tests/test_quota_manager.py`

**Step 1: TopicQuota 模型**

```python
# packages/storage/models.py
class TopicQuota(Base):
    __tablename__ = 'topic_quotas'

    id = Column(UUID, primary_key=True, default=uuid4)
    topic_id = Column(UUID, ForeignKey('topics.id'), nullable=False)
    channel = Column(String, nullable=False)  # 'ieee'
    daily_limit = Column(Integer, default=50)
    daily_used = Column(Integer, default=0)
    last_reset_at = Column(DateTime, default=datetime.utcnow)

    @hybrid_property
    def remaining(self) -> int:
        return max(0, self.daily_limit - self.daily_used)

    def check_and_increment(self, count: int = 1) -> bool:
        """检查配额并预占，返回是否成功"""
        self._reset_if_needed()
        if self.remaining >= count:
            self.daily_used += count
            return True
        return False

    def _reset_if_needed(self):
        if (datetime.utcnow() - self.last_reset_at).days >= 1:
            self.daily_used = 0
            self.last_reset_at = datetime.utcnow()
```

**Step 2: QuotaManager**

```python
# packages/worker/quota_manager.py
class QuotaManager:
    def __init__(self, session):
        self.session = session

    async def check_quota(self, topic_id: str, channel: str, needed: int = 1) -> bool:
        if channel != 'ieee':
            return True  # 非 IEEE 渠道不需要配额检查

        quota = self.session.query(TopicQuota).filter_by(
            topic_id=topic_id, channel='ieee'
        ).first()

        if not quota:
            return True  # 没有配置配额限制，默认允许

        return quota.remaining >= needed

    async def reserve_quota(self, topic_id: str, channel: str, count: int) -> bool:
        if channel != 'ieee':
            return True

        quota = self.session.query(TopicQuota).filter_by(
            topic_id=topic_id, channel='ieee'
        ).first()

        if not quota:
            return True

        return quota.check_and_increment(count)
```

**Step 3: 提交**

```bash
git add packages/worker/quota_manager.py packages/storage/models.py
git commit -m "feat(quota): add TopicQuota model and QuotaManager"
```

---

### Phase 4: 完善体验 (P2)

---

### Task 9: PaperDetailDrawer 渠道元数据对比

**Files:**
- Modify: `frontend/src/components/search/SearchResultsList.tsx` (已在 Task 4 创建占位)
- Test: `frontend/src/components/search/__tests__/PaperDetailDrawer.test.tsx`

**Step 1: 完善 PaperDetailDrawer**

```tsx
function PaperDetailDrawer({ paper, onClose }: { paper: SearchResult, onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/50">
      <div className="absolute right-0 top-0 bottom-0 w-1/2 bg-white p-6 overflow-y-auto">
        <button onClick={onClose}>关闭</button>

        <h2 className="text-xl font-bold mt-4">{paper.title}</h2>

        {/* 渠道元数据对比表格 */}
        <table className="w-full mt-4 border">
          <thead>
            <tr>
              <th>渠道</th>
              <th>外部ID</th>
              <th>影响因子</th>
              <th>引用数</th>
              <th>特殊信息</th>
            </tr>
          </thead>
          <tbody>
            {paper.sources.map((src, i) => (
              <tr key={i}>
                <td>{src.channel}</td>
                <td className="font-mono text-sm">{src.externalId}</td>
                <td>{src.impactFactor || 'N/A'}</td>
                <td>{src.citations || 'N/A'}</td>
                <td>{src.tldr ? '✅ TL;DR' : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

**Step 2: 提交**

```bash
git add frontend/src/components/search/SearchResultsList.tsx
git commit -m "feat(search): add PaperDetailDrawer with channel metadata comparison"
```

---

## 实施顺序

1. **Task 1**: GlobalChannelProvider (前端基础)
2. **Task 2**: TopicChannelSelector 分组折叠
3. **Task 3**: MultiSourceSearchBar
4. **Task 4**: SearchResultsList
5. **Task 5**: search_multi API + Aggregator
6. **Task 6**: suggest_channels API + SmartRouter
7. **Task 7**: ChannelWorkerPool
8. **Task 8**: QuotaManager
9. **Task 9**: PaperDetailDrawer (P2)

---

## 执行选项

**1. Subagent-Driven (本会话)** - 我 dispatch 独立 subagent 执行每个任务，期间 review，快速迭代

**2. Parallel Session (新会话)** - 在新 session 中使用 executing-plans，批量执行带 checkpoint

你选哪个？
