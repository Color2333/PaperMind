# CS 分类订阅功能实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 新增独立的 arXiv CS 分类订阅系统，用户可订阅分类并控制每日配额，系统自动调度抓取

**Architecture:** 新增 `CSCategory` + `CSFeedSubscription` 数据模型，独立于 TopicSubscription；新增 `CSFeedOrchestrator` 调度服务管理限流和熔断；REST API 挂载在 `/cs-categories` 和 `/cs-feeds`；前端在 Topics 页面内新增 Tab

**Tech Stack:** FastAPI + SQLite + APScheduler + React

---

## Phase 1: 数据模型

### Task 1: 新增 CSCategory 和 CSFeedSubscription 模型

**Files:**
- Modify: `packages/storage/models.py`
- Reference: `packages/storage/models.py:189-209` (TopicSubscription 作为参考)

**Step 1: 添加 CSCategory 模型**

在 `models.py` 末尾添加：

```python
class CSCategory(Base):
    __tablename__ = "cs_categories"

    code: str = Field(primary_key)  # "cs.CV"
    name: str = Field(nullable=False)
    description: str = Field(default="")
    cached_at: datetime = Field(default_factory=datetime.utcnow)


class CSFeedSubscription(Base):
    __tablename__ = "cs_feed_subscriptions"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    category_code: str = Field(nullable=False)
    daily_limit: int = Field(default=30)
    enabled: bool = Field(default=True)
    status: str = Field(default="active")  # active | cool_down | paused
    cool_down_until: datetime | None = Field(default=None)
    last_run_at: datetime | None = Field(default=None)
    last_run_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**Step 2: 验证模型可导入**

Run: `cd /Users/haojiang/Documents/2026/PaperMind && python -c "from packages.storage.models import CSCategory, CSFeedSubscription; print('OK')"`

---

### Task 2: 新增 CSFeedRepository

**Files:**
- Modify: `packages/storage/repositories.py`
- Reference: `packages/storage/repositories.py:964-1062` (TopicRepository 作为参考)

**Step 1: 在 repositories.py 添加 CSFeedRepository**

在文件末尾添加：

```python
class CSFeedRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_categories(self) -> list[CSCategory]:
        return list(self.session.execute(select(CSCategory)).scalars())

    def upsert_category(self, code: str, name: str, description: str = "") -> CSCategory:
        existing = self.session.execute(select(CSCategory).where(CSCategory.code == code)).scalar_one_or_none()
        if existing:
            existing.name = name
            existing.description = description
            existing.cached_at = datetime.utcnow()
            return existing
        cat = CSCategory(code=code, name=name, description=description)
        self.session.add(cat)
        self.session.commit()
        return cat

    def get_subscriptions(self) -> list[CSFeedSubscription]:
        return list(self.session.execute(select(CSFeedSubscription)).scalars())

    def get_subscription(self, category_code: str) -> CSFeedSubscription | None:
        return self.session.execute(
            select(CSFeedSubscription).where(CSFeedSubscription.category_code == category_code)
        ).scalar_one_or_none()

    def upsert_subscription(self, category_code: str, daily_limit: int, enabled: bool = True) -> CSFeedSubscription:
        existing = self.get_subscription(category_code)
        if existing:
            existing.daily_limit = daily_limit
            existing.enabled = enabled
            self.session.commit()
            return existing
        sub = CSFeedSubscription(category_code=category_code, daily_limit=daily_limit, enabled=enabled)
        self.session.add(sub)
        self.session.commit()
        return sub

    def delete_subscription(self, category_code: str) -> bool:
        sub = self.get_subscription(category_code)
        if sub:
            self.session.delete(sub)
            self.session.commit()
            return True
        return False

    def update_run_status(self, category_code: str, count: int):
        sub = self.get_subscription(category_code)
        if sub:
            sub.last_run_at = datetime.utcnow()
            sub.last_run_count = count
            sub.status = "active"
            self.session.commit()

    def set_cool_down(self, category_code: str, until: datetime):
        sub = self.get_subscription(category_code)
        if sub:
            sub.status = "cool_down"
            sub.cool_down_until = until
            self.session.commit()

    def get_active_subscriptions(self) -> list[CSFeedSubscription]:
        return list(self.session.execute(
            select(CSFeedSubscription).where(CSFeedSubscription.enabled == True)
        ).scalars())
```

**Step 2: 验证 repository 可导入**

Run: `cd /Users/haojiang/Documents/2026/PaperMind && python -c "from packages.storage.repositories import CSFeedRepository; print('OK')"`

---

## Phase 2: arXiv 分类获取

### Task 3: arxiv_client 新增 fetch_categories

**Files:**
- Modify: `packages/integrations/arxiv_client.py`
- Reference: `packages/integrations/arxiv_client.py:58-117` (fetch_latest 作为参考)

**Step 1: 添加 fetch_categories 方法**

在 `ArxivClient` 类中添加：

```python
def fetch_categories(self) -> list[dict]:
    """从 arXiv API 获取 CS 分类列表"""
    url = "https://arxiv.org/api/categories"
    acquire_api("arxiv", timeout=30)
    response = self.client.get(url, timeout=30)
    response.raise_for_status()
    root = ElementTree.fromstring(response.text)
    categories = []
    for cat in root.findall("category"):
        code = cat.find("code").text or ""
        if code.startswith("cs."):
            categories.append({
                "code": code,
                "name": cat.find("name").text or "",
                "description": cat.find("description").text or "",
            })
    return categories
```

**Step 2: 验证方法可调用**

Run: `cd /Users/haojiang/Documents/2026/PaperMind && python -c "from packages.integrations.arxiv_client import ArxivClient; print(ArxivClient().fetch_categories()[:3])"`

---

## Phase 3: REST API

### Task 4: 新增 cs_feeds router

**Files:**
- Create: `apps/api/routers/cs_feeds.py`
- Reference: `apps/api/routers/topics.py` (作为 API 风格参考)

**Step 1: 编写 API 路由**

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from packages.storage.repositories import CSFeedRepository
from packages.integrations.arxiv_client import ArxivClient

router = APIRouter(prefix="/cs", tags=["cs-feeds"])


class CategoryInfo(BaseModel):
    code: str
    name: str
    description: str


class CSFeedItem(BaseModel):
    category_code: str
    category_name: str
    daily_limit: int
    enabled: bool
    status: str
    last_run_at: str | None
    last_run_count: int


class SubscribeRequest(BaseModel):
    category_codes: list[str]
    daily_limit: int = 30
    enabled: bool = True


def get_repo():
    from packages.storage.database import SessionLocal
    session = SessionLocal()
    try:
        yield CSFeedRepository(session)
    finally:
        session.close()


@router.get("/categories")
def list_categories(repo: CSFeedRepository = Depends(get_repo)):
    categories = repo.get_categories()
    return {"categories": [CategoryInfo.model_validate(c).__dict__ for c in categories]}


@router.get("/feeds")
def list_feeds(repo: CSFeedRepository = Depends(get_repo)):
    feeds = repo.get_subscriptions()
    categories = {c.code: c.name for c in repo.get_categories()}
    return {
        "feeds": [
            {
                "category_code": f.category_code,
                "category_name": categories.get(f.category_code, f.category_code),
                "daily_limit": f.daily_limit,
                "enabled": f.enabled,
                "status": f.status,
                "last_run_at": f.last_run_at.isoformat() if f.last_run_at else None,
                "last_run_count": f.last_run_count,
            }
            for f in feeds
        ]
    }


@router.post("/feeds")
def subscribe(req: SubscribeRequest, repo: CSFeedRepository = Depends(get_repo)):
    created = []
    for code in req.category_codes:
        sub = repo.upsert_subscription(code, req.daily_limit, req.enabled)
        created.append({
            "category_code": sub.category_code,
            "daily_limit": sub.daily_limit,
            "enabled": sub.enabled,
        })
    return {"created": len(created), "feeds": created}


@router.delete("/feeds/{category_code}")
def unsubscribe(category_code: str, repo: CSFeedRepository = Depends(get_repo)):
    deleted = repo.delete_subscription(category_code)
    return {"deleted": deleted}
```

**Step 2: 注册 router**

Modify `apps/api/main.py`，在 `app.include_router(topics.router)` 后添加：

```python
from apps.api.routers import cs_feeds
app.include_router(cs_feeds.router)
```

---

## Phase 4: 调度服务

### Task 5: 新增 CSFeedOrchestrator

**Files:**
- Create: `packages/ai/cs_feed_orchestrator.py`
- Reference: `packages/ai/daily_runner.py:119-287` (run_topic_ingest 作为参考)

**Step 1: 编写 Orchestrator**

```python
from datetime import datetime, timedelta
import threading
import time
import logging

from packages.integrations.arxiv_client import ArxivClient
from packages.storage.database import SessionLocal
from packages.storage.repositories import CSFeedRepository

logger = logging.getLogger(__name__)

TOKEN_BUCKET_SIZE = 20      # 每分钟最多 20 请求
TOKEN_FILL_RATE = 20        # 每分钟补充 20 个 token
REQUEST_INTERVAL = 3        # 每请求间隔 3 秒
COOL_DOWN_MINUTES = 30      # 熔断冷却时间


class TokenBucket:
    def __init__(self, size: int, fill_rate: int):
        self.size = size
        self.tokens = size
        self.fill_rate = fill_rate
        self.last_refill = time.time()
        self.lock = threading.Lock()

    def acquire(self, timeout: float = 60) -> bool:
        while True:
            with self.lock:
                self._refill()
                if self.tokens >= 1:
                    self.tokens -= 1
                    return True
            if time.time() - self.last_refill > timeout:
                return False
            time.sleep(1)

    def _refill(self):
        now = time.time()
        elapsed = now - self.last_refill
        new_tokens = elapsed * (self.fill_rate / 60)
        self.tokens = min(self.size, self.tokens + new_tokens)
        self.last_refill = now


class CSFeedOrchestrator:
    def __init__(self):
        self.bucket = TokenBucket(TOKEN_BUCKET_SIZE, TOKEN_FILL_RATE)

    def sync_categories(self):
        """从 arXiv 拉取分类并写入 DB"""
        client = ArxivClient()
        cats = client.fetch_categories()
        repo = CSFeedRepository(SessionLocal())
        for c in cats:
            repo.upsert_category(c["code"], c["name"], c.get("description", ""))
        logger.info("[CSFeed] Synced %d categories", len(cats))

    def run(self):
        """每小时执行一次"""
        repo = CSFeedRepository(SessionLocal())
        subs = repo.get_active_subscriptions()

        for sub in subs:
            now = datetime.utcnow()

            # 冷却中检查
            if sub.status == "cool_down" and sub.cool_down_until:
                if now < sub.cool_down_until:
                    logger.info("[CSFeed] Skipping %s (cool down until %s)", sub.category_code, sub.cool_down_until)
                    continue

            # 每日配额检查
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            if sub.last_run_at and sub.last_run_at >= today_start:
                remaining = sub.daily_limit - sub.last_run_count
            else:
                remaining = sub.daily_limit

            if remaining <= 0:
                logger.info("[CSFeed] Skipping %s (daily limit reached)", sub.category_code)
                continue

            # 请求间隔
            if not self.bucket.acquire(timeout=30):
                logger.warning("[CSFeed] Token bucket timeout, skipping %s", sub.category_code)
                continue
            time.sleep(REQUEST_INTERVAL)

            # 抓取
            try:
                client = ArxivClient()
                papers = client.fetch_latest(
                    query=f"cat:{sub.category_code}",
                    max_results=remaining,
                    days_back=7,
                )
                # upsert papers (复用现有逻辑)
                from packages.storage.repositories import PaperRepository
                paper_repo = PaperRepository(SessionLocal())
                count = 0
                for p in papers:
                    paper_repo.upsert_paper(p)
                    count += 1

                repo.update_run_status(sub.category_code, count)
                logger.info("[CSFeed] %s: ingested %d papers", sub.category_code, count)

            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "Too Many Requests" in err_str:
                    repo.set_cool_down(sub.category_code, now + timedelta(minutes=COOL_DOWN_MINUTES))
                    logger.warning("[CSFeed] Rate limited %s, cool down 30min", sub.category_code)
                else:
                    logger.error("[CSFeed] Error fetching %s: %s", sub.category_code, e)
```

**Step 2: 注册定时任务**

Modify `apps/worker/main.py`，在 `topic_dispatch_job` 旁边添加：

```python
from packages.ai.cs_feed_orchestrator import CSFeedOrchestrator

cs_orchestrator = CSFeedOrchestrator()

def cs_feed_dispatch_job():
    """每小时同步分类 + 执行订阅抓取"""
    cs_orchestrator.sync_categories()
    cs_orchestrator.run()
```

并在 APScheduler 注册：

```python
scheduler.add_job(cs_feed_dispatch_job, "cron", minute=0, id="cs_feed_dispatch")
```

---

## Phase 5: 前端 UI

### Task 6: 新增 CSFeeds 前端页面

**Files:**
- Create: `frontend/src/pages/CSFeeds.tsx`
- Reference: `frontend/src/pages/Topics.tsx` (作为 UI 风格参考)

**Step 1: 编写 CSFeeds 页面组件**

```tsx
import { useEffect, useState } from "react";
import { Loader2, RefreshCw, CheckCircle2, XCircle, Search } from "lucide-react";
import { topicApi } from "@/services/api";

interface CSCategory {
  code: string;
  name: string;
  description: string;
}

interface CSFeed {
  category_code: string;
  category_name: string;
  daily_limit: number;
  enabled: boolean;
  status: string;
  last_run_at: string | null;
  last_run_count: number;
}

const ARXIV_CS_PREFIXES = [
  "cs.CV", "cs.LG", "cs.CL", "cs.AI", "cs.NE", "cs.CR", "cs.DB",
  "cs.DC", "cs.DL", "cs.DM", "cs.DS", "cs.ET", "cs.FL", "cs.GL",
  "cs.GR", "cs.GT", "cs.HC", "cs.IR", "cs.IT", "cs.LO", "cs.MA",
  "cs.MM", "cs.MS", "cs.NA", "cs.NI", "cs.OH", "cs.OS", "cs.PL",
  "cs.RO", "cs.SC", "cs.SD", "cs.SE", "cs.SI", "cs.SY",
];

export default function CSFeeds() {
  const [categories, setCategories] = useState<CSCategory[]>([]);
  const [feeds, setFeeds] = useState<CSFeed[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [globalLimit, setGlobalLimit] = useState(30);
  const [saving, setSaving] = useState(false);

  async function loadData() {
    setLoading(true);
    try {
      const [catRes, feedRes] = await Promise.all([
        topicApi.csCategories(),
        topicApi.csFeeds(),
      ]);
      setCategories(catRes.categories || []);
      setFeeds(feedRes.feeds || []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadData(); }, []);

  const subscribedCodes = new Set(feeds.map(f => f.category_code));
  const filtered = categories.filter(c =>
    c.code.toLowerCase().includes(search.toLowerCase()) ||
    c.name.toLowerCase().includes(search.toLowerCase())
  );

  async function toggleCategory(code: string) {
    if (subscribedCodes.has(code)) {
      await topicApi.csFeedDelete(code);
    } else {
      await topicApi.csFeedCreate({ category_codes: [code], daily_limit: globalLimit });
    }
    await loadData();
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="animate-fade-in space-y-6">
      <div className="page-hero rounded-2xl p-6">
        <h1 className="text-2xl font-bold text-ink">arXiv CS 分类订阅</h1>
        <p className="mt-0.5 text-sm text-ink-secondary">订阅 CS 细分领域，自动抓取最新论文</p>
      </div>

      <div className="flex items-center gap-3 bg-card rounded-xl border p-4">
        <label className="text-sm font-medium">全局每日配额</label>
        <input
          type="number"
          value={globalLimit}
          onChange={e => setGlobalLimit(Number(e.target.value))}
          className="w-20 rounded-lg border bg-background px-3 py-1.5 text-sm"
          min={1}
          max={200}
        />
        <span className="text-sm text-muted-foreground">篇/分类/天</span>
        <button
          onClick={loadData}
          className="ml-auto flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
        >
          <RefreshCw className="w-4 h-4" />
          刷新
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-card rounded-xl border p-4">
          <div className="flex items-center gap-2 mb-4">
            <Search className="w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              placeholder="搜索分类..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="flex-1 rounded-lg border bg-background px-3 py-1.5 text-sm"
            />
          </div>
          <div className="space-y-1 max-h-96 overflow-y-auto">
            {filtered.slice(0, 40).map(c => (
              <label
                key={c.code}
                className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-muted cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={subscribedCodes.has(c.code)}
                  onChange={() => toggleCategory(c.code)}
                  className="rounded"
                />
                <span className="text-sm font-mono w-16 shrink-0">{c.code}</span>
                <span className="text-sm truncate flex-1">{c.name}</span>
              </label>
            ))}
          </div>
        </div>

        <div className="bg-card rounded-xl border p-4">
          <h3 className="font-semibold mb-4">已订阅 ({feeds.length} 个分类)</h3>
          {feeds.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">左侧勾选要订阅的分类</p>
          ) : (
            <div className="space-y-3 max-h-96 overflow-y-auto">
              {feeds.map(f => (
                <div key={f.category_code} className="flex items-center gap-3 p-3 rounded-lg bg-muted/50">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-mono font-medium">{f.category_code}</span>
                      <span className={`text-xs px-2 py-0.5 rounded-full ${
                        f.status === "active" ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" :
                        f.status === "cool_down" ? "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400" :
                        "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400"
                      }`}>
                        {f.status === "active" ? "运行中" : f.status === "cool_down" ? "冷却中" : "已暂停"}
                      </span>
                    </div>
                    <div className="text-xs text-muted-foreground mt-0.5">
                      配额 {f.daily_limit}/天 · 上次入库 {f.last_run_count} 篇
                      {f.last_run_at && ` · ${new Date(f.last_run_at).toLocaleDateString()}`}
                    </div>
                  </div>
                  <button
                    onClick={() => toggleCategory(f.category_code)}
                    className="text-destructive hover:text-destructive/80"
                  >
                    <XCircle className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
```

**Step 2: 添加 API 方法**

Modify `frontend/src/services/api.ts`，添加：

```ts
csCategories(): Promise<{ categories: CSCategory[] }>
csFeeds(): Promise<{ feeds: CSFeed[] }>
csFeedCreate(req: { category_codes: string[]; daily_limit: number }): Promise<any>
csFeedDelete(categoryCode: string): Promise<any>
```

---

### Task 7: Topics 页面添加 Tab 切换

**Files:**
- Modify: `frontend/src/pages/Topics.tsx`

**Step 1: 在 Topics.tsx 顶部添加 Tab 状态**

```tsx
const [activeTab, setActiveTab] = useState<"topics" | "cs-feeds">("topics");
```

**Step 2: 在 Topics 组件 return 的顶部添加 Tab 栏**

在 `<div className="page-hero">` 之前添加：

```tsx
<div className="flex gap-1 bg-card rounded-xl border p-1 mb-6">
  <button
    onClick={() => setActiveTab("topics")}
    className={`flex-1 py-2 text-sm font-medium rounded-lg transition-colors ${
      activeTab === "topics" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
    }`}
  >
    主题订阅
  </button>
  <button
    onClick={() => setActiveTab("cs-feeds")}
    className={`flex-1 py-2 text-sm font-medium rounded-lg transition-colors ${
      activeTab === "cs-feeds" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
    }`}
  >
    分类订阅
  </button>
</div>
```

**Step 3: 根据 Tab 条件渲染**

把 `return` 的主体用条件包裹：

```tsx
if (activeTab === "cs-feeds") {
  return <CSFeeds />;
}

return (
  <div className="animate-fade-in space-y-6">
    {/* 原有的 Topics 页面内容 */}
  </div>
);
```

**Step 4: 导入 CSFeeds**

在文件顶部添加：

```tsx
import CSFeeds from "./CSFeeds";
```

---

## Phase 6: 数据库迁移

### Task 8: 生成并执行数据库迁移

**Step 1: 生成迁移**

Run: `cd /Users/haojiang/Documents/2026/PaperMind/infra && alembic revision --autogenerate -m "add cs_categories and cs_feed_subscriptions"`

**Step 2: 执行迁移**

Run: `cd /Users/haojiang/Documents/2026/PaperMind/infra && alembic upgrade head`

---

## 验证清单

- [ ] `GET /cs/categories` 返回 CS 分类列表
- [ ] `POST /cs/feeds` 可订阅分类
- [ ] `GET /cs/feeds` 可查看已订阅列表
- [ ] `DELETE /cs/feeds/{code}` 可取消订阅
- [ ] Topics 页面 Tab 切换正常
- [ ] 分类订阅 Tab 显示分类列表和已订阅状态
- [ ] 勾选分类后 `topics.csFeedCreate` API 被调用
- [ ] Worker 每小时整点触发 `cs_feed_dispatch_job`
- [ ] 触发 429 后分类进入 30 分钟冷却
- [ ] 每日配额控制生效
