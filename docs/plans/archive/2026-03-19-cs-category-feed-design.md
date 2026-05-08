# CS 分类订阅功能设计

## 概述

新增独立的 CS 分类订阅系统，用户可直接订阅 arXiv CS 下的细分领域（如 cs.CV、cs.LG），系统定时抓取最新论文入库。与现有的关键词主题订阅完全独立，UI 整合在 Topics 页面内通过 Tab 切换。

---

## 数据模型

### CSCategory（arXiv 分类缓存）

```python
class CSCategory(Base):
    code: str          # "cs.CV"
    name: str          # "Computer Vision and Pattern Recognition"
    description: str   # "Covers image processing, computer vision, pattern recognition etc."
    cached_at: datetime  # 缓存时间，30 天后失效需刷新
```

来源：启动时从 arXiv API `https://arxiv.org/api/categories` 动态拉取，存入 DB，30 天更新一次。

### CSFeedSubscription（用户订阅记录）

```python
class CSFeedSubscription(Base):
    id: UUID
    category_code: str          # "cs.CV"
    user_id: str | None         # 预留，多用户时区分；当前单用户可写死
    daily_limit: int            # 每日配额（篇数）
    enabled: bool               # 是否启用
    status: str                 # "active" | "cool_down" | "paused"
    cool_down_until: datetime    # 熔断冷却截止时间
    last_run_at: datetime | None
    last_run_count: int         # 上次入库数量
    created_at: datetime
```

与 `TopicSubscription` 完全独立，不共用表。

---

## 调度服务

### CSFeedOrchestrator

协调所有分类订阅的定时抓取，复用现有 Worker 的 APScheduler 调度框架。

#### 调度策略

- 触发频率：每小时整点执行一次（与主题订阅调度共用 Worker）
- 全局请求控制：每分钟最多 20 个 arXiv API 请求（token bucket 模式）
- 请求间隔：每个分类请求之间至少间隔 3 秒
- 每日配额：用户设的 daily_limit 精确控制，精确到每个分类的每日已入库计数

#### 处理流程

```
每小时触发 CSFeedOrchestrator.run()
         ↓
1. 加载所有 enabled=True 的 CSFeedSubscription
         ↓
2. 遍历每个订阅（按 category_code 字母序）：
   ┌─────────────────────────────────────────┐
   │ 检查 status == "cool_down"              │
   │   → 当前时间 < cool_down_until → 跳过    │
   ├─────────────────────────────────────────┤
   │ 计算今日已入库数量                       │
   │   → 今日已入库 >= daily_limit → 跳过     │
   ├─────────────────────────────────────────┤
   │ 检查全局 token bucket                    │
   │   → 桶已满 → 等到下一分钟或下一小时       │
   ├─────────────────────────────────────────┤
   │ 调用 ArxivClient.fetch_latest(           │
   │   query=f"cat:{category_code}",          │
   │   max_results=剩余配额,                   │
   │   days_back=7                            │
   │ )                                        │
   ├─────────────────────────────────────────┤
   │ 成功 → upsert → 记录 CollectionAction    │
   │ 触发 429 → status="cool_down",           │
   │         cool_down_until=now+30min        │
   │ 其他错误 → 记录日志，跳过该分类           │
   └─────────────────────────────────────────┘
         ↓
3. 全部处理完 → 记录本次执行摘要日志
```

#### 熔断机制

- 触发条件：arXiv 返回 429 Too Many Requests
- 冷却时间：30 分钟（cool_down_until = now + 30min）
- 恢复条件：冷却时间结束后自动恢复为 "active"

---

## API 设计

### GET /cs-categories

返回 arXiv CS 全部分类列表（供 UI 勾选用）。

```
Response:
{
  "categories": [
    {
      "code": "cs.CV",
      "name": "Computer Vision and Pattern Recognition",
      "description": "Covers image processing, computer vision, pattern recognition..."
    },
    ...
  ],
  "updated_at": "2026-03-19T10:00:00Z"
}
```

### GET /cs-feeds

返回当前用户的分类订阅列表。

```
Response:
{
  "feeds": [
    {
      "id": "uuid",
      "category_code": "cs.CV",
      "category_name": "Computer Vision and Pattern Recognition",
      "daily_limit": 30,
      "enabled": true,
      "status": "active",
      "last_run_at": "2026-03-19T08:00:00Z",
      "last_run_count": 25
    }
  ]
}
```

### POST /cs-feeds

批量订阅分类。

```
Body:
{
  "category_codes": ["cs.CV", "cs.LG"],
  "daily_limit": 50,
  "enabled": true
}

Response:
{
  "created": 2,
  "feeds": [...]
}
```

### DELETE /cs-feeds/{id}

取消订阅。

### POST /cs-feeds/{id}/trigger

手动触发一次抓取（立即执行，跳过定时）。

---

## 前端 UI

### 页面结构

在 `/topics` 页面内新增 Tab：

```
[主题订阅] [分类订阅]
```

### 分类订阅 Tab 布局

```
┌─────────────────────────────────────────────────────────┐
│  arXiv CS 分类订阅                                       │
│  ─────────────────────────────────────────────────────  │
│  全局每日配额：[  50  ] 篇                               │
│                                                         │
│  ┌─────────────────┐  ┌──────────────────────────────┐  │
│  │ 分类列表（左侧） │  │ 已订阅列表（右侧）           │  │
│  │                 │  │                              │  │
│  │ 🔍 搜索分类      │  │ cs.CV          30篇/天  [x]  │  │
│  │                 │  │ cs.LG          50篇/天  [x]  │  │
│  │ ☑ cs.CV (CV)    │  │ cs.CL          20篇/天  [x]  │  │
│  │ ☑ cs.LG (LG)    │  │                              │  │
│  │ ☐ cs.CL (CL)    │  │ 状态: 运行中 / 3个分类        │  │
│  │ ☐ cs.AI (AI)    │  │                              │  │
│  │ ☐ cs.RO (RO)    │  │ [保存配置]                    │  │
│  │ ...             │  │                              │  │
│  └─────────────────┘  └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

- 左侧：可搜索的分类列表，带复选框
- 右侧：已勾选的分类 + 各自配额（可编辑）+ 删除按钮
- 底部：保存配置按钮

### 分类来源

调用 `GET /cs-categories` 获取分类列表，缓存 30 天。

---

## 文件变更

### 后端新增

| 文件 | 说明 |
|------|------|
| `packages/storage/models.py` | 新增 `CSCategory`、`CSFeedSubscription` 模型 |
| `packages/storage/repositories.py` | 新增 `CSFeedRepository` |
| `packages/integrations/arxiv_client.py` | 新增 `fetch_categories()` 方法 |
| `packages/ai/cs_feed_orchestrator.py` | 新增 `CSFeedOrchestrator` 调度服务 |
| `apps/api/routers/cs_feeds.py` | 新增分类订阅 REST API |
| `apps/worker/main.py` | 注册 `CSFeedOrchestrator` 调度任务 |

### 后端修改

| 文件 | 说明 |
|------|------|
| `apps/api/main.py` | 注册 `cs_feeds` router |
| `packages/storage/repositories.py` | `BaseQuery` 可复用 |

### 前端新增

| 文件 | 说明 |
|------|------|
| `frontend/src/pages/CSFeeds.tsx` | 分类订阅 Tab 页面 |
| `frontend/src/services/api.ts` | 新增 `csFeedApi` |

### 前端修改

| 文件 | 说明 |
|------|------|
| `frontend/src/pages/Topics.tsx` | 新增 Tab 切换 + `<CSFeeds />` 组件 |
| `frontend/src/components/Sidebar.tsx` | 如需要可添加分类订阅入口 |

---

## 实现顺序

1. **后端基础** — 数据模型 + 分类获取 + Repository
2. **后端 API** — REST 接口
3. **调度服务** — Orchestrator（含限流 + 熔断）
4. **前端 UI** — Tab + 分类列表 + 订阅管理
5. **集成测试** — 手动触发 + 观察限流行为
