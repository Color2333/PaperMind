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
      const [catRes, feedRes] = await Promise.all([topicApi.csCategories(), topicApi.csFeeds()]);
      setCategories(catRes.categories || []);
      setFeeds(feedRes.feeds || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const subscribedCodes = new Set(feeds.map((f) => f.category_code));

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
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="text-ink-tertiary h-6 w-6 animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <div className="bg-primary/8 rounded-xl p-2">
          <Layers className="text-primary h-4 w-4" />
        </div>
        <div>
          <h2 className="text-ink text-sm font-semibold">arXiv CS 分类订阅</h2>
          <p className="text-ink-tertiary text-xs">订阅感兴趣的 CS 细分领域，自动抓取最新论文</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-ink-secondary text-xs">新增默认配额</span>
          <input
            type="number"
            value={globalLimit}
            onChange={(e) => setGlobalLimit(Number(e.target.value))}
            className="border-border bg-page h-8 w-16 rounded-lg border px-2 text-center text-sm"
            min={1}
            max={200}
          />
          <span className="text-ink-tertiary text-xs">篇/天</span>
        </div>
      </div>

      <div className="border-border bg-surface rounded-xl border p-6 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <span className="text-ink-secondary text-xs">
            共 {categories.length} 个分类 · 已订阅 {feeds.length} 个
          </span>
          <Button
            size="sm"
            variant="ghost"
            icon={<RefreshCw className="h-3.5 w-3.5" />}
            onClick={loadData}
          >
            刷新
          </Button>
        </div>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-4">
          {categories.map((c) => {
            const subscribed = subscribedCodes.has(c.code);
            const feed = feeds.find((f) => f.category_code === c.code);
            return (
              <label
                key={c.code}
                className={`group flex cursor-pointer items-center gap-2.5 rounded-lg border px-3 py-2.5 transition-all ${
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
                <div
                  className={`h-2 w-2 rounded-full ${subscribed ? "bg-primary" : "bg-ink-tertiary/30"}`}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-ink font-mono text-xs font-medium">{c.code}</span>
                    {subscribed && feed && (
                      <span className="text-ink-tertiary text-[10px]">
                        {feed.last_run_count > 0 ? `${feed.last_run_count}篇` : "待抓取"}
                      </span>
                    )}
                  </div>
                  <span className="text-ink-tertiary block truncate text-[11px]">{c.name}</span>
                </div>
              </label>
            );
          })}
        </div>
      </div>

      {feeds.length > 0 && (
        <div className="border-border bg-surface rounded-xl border p-6 shadow-sm">
          <h3 className="text-ink mb-4 text-sm font-semibold">已订阅分类</h3>
          <div className="space-y-2">
            {feeds.map((f) => (
              <div
                key={f.category_code}
                className="border-border/50 bg-page flex items-center justify-between rounded-lg border px-4 py-3"
              >
                <div className="flex items-center gap-3">
                  <div
                    className={`h-2 w-2 rounded-full ${f.enabled ? "bg-success animate-pulse" : "bg-ink-tertiary/30"}`}
                  />
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-ink font-mono text-sm font-medium">
                        {f.category_code}
                      </span>
                      <span className="bg-success/10 text-success rounded-full px-1.5 py-0.5 text-[10px]">
                        {f.status === "active"
                          ? "运行中"
                          : f.status === "cool_down"
                            ? "冷却中"
                            : "已暂停"}
                      </span>
                    </div>
                    <div className="text-ink-tertiary mt-0.5 text-[11px]">
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
                        onChange={(e) => setEditLimit(Number(e.target.value))}
                        className="border-border bg-page h-7 w-16 rounded-lg border px-2 text-center text-xs"
                        min={1}
                        max={200}
                      />
                      <span className="text-ink-tertiary text-[10px]">篇/天</span>
                      <button
                        type="button"
                        onClick={() => updateLimit(f.category_code, editLimit)}
                        className="hover:bg-success/10 text-success rounded p-1"
                      >
                        <Check className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingCode(null)}
                        className="hover:bg-error/10 text-error rounded p-1"
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
                        className="bg-primary/8 text-primary hover:bg-primary/15 flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium disabled:opacity-50"
                      >
                        {fetchingCode === f.category_code ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <Play className="h-3 w-3" />
                        )}
                        {fetchingCode === f.category_code ? "抓取中" : "手动抓取"}
                      </button>
                      <span className="text-ink-secondary text-xs">{f.daily_limit} 篇/天</span>
                      <button
                        type="button"
                        onClick={() => startEdit(f)}
                        className="hover:bg-hover text-ink-tertiary rounded p-1"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => toggleCategory(f.category_code)}
                        className="text-error hover:text-error/80 hover:bg-error/10 rounded px-2 py-1 text-xs"
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
