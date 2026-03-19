import { useEffect, useState, useCallback } from "react";
import { Loader2, RefreshCw, Layers, Pencil, Check, X, Play } from "lucide-react";
import { topicApi } from "@/services/api";
import { Button } from "@/components/ui";

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

export default function CSFeeds() {
  const [categories, setCategories] = useState<CSCategory[]>([]);
  const [feeds, setFeeds] = useState<CSFeed[]>([]);
  const [loading, setLoading] = useState(true);
  const [globalLimit, setGlobalLimit] = useState(30);
  const [editingCode, setEditingCode] = useState<string | null>(null);
  const [editLimit, setEditLimit] = useState(30);
  const [fetchingCode, setFetchingCode] = useState<string | null>(null);

  const loadData = useCallback(async () => {
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
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const subscribedCodes = new Set(feeds.map(f => f.category_code));

  async function toggleCategory(code: string) {
    if (subscribedCodes.has(code)) {
      await topicApi.csFeedDelete(code);
    } else {
      await topicApi.csFeedCreate({ category_codes: [code], daily_limit: globalLimit });
    }
    await loadData();
  }

  async function handleFetch(code: string) {
    setFetchingCode(code);
    try {
      await topicApi.csFeedFetch(code);
    } finally {
      setFetchingCode(null);
    }
  }

  async function updateLimit(code: string, newLimit: number) {
    await topicApi.csFeedUpdate(code, { daily_limit: newLimit });
    setEditingCode(null);
    await loadData();
  }

  function startEdit(feed: CSFeed) {
    setEditingCode(feed.category_code);
    setEditLimit(feed.daily_limit);
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-6 h-6 animate-spin text-ink-tertiary" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <div className="rounded-xl bg-primary/8 p-2"><Layers className="h-4 w-4 text-primary" /></div>
        <div>
          <h2 className="text-sm font-semibold text-ink">arXiv CS 分类订阅</h2>
          <p className="text-xs text-ink-tertiary">订阅感兴趣的 CS 细分领域，自动抓取最新论文</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-ink-secondary">新增默认配额</span>
          <input
            type="number"
            value={globalLimit}
            onChange={e => setGlobalLimit(Number(e.target.value))}
            className="w-16 h-8 rounded-lg border border-border bg-page px-2 text-sm text-center"
            min={1}
            max={200}
          />
          <span className="text-xs text-ink-tertiary">篇/天</span>
        </div>
      </div>

      <div className="rounded-xl border border-border bg-surface p-6 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <span className="text-xs text-ink-secondary">共 {categories.length} 个分类 · 已订阅 {feeds.length} 个</span>
          <Button size="sm" variant="ghost" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={loadData}>刷新</Button>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
          {categories.map(c => {
            const subscribed = subscribedCodes.has(c.code);
            const feed = feeds.find(f => f.category_code === c.code);
            return (
              <label
                key={c.code}
                className={`group flex items-center gap-2.5 rounded-lg border px-3 py-2.5 cursor-pointer transition-all ${
                  subscribed
                    ? "border-primary/30 bg-primary/5"
                    : "border-border bg-page hover:border-primary/20 hover:bg-primary/[0.02]"
                }`}
              >
                <input
                  type="checkbox"
                  checked={subscribed}
                  onChange={() => toggleCategory(c.code)}
                  className="sr-only"
                />
                <div className={`h-2 w-2 rounded-full ${subscribed ? "bg-primary" : "bg-ink-tertiary/30"}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-mono font-medium text-ink">{c.code}</span>
                    {subscribed && feed && (
                      <span className="text-[10px] text-ink-tertiary">
                        {feed.last_run_count > 0 ? `${feed.last_run_count}篇` : "待抓取"}
                      </span>
                    )}
                  </div>
                  <span className="text-[11px] text-ink-tertiary truncate block">{c.name}</span>
                </div>
              </label>
            );
          })}
        </div>
      </div>

      {feeds.length > 0 && (
        <div className="rounded-xl border border-border bg-surface p-6 shadow-sm">
          <h3 className="text-sm font-semibold text-ink mb-4">已订阅分类</h3>
          <div className="space-y-2">
            {feeds.map(f => (
              <div key={f.category_code} className="flex items-center justify-between rounded-lg border border-border/50 bg-page px-4 py-3">
                <div className="flex items-center gap-3">
                  <div className={`h-2 w-2 rounded-full ${f.enabled ? "bg-success animate-pulse" : "bg-ink-tertiary/30"}`} />
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-mono font-medium text-ink">{f.category_code}</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-success/10 text-success">
                        {f.status === "active" ? "运行中" : f.status === "cool_down" ? "冷却中" : "已暂停"}
                      </span>
                    </div>
                    <div className="text-[11px] text-ink-tertiary mt-0.5">
                      {f.last_run_at && `上次 ${new Date(f.last_run_at).toLocaleDateString()} · `}
                      已入库 {f.last_run_count} 篇
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {editingCode === f.category_code ? (
                    <>
                      <input
                        type="number"
                        value={editLimit}
                        onChange={e => setEditLimit(Number(e.target.value))}
                        className="w-16 h-7 rounded-lg border border-border bg-page px-2 text-xs text-center"
                        min={1}
                        max={200}
                      />
                      <span className="text-[10px] text-ink-tertiary">篇/天</span>
                      <button
                        type="button"
                        onClick={() => updateLimit(f.category_code, editLimit)}
                        className="p-1 rounded hover:bg-success/10 text-success"
                      >
                        <Check className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingCode(null)}
                        className="p-1 rounded hover:bg-error/10 text-error"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => handleFetch(f.category_code)}
                        disabled={fetchingCode === f.category_code}
                        className="flex items-center gap-1 rounded-lg bg-primary/8 px-2.5 py-1 text-xs font-medium text-primary hover:bg-primary/15 disabled:opacity-50"
                      >
                        {fetchingCode === f.category_code ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <Play className="h-3 w-3" />
                        )}
                        {fetchingCode === f.category_code ? "抓取中" : "手动抓取"}
                      </button>
                      <span className="text-xs text-ink-secondary">{f.daily_limit} 篇/天</span>
                      <button
                        type="button"
                        onClick={() => startEdit(f)}
                        className="p-1 rounded hover:bg-hover text-ink-tertiary"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => toggleCategory(f.category_code)}
                        className="text-xs text-error hover:text-error/80 px-2 py-1 rounded hover:bg-error/10"
                      >
                        取消
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
