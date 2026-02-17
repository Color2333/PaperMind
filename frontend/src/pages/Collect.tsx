/**
 * 论文收集与订阅管理（现代精致版）
 * @author Bamzc
 */
import { useState, useEffect, useCallback } from "react";
import { Button, Empty, Spinner } from "@/components/ui";
import {
  Search,
  Download,
  Clock,
  Plus,
  Trash2,
  CheckCircle2,
  AlertTriangle,
  ArrowUpDown,
  Power,
  PowerOff,
  Sparkles,
  Pencil,
  X,
  Rss,
  Loader2,
} from "lucide-react";
import { ingestApi, topicApi } from "@/services/api";
import type { Topic, TopicCreate, TopicUpdate, ScheduleFrequency, KeywordSuggestion } from "@/types";

type SortBy = "submittedDate" | "relevance" | "lastUpdatedDate";

interface SearchResult {
  ingested: number;
  query: string;
  sortBy: SortBy;
  time: string;
}

const FREQ_OPTIONS: { value: ScheduleFrequency; label: string }[] = [
  { value: "daily", label: "每天" },
  { value: "twice_daily", label: "每天两次" },
  { value: "weekdays", label: "工作日" },
  { value: "weekly", label: "每周" },
];
const FREQ_LABEL: Record<string, string> = { daily: "每天", twice_daily: "每天两次", weekdays: "工作日", weekly: "每周" };

function utcToBj(utc: number): number { return (utc + 8) % 24; }
function bjToUtc(bj: number): number { return (bj - 8 + 24) % 24; }
function hourOptions(): { value: number; label: string }[] {
  return Array.from({ length: 24 }, (_, i) => ({ value: i, label: `${String(i).padStart(2, "0")}:00` }));
}

export default function Collect() {
  const [query, setQuery] = useState("");
  const [maxResults, setMaxResults] = useState(20);
  const [sortBy, setSortBy] = useState<SortBy>("submittedDate");
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [error, setError] = useState("");

  const [topics, setTopics] = useState<Topic[]>([]);
  const [loading, setLoading] = useState(true);

  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [formName, setFormName] = useState("");
  const [formQuery, setFormQuery] = useState("");
  const [formMax, setFormMax] = useState(20);
  const [formFreq, setFormFreq] = useState<ScheduleFrequency>("daily");
  const [formTimeBj, setFormTimeBj] = useState(5);
  const [saving, setSaving] = useState(false);

  const [aiDesc, setAiDesc] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<KeywordSuggestion[]>([]);

  useEffect(() => {
    topicApi.list(false).then((r) => { setTopics(r.items); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  const handleSearch = useCallback(async () => {
    if (!query.trim()) return;
    setSearching(true); setError("");
    try {
      const res = await ingestApi.arxiv(query.trim(), maxResults);
      setResults((prev) => [{ ingested: res.ingested, query: query.trim(), sortBy, time: new Date().toLocaleTimeString("zh-CN") }, ...prev]);
    } catch (err) { setError(err instanceof Error ? err.message : "搜索失败"); } finally { setSearching(false); }
  }, [query, maxResults, sortBy]);

  const handleAiSuggest = useCallback(async () => {
    const desc = aiDesc.trim() || formQuery.trim() || query.trim();
    if (!desc) return;
    setAiLoading(true); setSuggestions([]);
    try { const res = await topicApi.suggestKeywords(desc); setSuggestions(res.suggestions); }
    catch { setError("AI 建议失败"); } finally { setAiLoading(false); }
  }, [aiDesc, formQuery, query]);

  const applySuggestion = useCallback((s: KeywordSuggestion) => { setFormName(s.name); setFormQuery(s.query); setSuggestions([]); setAiDesc(""); }, []);

  const resetForm = useCallback(() => { setShowForm(false); setEditId(null); setFormName(""); setFormQuery(""); setFormMax(20); setFormFreq("daily"); setFormTimeBj(5); setSuggestions([]); setAiDesc(""); }, []);
  const openAdd = useCallback(() => { resetForm(); setShowForm(true); }, [resetForm]);
  const openEdit = useCallback((t: Topic) => {
    setEditId(t.id); setFormName(t.name); setFormQuery(t.query); setFormMax(t.max_results_per_run);
    setFormFreq(t.schedule_frequency || "daily"); setFormTimeBj(utcToBj(t.schedule_time_utc ?? 21));
    setSuggestions([]); setAiDesc(""); setShowForm(true);
  }, []);

  const handleSave = useCallback(async () => {
    if (!formName.trim() || !formQuery.trim()) return;
    setSaving(true);
    try {
      const utcHour = bjToUtc(formTimeBj);
      if (editId) {
        const updated = await topicApi.update(editId, { query: formQuery.trim(), max_results_per_run: formMax, schedule_frequency: formFreq, schedule_time_utc: utcHour });
        setTopics((prev) => prev.map((x) => (x.id === editId ? updated : x)));
      } else {
        const topic = await topicApi.create({ name: formName.trim(), query: formQuery.trim(), enabled: true, max_results_per_run: formMax, schedule_frequency: formFreq, schedule_time_utc: utcHour });
        setTopics((prev) => [topic, ...prev]);
      }
      resetForm();
    } catch (err) { setError(err instanceof Error ? err.message : "保存失败"); } finally { setSaving(false); }
  }, [formName, formQuery, formMax, formFreq, formTimeBj, editId, resetForm]);

  const handleToggle = useCallback(async (t: Topic) => {
    try { await topicApi.update(t.id, { enabled: !t.enabled }); setTopics((prev) => prev.map((x) => (x.id === t.id ? { ...x, enabled: !x.enabled } : x))); } catch {}
  }, []);
  const handleDelete = useCallback(async (id: string) => {
    try { await topicApi.delete(id); setTopics((prev) => prev.filter((t) => t.id !== id)); } catch {}
  }, []);

  return (
    <div className="animate-fade-in space-y-8">
      {/* 页面头 */}
      <div className="page-hero rounded-2xl p-6">
        <h1 className="text-2xl font-bold text-ink">论文收集</h1>
        <p className="mt-1 text-sm text-ink-secondary">从 arXiv 搜索下载论文，或创建订阅自动定时收集</p>
      </div>

      {/* 错误 */}
      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-error/20 bg-error-light px-4 py-3">
          <AlertTriangle className="h-4 w-4 text-error" />
          <p className="flex-1 text-sm text-error">{error}</p>
          <button onClick={() => setError("")} className="text-error/60 hover:text-error"><X className="h-4 w-4" /></button>
        </div>
      )}

      {/* 搜索区 */}
      <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm">
        <div className="mb-5 flex items-center gap-2">
          <div className="rounded-xl bg-primary/8 p-2"><Search className="h-4 w-4 text-primary" /></div>
          <div>
            <h2 className="text-sm font-semibold text-ink">即时搜索</h2>
            <p className="text-xs text-ink-tertiary">搜索并下载论文到本地库</p>
          </div>
        </div>

        <div className="flex gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-tertiary" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleSearch(); }}
              placeholder="3D reconstruction, NeRF, LLM alignment..."
              className="h-11 w-full rounded-xl border border-border bg-page pl-10 pr-4 text-sm text-ink placeholder:text-ink-placeholder focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          </div>
          <Button icon={<Download className="h-4 w-4" />} onClick={handleSearch} loading={searching} disabled={!query.trim()}>
            搜索下载
          </Button>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-xs text-ink-secondary">
            数量
            <select value={maxResults} onChange={(e) => setMaxResults(Number(e.target.value))} className="h-7 rounded-lg border border-border bg-surface px-2 text-xs text-ink">
              {[10, 20, 50, 100].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs text-ink-secondary">
            <ArrowUpDown className="h-3 w-3" /> 排序
            <select value={sortBy} onChange={(e) => setSortBy(e.target.value as SortBy)} className="h-7 rounded-lg border border-border bg-surface px-2 text-xs text-ink">
              <option value="submittedDate">最新提交</option>
              <option value="relevance">相关性</option>
              <option value="lastUpdatedDate">最近更新</option>
            </select>
          </label>
          {query.trim() && (
            <Button variant="secondary" size="sm" icon={<Clock className="h-3 w-3" />}
              onClick={() => { setFormName(query.trim()); setFormQuery(query.trim()); setFormMax(maxResults); setShowForm(true); }}>
              加为订阅
            </Button>
          )}
        </div>

        {/* 结果 */}
        {results.length > 0 && (
          <div className="mt-4 space-y-2">
            {results.map((r, i) => (
              <div key={i} className="flex items-center gap-3 rounded-xl bg-success-light/50 px-4 py-2.5">
                <CheckCircle2 className="h-4 w-4 shrink-0 text-success" />
                <span className="text-sm text-ink">&quot;{r.query}&quot; — <strong>{r.ingested}</strong> 篇</span>
                <span className="ml-auto text-xs text-ink-tertiary">{r.time}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 订阅管理 */}
      <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm">
        <div className="mb-5 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="rounded-xl bg-info/8 p-2"><Rss className="h-4 w-4 text-info" /></div>
            <div>
              <h2 className="text-sm font-semibold text-ink">自动订阅</h2>
              <p className="text-xs text-ink-tertiary">系统定期自动收集新论文</p>
            </div>
          </div>
          <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={openAdd}>新建</Button>
        </div>

        {/* 表单 */}
        {showForm && (
          <div className="mb-5 rounded-2xl border border-border-light bg-page p-5">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-ink">{editId ? "编辑订阅" : "新建订阅"}</h3>
              <button onClick={resetForm} className="rounded-lg p-1 text-ink-tertiary hover:bg-hover"><X className="h-4 w-4" /></button>
            </div>

            <div className="space-y-4">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <FormField label="订阅名称">
                  <input value={formName} onChange={(e) => setFormName(e.target.value)} placeholder="3D 重建" disabled={!!editId}
                    className="form-input" />
                </FormField>
                <FormField label="arXiv 关键词">
                  <input value={formQuery} onChange={(e) => setFormQuery(e.target.value)} placeholder="all:NeRF AND all:3D"
                    className="form-input" />
                </FormField>
                <FormField label="每次数量">
                  <select value={formMax} onChange={(e) => setFormMax(Number(e.target.value))} className="form-input">
                    {[10, 20, 50].map((n) => <option key={n} value={n}>{n} 篇</option>)}
                  </select>
                </FormField>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <FormField label="频率">
                  <select value={formFreq} onChange={(e) => setFormFreq(e.target.value as ScheduleFrequency)} className="form-input">
                    {FREQ_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </FormField>
                <FormField label="执行时间（北京）">
                  <select value={formTimeBj} onChange={(e) => setFormTimeBj(Number(e.target.value))} className="form-input">
                    {hourOptions().map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </FormField>
              </div>

              {/* AI 建议 */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-ink-secondary">AI 关键词建议</label>
                <div className="flex gap-2">
                  <div className="relative flex-1">
                    <Sparkles className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-primary/40" />
                    <input value={aiDesc} onChange={(e) => setAiDesc(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") handleAiSuggest(); }}
                      placeholder="描述研究兴趣，AI 生成搜索词..."
                      className="form-input pl-9" />
                  </div>
                  <Button variant="secondary" size="sm" icon={aiLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
                    onClick={handleAiSuggest} disabled={aiLoading || (!aiDesc.trim() && !formQuery.trim() && !query.trim())}>
                    AI 建议
                  </Button>
                </div>
                {suggestions.length > 0 && (
                  <div className="mt-2 grid gap-2 sm:grid-cols-2">
                    {suggestions.map((s, i) => (
                      <button key={i} onClick={() => applySuggestion(s)}
                        className="flex items-start gap-2 rounded-xl border border-border-light bg-surface p-3 text-left transition-all hover:border-primary/30 hover:shadow-sm">
                        <Sparkles className="mt-0.5 h-3 w-3 shrink-0 text-primary" />
                        <div className="min-w-0">
                          <p className="text-xs font-medium text-ink">{s.name}</p>
                          <p className="mt-0.5 font-mono text-[10px] text-ink-tertiary">{s.query}</p>
                          <p className="mt-0.5 text-[10px] text-ink-secondary">{s.reason}</p>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex gap-2 pt-1">
                <Button icon={editId ? <Pencil className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />}
                  onClick={handleSave} loading={saving} disabled={!formName.trim() || !formQuery.trim()}>
                  {editId ? "保存" : "创建"}
                </Button>
                <Button variant="secondary" onClick={resetForm}>取消</Button>
              </div>
            </div>
          </div>
        )}

        {/* 订阅列表 */}
        {loading ? (
          <Spinner text="加载订阅列表..." />
        ) : topics.length === 0 ? (
          <Empty icon={<Rss className="h-12 w-12" />} title="暂无订阅" description="创建订阅后系统会定期自动收集论文" action={<Button size="sm" onClick={openAdd}>创建第一个订阅</Button>} />
        ) : (
          <div className="space-y-2">
            {topics.map((t) => {
              const bjHour = utcToBj(t.schedule_time_utc ?? 21);
              const freqLabel = FREQ_LABEL[t.schedule_frequency] || "每天";
              return (
                <div key={t.id} className="group flex items-center gap-3 rounded-xl border border-transparent bg-page px-4 py-3 transition-all hover:border-border hover:shadow-sm">
                  <div className={`h-2.5 w-2.5 shrink-0 rounded-full ${t.enabled ? "bg-success" : "bg-ink-tertiary"} ${t.enabled ? "status-running" : ""}`} />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-ink">{t.name}</p>
                    <p className="text-xs text-ink-tertiary">{t.query}</p>
                  </div>
                  <div className="hidden shrink-0 text-right sm:block">
                    <p className="text-xs font-medium text-ink-secondary">{freqLabel} {String(bjHour).padStart(2, "0")}:00</p>
                    <p className="text-[10px] text-ink-tertiary">每次 {t.max_results_per_run} 篇</p>
                  </div>
                  <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                    <button onClick={() => openEdit(t)} className="rounded-lg p-1.5 text-ink-tertiary hover:bg-hover hover:text-ink"><Pencil className="h-3.5 w-3.5" /></button>
                    <button onClick={() => handleToggle(t)} className={`rounded-lg p-1.5 ${t.enabled ? "text-success hover:bg-success-light" : "text-ink-tertiary hover:bg-hover"}`}>
                      {t.enabled ? <Power className="h-3.5 w-3.5" /> : <PowerOff className="h-3.5 w-3.5" />}
                    </button>
                    <button onClick={() => handleDelete(t.id)} className="rounded-lg p-1.5 text-ink-tertiary hover:bg-error-light hover:text-error"><Trash2 className="h-3.5 w-3.5" /></button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium text-ink-secondary">{label}</label>
      {children}
    </div>
  );
}
