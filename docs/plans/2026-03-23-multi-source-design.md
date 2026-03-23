# 多源聚合论文搜索 - 设计文档

**日期**: 2026-03-23
**状态**: 已批准
**版本**: v1.0

---

## 1. 背景

PaperMind 从单源（arXiv）扩展到多源聚合架构，支持 IEEE、OpenAlex、Semantic Scholar、DBLP、bioRxiv 等渠道。

### 目标
- 用户可在主题级别配置多个搜索渠道
- 全局默认 arxiv，减少用户升级痛点
- 智能路由推荐渠道，减少用户决策负担
- 并行聚合搜索，结果统一展示
- 支持按主题独立配置 IEEE 配额

---

## 2. 核心架构

### 2.1 前端架构

```
GlobalChannelProvider (Context)
├── 全局默认渠道配置
├── 渠道状态（可用/配额/错误）
└── 用户偏好学习

TopicChannelSelector (分组折叠面板)
├── 按类别分组：通用搜索 / AI增强 / CS会议 / 预印本
├── 默认启用 arxiv，其他关闭
└── 每个主题独立渠道配置

MultiSourceSearchBar
├── 关键词输入
├── 智能路由推荐渠道
└── 一键搜索多源

SearchResultsList
├── 合并去重列表
├── 来源标签
├── 按渠道筛选
└── PaperDetailDrawer (渠道元数据对比)
```

### 2.2 后端架构

```
POST /papers/search-multi
├── 并行调用各渠道
├── 合并去重
└── 返回聚合结果 + 各渠道元数据

GET /papers/suggest-channels
├── 根据关键词分析推荐渠道
└── 分析论文数量、领域匹配度

TopicQuota (主题配额管理)
├── 每主题独立 IEEE 配额
├── 配额消耗 / 重置逻辑
└── 配额用完后自动跳过
```

### 2.3 Worker 架构

```
TopicScheduler
├── 按主题独立调度
├── 协调多渠道任务
└── 失败重试 + 熔断

ChannelWorkerPool
├── 各渠道独立 Worker
├── 适配各自 API 特性
└── 返回统一 Paper 格式

QuotaManager
├── IEEE 配额：全局池 + 主题级子池
├── 配额预占 + 实际消耗
└── 配额用完自动切换备选渠道

Aggregator
├── 接收各渠道结果
├── 去重（DOI / Title 相似度）
├── 优先级排序
└── 入库
```

---

## 3. 组件清单

### P1 - 必须实现

| 组件 | 文件位置 | 描述 |
|------|----------|------|
| GlobalChannelProvider | `frontend/src/contexts/ChannelContext.tsx` | 全局渠道上下文 |
| TopicChannelSelector | `frontend/src/components/topics/TopicChannelSelector.tsx` | 分组折叠面板 |
| MultiSourceSearchBar | `frontend/src/components/search/MultiSourceSearchBar.tsx` | 搜索框 + 推荐 |
| SearchResultsList | `frontend/src/components/search/SearchResultsList.tsx` | 合并结果列表 |
| search_multi API | `apps/api/routers/papers.py` | 多源搜索接口 |
| suggest_channels API | `apps/api/routers/papers.py` | 渠道推荐接口 |
| TopicQuota model | `packages/storage/models.py` | 主题配额模型 |
| ChannelWorkerPool | `packages/worker/channel_pool.py` | 渠道 Worker 池 |
| Aggregator | `packages/worker/aggregator.py` | 结果聚合器 |

### P2 - 后续迭代

| 组件 | 文件位置 | 描述 |
|------|----------|------|
| PaperDetailDrawer | `frontend/src/components/search/PaperDetailDrawer.tsx` | 论文详情 + 渠道对比 |
| ChannelStatusBadge | `frontend/src/components/ui/Badge.tsx` | 渠道状态标签 |
| QuotaSettingPanel | `frontend/src/components/topics/QuotaSettingPanel.tsx` | 主题级配额配置 |
| QuotaManager | `packages/worker/quota_manager.py` | 配额管理器 |
| SmartRouter | `packages/worker/smart_router.py` | 智能路由引擎 |

---

## 4. 数据模型

### 4.1 TopicChannelConfig

```typescript
interface TopicChannelConfig {
  topic_id: string;
  channels: string[];           // 默认: ['arxiv']
  channel_configs: {
    [channel: string]: {
      enabled: boolean;
      daily_quota?: number;      // IEEE 专用
      max_results_per_run?: number;
    }
  };
  use_global_default: boolean;   // 是否使用全局默认
}
```

### 4.2 TopicQuota

```python
class TopicQuota(Base):
  topic_id: UUID
  channel: str                  # 'ieee'
  daily_limit: int             # 每日限制
  daily_used: int               # 今日已用
  last_reset_at: datetime      # 上次重置时间
```

### 4.3 PaperSource

```python
class PaperSource(Base):
  paper_id: UUID
  channel: str                 # 'arxiv', 'ieee', 'openalex'
  external_id: str             # 渠道返回的原始 ID
  fetched_at: datetime
  channel_metadata: dict       # 渠道特定元数据
```

---

## 5. API 设计

### 5.1 多源搜索

```
POST /papers/search-multi
Body: {
  query: string,
  channels: string[],           // 默认: ['arxiv']
  max_results_per_channel: int, // 默认: 50
  topic_id?: string             // 用于配额检查
}
Response: {
  papers: Paper[],
  channel_stats: {
    [channel: string]: {
      total: number,
      new: number,
      duplicates: number,
      error?: string
    }
  }
}
```

### 5.2 渠道推荐

```
GET /papers/suggest-channels?query={query}
Response: {
  recommended: string[],
  alternatives: string[],
  reasoning: string
}
```

### 5.3 主题渠道配置

```
GET /topics/{topic_id}/channels
PUT /topics/{topic_id}/channels
Body: TopicChannelConfig
```

---

## 6. 智能路由策略

```
关键词 → 领域检测 → 渠道推荐

规则库：
- "machine learning", "neural network", "transformer" → [arxiv, semantic_scholar, openalex]
- "NeurIPS", "ICML", "CVPR", "ACL" → [dblp, arxiv]
- "CRISPR", "gene editing", "protein" → [biorxiv, openalex]
- "IEEE", "5G", "standard" → [ieee]
- 默认 → [arxiv]

动态调整：
- 如果某渠道最近失败，降级推荐
- 如果 IEEE 配额不足，移除推荐
```

---

## 7. Worker 流程

### 7.1 主题调度流程

```
1. TopicScheduler 触发（时间到了 OR 用户手动）
2. ChannelRouter 分析关键词，决定渠道列表
3. IEEE 配额检查，不足则移除
4. 并行启动各 ChannelWorker
5. Aggregator 收集结果并去重
6. 入库 + 更新主题最后抓取时间
```

### 7.2 并行策略

```
- 各渠道 Worker 独立运行，互不阻塞
- 使用 asyncio 并发调度
- 设置单渠道超时（30s），超时后标记失败继续其他
- 全部失败时告警
```

### 7.3 去重策略

```
1. DOI 精确匹配
2. Title 模糊匹配（相似度 > 0.9）
3. 多渠道同论文：保留相关性最高的，标记其他来源
```

---

## 8. 视觉设计

### 8.1 分组折叠面板

```
▼ 通用搜索
  ☑ arxiv
  ☐ openalex

▼ AI/ML 增强
  ☐ semantic_scholar

▼ CS 会议专用
  ☐ dblp

▼ 付费渠道
  ☐ IEEE (需配置配额)

▼ 预印本
  ☐ bioRxiv
```

### 8.2 搜索结果列表

```
┌─────────────────────────────────────────────────────────────┐
│ [搜索: machine learning] [推荐渠道] [arxiv ✓] [openalex ✓] │
├─────────────────────────────────────────────────────────────┤
│ Attention Is All You Need                    [arXiv] ⭐ 5.2k│
│ Vaswani et al. · 2017 · NeurIPS                             │
│ ─────────────────────────────────────────────────────────── │
│ Deep Residual Learning                          [OpenAlex] ⭐ 3.8k│
│ He et al. · 2016 · CVPR                                     │
└─────────────────────────────────────────────────────────────┘
```

### 8.3 论文详情抽屉

```
┌─────────────────────────────────────────────────────────────┐
│ Attention Is All You Need                          [arXiv]  │
├─────────────────────────────────────────────────────────────┤
│ 📄 基本信息                                                 │
│    作者: Vaswani et al.                                     │
│    年份: 2017                                               │
│    会议: NeurIPS                                            │
│                                                             │
│ 🔗 渠道元数据对比                                           │
│ ┌─────────────┬────────────────┬────────────────┐        │
│ │ arXiv        │ OpenAlex       │ Semantic Scholar│        │
│ ├─────────────┼────────────────┼────────────────┤        │
│ │ ID: 1706... │ DOI: 10.48... │ Cited: 95k     │        │
│ │ IF: N/A     │ IF: 38.9      │ TL;DR: ✓       │        │
│ └─────────────┴────────────────┴────────────────┘        │
└─────────────────────────────────────────────────────────────┘
```

---

## 9. 实施计划

### Phase 1: 前端基础 (P1)
- [ ] GlobalChannelProvider
- [ ] TopicChannelSelector (分组折叠)
- [ ] 前端多渠道配置 API 对接

### Phase 2: 后端多源搜索 (P1)
- [ ] search_multi API
- [ ] suggest_channels API
- [ ] 现有 Channel 适配器对接

### Phase 3: Worker 重构 (P1)
- [ ] ChannelWorkerPool
- [ ] Aggregator
- [ ] 主题调度集成

### Phase 4: 完善体验 (P2)
- [ ] PaperDetailDrawer
- [ ] 渠道状态监控
- [ ] 配额管理 UI

---

## 10. 风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| IEEE API 不稳定 | 搜索失败 | 降级到 OpenAlex，自动重试 |
| 语义 Scholar 限流 | 配额耗尽 | 排队等待，缓存结果 |
| 多渠道去重不准 | 重复论文 | DOI 精确 + Title 模糊双重校验 |
| Worker 并发过高 | API 被封 | 全局并发限制，队列缓冲 |

---

## 11. 附录

### 渠道特性

| 渠道 | API 限制 | 认证 | 特点 |
|------|----------|------|------|
| arXiv | 无 | 无 | 免费、开放、预印本为主 |
| IEEE | 50次/天(免费) | API Key | 正式出版物，质量高 |
| OpenAlex | 10次/秒 | Email | 全学科，2.5亿+ |
| Semantic Scholar | 100次/5分钟 | API Key (可选) | AI 增强，有 TL;DR |
| DBLP | 无明确限制 | 无 | CS 会议权威 |
| bioRxiv | 无明确限制 | 无 | 预印本，最新研究 |
