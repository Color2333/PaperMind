/**
 * 论文收集与订阅管理（重构版：手动抓取 + 丰富结果展示）
 * @author Bamzc
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
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
  RefreshCw,
  FileText,
  ExternalLink,
  ChevronDown,
  ChevronRight,
  Library,
  Calendar,
  Hash,
  Zap,
  Play,
} from "lucide-react";
import { ingestApi, topicApi, type TopicFetchResult } from "@/services/api";
import { useToast } from "@/contexts/ToastContext";
import ConfirmDialog from "@/components/ConfirmDialog";
import type { Topic, TopicCreate, TopicUpdate, ScheduleFrequency, KeywordSuggestion, IngestPaper } from "@/types";

type SortBy = "submittedDate" | "relevance" | "lastUpdatedDate";

interface SearchResult {
  ingested: number;
  papers: IngestPaper[];
  query: string;
  sortBy: SortBy;
  time: string;
  expanded: boolean;
}

const FREQ_OPTIONS: { value: ScheduleFrequency; label: string; desc: string }[] = [
  { value: "daily", label: "每天", desc: "每日自动抓取" },
  { value: "twice_daily", label: "每天两次", desc: "上午和下午各一次" },
  { value: "weekdays", label: "工作日", desc: "周一至周五" },
  { value: "weekly", label: "每周", desc: "每周日" },
];
const FREQ_LABEL: Record<string, string> = { daily: "每天", twice_daily: "每天两次", weekdays: "工作日", weekly: "每周" };

function utcToBj(utc: number): number { return (utc + 8) % 24; }
function bjToUtc(bj: number): number { return (bj - 8 + 24) % 24; }
function hourOptions(): { value: number; label: string }[] {
  return Array.from({ length: 24 }, (_, i) => ({ value: i, label: `${String(i).padStart(2, "0")}:00` }));
}

function relativeTime(iso: string): string {
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "刚刚";
  if (mins < 60) return `${mins} 分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} 天前`;
  return d.toLocaleDateString("zh-CN");
}

export default function Collect() {
  const { toast } = useToast();
  const navigate = useNavigate();

  // ========== 即时搜索 ==========
  const [query, setQuery] = useState("");
  const [maxResults, setMaxResults] = useState(20);
  const [sortBy, setSortBy] = useState<SortBy>("submittedDate");
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [error, setError] = useState("");

  // ========== 订阅管理 ==========
  const [topics, setTopics] = useState<Topic[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchingTopicId, setFetchingTopicId] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  // ========== 表单 ==========
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [formName, setFormName] = useState("");
  const [formQuery, setFormQuery] = useState("");
  const [formMax, setFormMax] = useState(20);
  const [formFreq, setFormFreq] = useState<ScheduleFrequency>("daily");
  const [formTimeBj, setFormTimeBj] = useState(5);
  const [saving, setSaving] = useState(false);

  // ========== AI 建议 ==========
  const [aiDesc, setAiDesc] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<KeywordSuggestion[]>([]);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  useEffect(() => {
    topicApi.list(false).then((r) => { setTopics(r.items); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  // ========== 即时搜索 ==========
  const handleSearch = useCallback(async () => {
    if (!query.trim()) return;
    setSearching(true); setError("");
    try {
      const res = await ingestApi.arxiv(query.trim(), maxResults, undefined, sortBy);
      setResults((prev) => [{
        ingested: res.ingested,
        papers: res.papers || [],
        query: query.trim(),
        sortBy,
        time: new Date().toLocaleTimeString("zh-CN"),
        expanded: true,
      }, ...prev.map(r => ({ ...r, expanded: false }))]);
      if (res.ingested > 0) toast("success", `成功收集 ${res.ingested} 篇论文`);
      else toast("info", "未找到新论文（可能已全部收集）");
    } catch (err) {
      setError(err instanceof Error ? err.message : "搜索失败");
    } finally { setSearching(false); }
  }, [query, maxResults, sortBy, toast]);

  // ========== 手动抓取订阅 ==========
  const handleManualFetch = useCallback(async (topicId: string) => {
    setFetchingTopicId(topicId);
    try {
      const res: TopicFetchResult = await topicApi.fetch(topicId);
      if (res.status === "started" || res.status === "already_running") {
        toast("info", res.topic_name || "抓取已在后台启动...");
        // 轮询状态
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = setInterval(async () => {
          try {
            const status = await topicApi.fetchStatus(topicId);
            if (status.status === "running") {
              // 显示进度
              const progress = status.progress_pct || 0;
              const message = status.message || `抓取中... (${progress}%)`;
              toast("info", message);
              return;
            }
            if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
            setFetchingTopicId(null);
            if (status.status === "ok" || status.status === "no_new_papers") {
              const newCount = status.new_count || status.inserted;
              const totalCount = status.total_count || status.inserted;
              const skipped = totalCount - newCount;
              let msg = `抓取完成：${newCount} 篇新论文`;
              if (skipped > 0) msg += `（跳过 ${skipped} 篇重复）`;
              if (status.processed > 0) msg += `，${status.processed} 篇处理`;
              toast("success", msg);
              // 刷新整个订阅列表，确保 last_run_at 和 paper_count 更新
              const list = await topicApi.list(false);
              setTopics(list.items);
              return;
            }
            if (status.status === "failed") {
              toast("error", `抓取失败：${status.error || "未知错误"}`);
            }
            // 无论如何都刷新列表
            const list = await topicApi.list(false);
            setTopics(list.items);
          } catch {
            if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
            setFetchingTopicId(null);
          }
        }, 3000);
        return;
      }
      if (res.status === "ok") {
        const newCount = res.new_count || res.inserted;
        const totalCount = res.total_count || res.inserted;
        const skipped = totalCount - newCount;
        let msg = `抓取完成：${newCount} 篇新论文`;
        if (skipped > 0) msg += `（跳过 ${skipped} 篇重复）`;
        if (res.processed > 0) msg += `，${res.processed} 篇处理`;
        toast("success", msg);
        const list = await topicApi.list(false);
        setTopics(list.items);
      } else if (res.status === "no_new_papers") {
        toast("info", `⚠️  没有新论文（${res.total_count || 0} 篇重复），已跳过处理`);
      } else {
        toast("error", `抓取失败：${res.error || "未知错误"}`);
      }
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "抓取失败");
    } finally { setFetchingTopicId(null); }
  }, [toast]);

  // ========== AI 建议 ==========
  const handleAiSuggest = useCallback(async () => {
    const desc = aiDesc.trim() || formQuery.trim() || query.trim();
    if (!desc) return;
    setAiLoading(true); setSuggestions([]);
    try { const res = await topicApi.suggestKeywords(desc); setSuggestions(res.suggestions); }
    catch { setError("AI 建议失败"); } finally { setAiLoading(false); }
  }, [aiDesc, formQuery, query]);

  const applySuggestion = useCallback((s: KeywordSuggestion) => { setFormName(s.name); setFormQuery(s.query); setSuggestions([]); setAiDesc(""); }, []);

  // ========== 表单操作 ==========
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
    try {
      const updated = await topicApi.update(t.id, { enabled: !t.enabled });
      setTopics((prev) => prev.map((x) => (x.id === t.id ? updated : x)));
    } catch { toast("error", "切换订阅状态失败"); }
  }, [toast]);
  const handleDelete = useCallback(async (id: string) => {
    try { await topicApi.delete(id); setTopics((prev) => prev.filter((t) => t.id !== id)); } catch { toast("error", "删除订阅失败"); }
  }, []);

  return (
    <div className="animate-fade-in space-y-6">
      {/* 页面头 */}
      <div className="page-hero rounded-2xl p-6">
        <div className="flex items-center gap-3">
          <div className="rounded-xl bg-primary/10 p-2.5"><Download className="h-5 w-5 text-primary" /></div>
          <div>
            <h1 className="text-2xl font-bold text-ink">论文收集</h1>
            <p className="mt-0.5 text-sm text-ink-secondary">搜索下载论文 · 创建订阅自动收集 · 随时手动触发抓取</p>
          </div>
        </div>
      </div>

      {/* 错误 */}
      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-error/20 bg-error-light px-4 py-3">
          <AlertTriangle className="h-4 w-4 text-error" />
          <p className="flex-1 text-sm text-error">{error}</p>
          <button aria-label="关闭" onClick={() => setError("")} className="text-error/60 hover:text-error"><X className="h-4 w-4" /></button>
        </div>
      )}

      {/* ================================================================
       * 即时搜索区
       * ================================================================ */}
      <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm">
        <div className="mb-5 flex items-center gap-2">
          <div className="rounded-xl bg-primary/8 p-2"><Search className="h-4 w-4 text-primary" /></div>
          <div>
            <h2 className="text-sm font-semibold text-ink">即时搜索</h2>
            <p className="text-xs text-ink-tertiary">输入关键词从 arXiv 搜索，论文直接下载到本地库</p>
          </div>
        </div>

        {/* 搜索栏 */}
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
          <Button icon={searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />} onClick={handleSearch} loading={searching} disabled={!query.trim()}>
            搜索下载
          </Button>
        </div>

        {/* 筛选条件 */}
        <div className="mt-3 flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-xs text-ink-secondary">
            <Hash className="h-3 w-3" /> 数量
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
            <button
              onClick={() => { setFormName(query.trim()); setFormQuery(query.trim()); setFormMax(maxResults); setShowForm(true); }}
              className="flex items-center gap-1.5 rounded-lg bg-primary/8 px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/15"
            >
              <Clock className="h-3 w-3" /> 存为自动订阅
            </button>
          )}
        </div>

        {/* 搜索结果 */}
        {results.length > 0 && (
          <div className="mt-5 space-y-3">
            {results.map((r, i) => (
              <SearchResultCard key={i} result={r} onToggle={() => setResults(prev => prev.map((x, j) => j === i ? { ...x, expanded: !x.expanded } : x))} onNavigate={(paperId) => navigate(`/papers/${paperId}`)} />
            ))}
          </div>
        )}
      </div>

      {/* ================================================================
       * 自动订阅管理
       * ================================================================ */}
      <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm">
        <div className="mb-5 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="rounded-xl bg-info/8 p-2"><Rss className="h-4 w-4 text-info" /></div>
            <div>
              <h2 className="text-sm font-semibold text-ink">自动订阅</h2>
              <p className="text-xs text-ink-tertiary">定时自动收集，也可随时手动触发</p>
            </div>
          </div>
          <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={openAdd}>新建订阅</Button>
        </div>

        {/* 新建/编辑表单 */}
        {showForm && (
          <div className="mb-5 rounded-2xl border border-primary/20 bg-primary/[0.02] p-5">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-ink">
                {editId ? <Pencil className="h-4 w-4 text-primary" /> : <Plus className="h-4 w-4 text-primary" />}
                {editId ? "编辑订阅" : "新建订阅"}
              </h3>
              <button aria-label="关闭" onClick={resetForm} className="rounded-lg p-1 text-ink-tertiary hover:bg-hover"><X className="h-4 w-4" /></button>
            </div>

            <div className="space-y-4">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <FormField label="订阅名称" hint="给这个订阅起个名字">
                  <input value={formName} onChange={(e) => setFormName(e.target.value)} placeholder="例：3D 重建" disabled={!!editId}
                    className="form-input" />
                </FormField>
                <FormField label="搜索关键词" hint="arXiv API 搜索表达式">
                  <input value={formQuery} onChange={(e) => setFormQuery(e.target.value)} placeholder="all:NeRF AND all:3D"
                    className="form-input" />
                </FormField>
                <FormField label="每次数量" hint="单次最多抓取篇数">
                  <select value={formMax} onChange={(e) => setFormMax(Number(e.target.value))} className="form-input">
                    {[10, 20, 50].map((n) => <option key={n} value={n}>{n} 篇</option>)}
                  </select>
                </FormField>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <FormField label="抓取频率">
                  <div className="grid grid-cols-2 gap-2">
                    {FREQ_OPTIONS.map((o) => (
                      <button key={o.value} onClick={() => setFormFreq(o.value)}
                        className={`rounded-lg border px-3 py-2 text-left text-xs transition-all ${formFreq === o.value ? "border-primary bg-primary/8 text-primary" : "border-border bg-surface text-ink-secondary hover:border-border/80"}`}>
                        <span className="font-medium">{o.label}</span>
                        <span className="ml-1 text-ink-tertiary">{o.desc}</span>
                      </button>
                    ))}
                  </div>
                </FormField>
                <FormField label="执行时间（北京时间）" hint="系统在指定时间自动抓取">
                  <select value={formTimeBj} onChange={(e) => setFormTimeBj(Number(e.target.value))} className="form-input">
                    {hourOptions().map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </FormField>
              </div>

              {/* AI 关键词建议 */}
              <div className="rounded-xl border border-dashed border-primary/20 bg-primary/[0.02] p-4">
                <label className="mb-2 flex items-center gap-1.5 text-xs font-medium text-primary">
                  <Sparkles className="h-3.5 w-3.5" /> AI 关键词助手
                </label>
                <div className="flex gap-2">
                  <div className="relative flex-1">
                    <input value={aiDesc} onChange={(e) => setAiDesc(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") handleAiSuggest(); }}
                      placeholder="用自然语言描述你的研究兴趣，AI 自动生成搜索词..."
                      className="h-9 w-full rounded-lg border border-border bg-surface px-3 text-xs text-ink placeholder:text-ink-placeholder focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary/20" />
                  </div>
                  <Button variant="secondary" size="sm" icon={aiLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
                    onClick={handleAiSuggest} disabled={aiLoading || (!aiDesc.trim() && !formQuery.trim() && !query.trim())}>
                    生成
                  </Button>
                </div>
                {suggestions.length > 0 && (
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    {suggestions.map((s, i) => (
                      <button key={i} onClick={() => applySuggestion(s)}
                        className="flex items-start gap-2 rounded-xl border border-border bg-surface p-3 text-left transition-all hover:border-primary/30 hover:shadow-sm">
                        <Zap className="mt-0.5 h-3 w-3 shrink-0 text-amber-500" />
                        <div className="min-w-0">
                          <p className="text-xs font-medium text-ink">{s.name}</p>
                          <p className="mt-0.5 font-mono text-[10px] text-primary/70">{s.query}</p>
                          <p className="mt-0.5 text-[10px] text-ink-tertiary">{s.reason}</p>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex gap-2 pt-1">
                <Button icon={editId ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />}
                  onClick={handleSave} loading={saving} disabled={!formName.trim() || !formQuery.trim()}>
                  {editId ? "保存修改" : "创建订阅"}
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
          <Empty icon={<Rss className="h-12 w-12" />} title="暂无订阅" description="创建订阅后系统会按设定的频率自动收集论文" action={<Button size="sm" onClick={openAdd}>创建第一个订阅</Button>} />
        ) : (
          <div className="space-y-3">
            {topics.map((t) => (
              <TopicCard
                key={t.id}
                topic={t}
                fetching={fetchingTopicId === t.id}
                onEdit={() => openEdit(t)}
                onToggle={() => handleToggle(t)}
                onDelete={() => setConfirmDeleteId(t.id)}
                onFetch={() => handleManualFetch(t.id)}
                onNavigate={() => navigate(`/papers?topicId=${t.id}`)}
              />
            ))}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={!!confirmDeleteId}
        title="删除订阅"
        description="删除后将停止自动收集该主题的论文，确定要删除吗？"
        variant="danger"
        confirmLabel="删除"
        onConfirm={async () => { if (confirmDeleteId) { await handleDelete(confirmDeleteId); setConfirmDeleteId(null); } }}
        onCancel={() => setConfirmDeleteId(null)}
      />
    </div>
  );
}


/* ================================================================
 * 订阅卡片
 * ================================================================ */
function TopicCard({
  topic: t,
  fetching,
  onEdit,
  onToggle,
  onDelete,
  onFetch,
  onNavigate,
}: {
  topic: Topic;
  fetching: boolean;
  onEdit: () => void;
  onToggle: () => void;
  onDelete: () => void;
  onFetch: () => void;
  onNavigate: () => void;
}) {
  const bjHour = utcToBj(t.schedule_time_utc ?? 21);
  const freqLabel = FREQ_LABEL[t.schedule_frequency] || "每天";

  return (
    <div className={`group rounded-xl border transition-all ${t.enabled ? "border-border bg-page hover:border-primary/20 hover:shadow-sm" : "border-border/50 bg-page/50 opacity-70"}`}>
      <div className="flex items-start gap-3 px-4 py-3.5">
        {/* 状态指示灯 */}
        <div className="mt-1.5 flex flex-col items-center gap-1">
          <div className={`h-2.5 w-2.5 rounded-full ${t.enabled ? "bg-success" : "bg-ink-tertiary"} ${t.enabled ? "animate-pulse" : ""}`} />
        </div>

        {/* 主体信息 */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-ink">{t.name}</h3>
            <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${t.enabled ? "bg-success/10 text-success" : "bg-ink-tertiary/10 text-ink-tertiary"}`}>
              {t.enabled ? "运行中" : "已暂停"}
            </span>
          </div>

          {/* 搜索词 */}
          <p className="mt-1 font-mono text-xs text-ink-tertiary">{t.query}</p>

          {/* 统计信息 */}
          <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-ink-secondary">
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {freqLabel} {String(bjHour).padStart(2, "0")}:00
            </span>
            <span className="flex items-center gap-1">
              <Hash className="h-3 w-3" />
              每次 {t.max_results_per_run} 篇
            </span>
            {(t.paper_count ?? 0) > 0 && (
              <button onClick={onNavigate} className="flex items-center gap-1 text-primary hover:underline">
                <Library className="h-3 w-3" />
                已收集 {t.paper_count} 篇
              </button>
            )}
            {t.last_run_at && (
              <span className="flex items-center gap-1">
                <Calendar className="h-3 w-3" />
                上次: {relativeTime(t.last_run_at)}
                {t.last_run_count != null && <> · {t.last_run_count} 篇</>}
              </span>
            )}
          </div>
        </div>

        {/* 操作按钮 */}
        <div className="flex shrink-0 items-center gap-1">
          {/* 手动抓取按钮 */}
          <button
            onClick={onFetch}
            disabled={fetching}
            className="flex items-center gap-1.5 rounded-lg bg-primary/8 px-3 py-1.5 text-xs font-medium text-primary transition-all hover:bg-primary/15 disabled:opacity-50"
            title="立即抓取最新论文"
          >
            {fetching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            {fetching ? "抓取中..." : "手动抓取"}
          </button>

          <div className="mx-1 h-5 w-px bg-border" />

          <button aria-label="编辑" onClick={onEdit} className="rounded-lg p-1.5 text-ink-tertiary hover:bg-hover hover:text-ink" title="编辑订阅">
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button aria-label={t.enabled ? "暂停" : "启用"} onClick={onToggle}
            className={`rounded-lg p-1.5 ${t.enabled ? "text-success hover:bg-success-light" : "text-ink-tertiary hover:bg-hover"}`}
            title={t.enabled ? "暂停自动抓取" : "启用自动抓取"}>
            {t.enabled ? <Power className="h-3.5 w-3.5" /> : <PowerOff className="h-3.5 w-3.5" />}
          </button>
          <button aria-label="删除" onClick={onDelete} className="rounded-lg p-1.5 text-ink-tertiary hover:bg-error-light hover:text-error" title="删除订阅">
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}


/* ================================================================
 * 即时搜索结果卡片
 * ================================================================ */
function SearchResultCard({ result: r, onToggle, onNavigate }: { result: SearchResult; onToggle: () => void; onNavigate: (id: string) => void }) {
  return (
    <div className="rounded-xl border border-success/20 bg-success/[0.03] transition-all">
      {/* 头部：摘要信息 */}
      <button onClick={onToggle} className="flex w-full items-center gap-3 px-4 py-3 text-left">
        <CheckCircle2 className="h-4 w-4 shrink-0 text-success" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-ink">
              &quot;{r.query}&quot;
            </span>
            <span className="rounded-full bg-success/10 px-2 py-0.5 text-[10px] font-semibold text-success">
              {r.ingested} 篇
            </span>
          </div>
          {r.papers.length > 0 && !r.expanded && (
            <p className="mt-0.5 truncate text-xs text-ink-tertiary">
              {r.papers.slice(0, 3).map(p => p.title).join(" · ")}
            </p>
          )}
        </div>
        <span className="shrink-0 text-[10px] text-ink-tertiary">{r.time}</span>
        {r.papers.length > 0 && (
          r.expanded ? <ChevronDown className="h-4 w-4 shrink-0 text-ink-tertiary" /> : <ChevronRight className="h-4 w-4 shrink-0 text-ink-tertiary" />
        )}
      </button>

      {/* 展开：论文列表 */}
      {r.expanded && r.papers.length > 0 && (
        <div className="border-t border-success/10 px-4 py-2">
          <div className="space-y-1.5">
            {r.papers.map((p) => (
              <div key={p.id} className="flex items-center gap-2 rounded-lg px-2 py-1.5 transition-colors hover:bg-success/5">
                <FileText className="h-3.5 w-3.5 shrink-0 text-ink-tertiary" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium text-ink">{p.title}</p>
                  <div className="flex items-center gap-2 text-[10px] text-ink-tertiary">
                    {p.arxiv_id && <span>{p.arxiv_id}</span>}
                    {p.publication_date && <span>{p.publication_date}</span>}
                  </div>
                </div>
                <button onClick={() => onNavigate(p.id)} className="shrink-0 rounded-md p-1 text-ink-tertiary transition-colors hover:bg-primary/10 hover:text-primary" title="查看论文">
                  <ExternalLink className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}


/* ================================================================
 * 通用表单字段
 * ================================================================ */
function FormField({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium text-ink-secondary">{label}</label>
      {hint && <p className="text-[10px] text-ink-tertiary">{hint}</p>}
      {children}
    </div>
  );
}
