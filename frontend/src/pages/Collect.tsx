/**
 * 论文收集与订阅管理 - 手动搜索 + 定时任务
 * @author Bamzc
 */
import { useState, useEffect, useCallback } from "react";
import { cn } from "@/lib/utils";
import {
  Search,
  Download,
  Clock,
  Plus,
  Trash2,
  CheckCircle2,
  Loader2,
  AlertTriangle,
  ArrowUpDown,
  FileText,
  Power,
  PowerOff,
  Pencil,
} from "lucide-react";
import { ingestApi, topicApi } from "@/services/api";
import type { Topic, TopicCreate, TopicUpdate } from "@/types";

type SortBy = "submittedDate" | "relevance" | "lastUpdatedDate";

interface SearchResult {
  ingested: number;
  query: string;
  sortBy: SortBy;
  time: string;
}

export default function Collect() {
  /* ========== 搜索状态 ========== */
  const [query, setQuery] = useState("");
  const [maxResults, setMaxResults] = useState(20);
  const [sortBy, setSortBy] = useState<SortBy>("submittedDate");
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [error, setError] = useState("");

  /* ========== 订阅状态 ========== */
  const [topics, setTopics] = useState<Topic[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState("");
  const [newQuery, setNewQuery] = useState("");
  const [newMax, setNewMax] = useState(20);
  const [saving, setSaving] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);

  /* 加载订阅列表 */
  useEffect(() => {
    topicApi.list(false).then((r) => { setTopics(r.items); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  /* ========== 搜索 ========== */
  const handleSearch = useCallback(async () => {
    if (!query.trim()) return;
    setSearching(true);
    setError("");
    try {
      const res = await ingestApi.arxiv(query.trim(), maxResults);
      setResults((prev) => [{ ingested: res.ingested, query: query.trim(), sortBy, time: new Date().toLocaleTimeString("zh-CN") }, ...prev]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "搜索失败");
    } finally {
      setSearching(false);
    }
  }, [query, maxResults, sortBy]);

  /* ========== 订阅 CRUD ========== */
  const handleAddTopic = useCallback(async () => {
    if (!newName.trim() || !newQuery.trim()) return;
    setSaving(true);
    try {
      const data: TopicCreate = { name: newName.trim(), query: newQuery.trim(), enabled: true, max_results_per_run: newMax };
      const topic = await topicApi.create(data);
      setTopics((prev) => [topic, ...prev]);
      setNewName(""); setNewQuery(""); setShowAdd(false);
    } catch (err) { setError(err instanceof Error ? err.message : "添加失败"); }
    finally { setSaving(false); }
  }, [newName, newQuery, newMax]);

  const handleToggle = useCallback(async (t: Topic) => {
    try {
      const data: TopicUpdate = { enabled: !t.enabled };
      await topicApi.update(t.id, data);
      setTopics((prev) => prev.map((x) => x.id === t.id ? { ...x, enabled: !x.enabled } : x));
    } catch { /* ignore */ }
  }, []);

  const handleDelete = useCallback(async (id: string) => {
    try { await topicApi.delete(id); setTopics((prev) => prev.filter((t) => t.id !== id)); } catch { /* ignore */ }
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent) => { if (e.key === "Enter") handleSearch(); };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-ink">论文收集与订阅</h1>
        <p className="mt-1 text-sm text-ink-secondary">从 arXiv 搜索论文，或创建订阅自动定时收集</p>
      </div>

      {/* ========== 搜索区 ========== */}
      <section className="rounded-2xl border border-border bg-surface p-6">
        <h2 className="mb-4 flex items-center gap-2 text-base font-semibold text-ink">
          <Search className="h-5 w-5 text-primary" />
          搜索并下载
        </h2>
        <div className="space-y-4">
          <div className="flex gap-3">
            <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={handleKeyDown} placeholder="输入关键词：3D reconstruction, NeRF, LLM..." className="flex-1 rounded-xl border border-border bg-page px-4 py-2.5 text-sm text-ink placeholder:text-ink-placeholder focus:border-primary/40 focus:outline-none" />
            <button onClick={handleSearch} disabled={!query.trim() || searching} className={cn("flex items-center gap-2 rounded-xl px-5 py-2.5 text-sm font-medium transition-all", query.trim() && !searching ? "bg-primary text-white shadow-sm hover:bg-primary-hover" : "bg-hover text-ink-tertiary")}>
              {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
              {searching ? "下载中..." : "搜索下载"}
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <label className="text-xs text-ink-secondary">数量:</label>
              <select value={maxResults} onChange={(e) => setMaxResults(Number(e.target.value))} className="rounded-lg border border-border bg-page px-2 py-1 text-xs text-ink">
                {[10, 20, 50, 100].map((n) => <option key={n} value={n}>{n} 篇</option>)}
              </select>
            </div>
            <div className="flex items-center gap-2">
              <ArrowUpDown className="h-3.5 w-3.5 text-ink-tertiary" />
              <label className="text-xs text-ink-secondary">排序:</label>
              <select value={sortBy} onChange={(e) => setSortBy(e.target.value as SortBy)} className="rounded-lg border border-border bg-page px-2 py-1 text-xs text-ink">
                <option value="submittedDate">最新提交</option>
                <option value="relevance">相关性</option>
                <option value="lastUpdatedDate">最近更新</option>
              </select>
            </div>
            {query.trim() && (
              <button onClick={() => { setNewName(query.trim()); setNewQuery(query.trim()); setNewMax(maxResults); setShowAdd(true); }} className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1 text-xs text-ink-secondary transition-colors hover:bg-hover hover:text-ink">
                <Clock className="h-3 w-3" />
                加为订阅
              </button>
            )}
          </div>
        </div>
        {error && <div className="mt-4 flex items-center gap-2 rounded-lg bg-error-light px-3 py-2 text-xs text-error"><AlertTriangle className="h-3.5 w-3.5" />{error}</div>}
        {results.length > 0 && (
          <div className="mt-4 space-y-2">
            {results.map((r, idx) => (
              <div key={idx} className="flex items-center gap-3 rounded-xl bg-page px-4 py-2.5">
                <CheckCircle2 className="h-4 w-4 shrink-0 text-success" />
                <div className="min-w-0 flex-1">
                  <span className="text-sm text-ink">"{r.query}" — <strong>{r.ingested}</strong> 篇</span>
                  <span className="ml-2 text-xs text-ink-tertiary">{r.time}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ========== 订阅管理 ========== */}
      <section className="rounded-2xl border border-border bg-surface p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-base font-semibold text-ink">
            <Clock className="h-5 w-5 text-primary" />
            自动订阅
          </h2>
          <button onClick={() => setShowAdd(!showAdd)} className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-primary-hover">
            <Plus className="h-3.5 w-3.5" />
            新建订阅
          </button>
        </div>

        {/* 新建表单 */}
        {showAdd && (
          <div className="mb-4 space-y-3 rounded-xl border border-border-light bg-page p-4">
            <div className="grid grid-cols-3 gap-3">
              <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="订阅名称" className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-placeholder focus:border-primary/40 focus:outline-none" />
              <input value={newQuery} onChange={(e) => setNewQuery(e.target.value)} placeholder="arXiv 搜索关键词" className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-placeholder focus:border-primary/40 focus:outline-none" />
              <select value={newMax} onChange={(e) => setNewMax(Number(e.target.value))} className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink">
                {[10, 20, 50].map((n) => <option key={n} value={n}>每次 {n} 篇</option>)}
              </select>
            </div>
            <div className="flex gap-2">
              <button onClick={handleAddTopic} disabled={!newName.trim() || !newQuery.trim() || saving} className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-primary-hover disabled:opacity-50">
                {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
                创建
              </button>
              <button onClick={() => setShowAdd(false)} className="rounded-lg border border-border px-4 py-1.5 text-sm text-ink-secondary hover:bg-hover">取消</button>
            </div>
          </div>
        )}

        {/* 订阅列表 */}
        {loading ? (
          <div className="flex items-center justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-ink-tertiary" /></div>
        ) : topics.length === 0 ? (
          <p className="py-8 text-center text-sm text-ink-tertiary">暂无订阅。创建订阅后系统会定期自动收集论文。</p>
        ) : (
          <div className="space-y-2">
            {topics.map((t) => (
              <div key={t.id} className="flex items-center gap-3 rounded-xl bg-page px-4 py-3 transition-colors hover:bg-hover">
                <div className={cn("h-2 w-2 shrink-0 rounded-full", t.enabled ? "bg-success" : "bg-ink-tertiary")} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-ink">{t.name}</p>
                  <p className="text-xs text-ink-tertiary">
                    {t.query} · 每次 {t.max_results_per_run} 篇 · 重试 {t.retry_limit} 次
                  </p>
                </div>
                <button onClick={() => handleToggle(t)} className={cn("flex h-7 items-center gap-1 rounded-lg px-2 text-xs font-medium transition-colors", t.enabled ? "text-success hover:bg-success-light" : "text-ink-tertiary hover:bg-hover")} title={t.enabled ? "暂停" : "启用"}>
                  {t.enabled ? <Power className="h-3 w-3" /> : <PowerOff className="h-3 w-3" />}
                  {t.enabled ? "运行中" : "已暂停"}
                </button>
                <button onClick={() => handleDelete(t.id)} className="flex h-7 w-7 items-center justify-center rounded-lg text-ink-tertiary transition-colors hover:bg-error-light hover:text-error">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
