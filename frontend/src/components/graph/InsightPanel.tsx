/**
 * 领域洞察面板 — 一键查询: 时间线 + 演化 + 质量 + 研究空白
 * @author Bamzc
 */
import { useState, useCallback } from "react";
import { Button, Badge } from "@/components/ui";
import { useToast } from "@/contexts/ToastContext";
import { graphApi, topicApi, todayApi, type TodaySummary } from "@/services/api";
import {
  Search, Network, Clock, BarChart3, TrendingUp, Star,
  ArrowDown, ArrowRight, Layers, Lightbulb, HelpCircle,
  Tag, Rss, Flame, Target, AlertTriangle, Zap,
  ChevronDown, ChevronRight, SlidersHorizontal, Compass, RotateCw,
} from "lucide-react";
import type {
  Topic, TimelineResponse, GraphQuality, EvolutionResponse, ResearchGapsResponse,
} from "@/types";
import { Section, PaperLink, NetStat, StrengthBadge, GapCard, LoadingHint } from "./shared";
import { useEffect } from "react";

const LIMIT_OPTIONS = [
  { value: 30, label: "30 篇" },
  { value: 50, label: "50 篇" },
  { value: 100, label: "100 篇" },
  { value: 200, label: "200 篇" },
  { value: 500, label: "500 篇" },
] as const;

export default function InsightPanel() {
  const { toast } = useToast();
  const [keyword, setKeyword] = useState("");
  const [limit, setLimit] = useState(100);
  const [loading, setLoading] = useState(false);

  const [timelineData, setTimelineData] = useState<TimelineResponse | null>(null);
  const [qualityData, setQualityData] = useState<GraphQuality | null>(null);
  const [evolutionData, setEvolutionData] = useState<EvolutionResponse | null>(null);
  const [gapsData, setGapsData] = useState<ResearchGapsResponse | null>(null);

  /* 推荐关键词 */
  const [topics, setTopics] = useState<Topic[]>([]);
  const [hotKeywords, setHotKeywords] = useState<{ keyword: string; count: number }[]>([]);
  const [activeKeyword, setActiveKeyword] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const [topicRes, todayRes] = await Promise.all([
        topicApi.list(true).catch(() => ({ items: [] as Topic[] })),
        todayApi.summary().catch(() => null as TodaySummary | null),
      ]);
      setTopics(topicRes.items);
      if (todayRes?.hot_keywords) setHotKeywords(todayRes.hot_keywords);
    })();
  }, []);

  const suggestedKeywords = (() => {
    const seen = new Set<string>();
    const result: { keyword: string; source: "topic" | "hot"; count?: number }[] = [];
    for (const t of topics) {
      if (!seen.has(t.name)) { seen.add(t.name); result.push({ keyword: t.name, source: "topic" }); }
    }
    for (const h of hotKeywords) {
      if (!seen.has(h.keyword)) { seen.add(h.keyword); result.push({ keyword: h.keyword, source: "hot", count: h.count }); }
    }
    return result;
  })();

  /* 一键并行查四项 */
  const runInsight = useCallback(async (kw: string) => {
    if (!kw.trim()) return;
    setKeyword(kw);
    setActiveKeyword(kw);
    setLoading(true);
    try {
      const [tl, ev, qa, gp] = await Promise.all([
        graphApi.timeline(kw, limit).catch(() => null),
        graphApi.evolution(kw, limit).catch(() => null),
        graphApi.quality(kw, limit).catch(() => null),
        graphApi.researchGaps(kw, limit).catch(() => null),
      ]);
      if (tl) setTimelineData(tl);
      if (ev) setEvolutionData(ev);
      if (qa) setQualityData(qa);
      if (gp) setGapsData(gp);
    } catch { toast("error", "查询失败，请重试"); }
    finally { setLoading(false); }
  }, [limit, toast]);

  const handleSubmit = useCallback(() => {
    runInsight(keyword);
  }, [keyword, runInsight]);

  const hasResults = timelineData || qualityData || evolutionData || gapsData;

  /* 单项刷新 */
  const refreshTimeline = useCallback(async () => { if (activeKeyword) setTimelineData(await graphApi.timeline(activeKeyword, limit)); }, [activeKeyword, limit]);
  const refreshEvolution = useCallback(async () => { if (activeKeyword) setEvolutionData(await graphApi.evolution(activeKeyword, limit)); }, [activeKeyword, limit]);
  const refreshQuality = useCallback(async () => { if (activeKeyword) setQualityData(await graphApi.quality(activeKeyword, limit)); }, [activeKeyword, limit]);
  const refreshGaps = useCallback(async () => { if (activeKeyword) setGapsData(await graphApi.researchGaps(activeKeyword, limit)); }, [activeKeyword, limit]);

  return (
    <div className="space-y-5">
      {/* 搜索区 */}
      <div className="rounded-2xl border border-border bg-surface p-5 shadow-sm">
        <div className="flex gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-tertiary" />
            <input
              placeholder="输入关键词: transformer, reinforcement learning..."
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleSubmit(); }}
              className="h-11 w-full rounded-xl border border-border bg-page pl-10 pr-4 text-sm text-ink placeholder:text-ink-placeholder focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          </div>
          <div className="relative flex items-center">
            <SlidersHorizontal className="absolute left-3 h-3.5 w-3.5 text-ink-tertiary pointer-events-none" />
            <select
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="h-11 appearance-none rounded-xl border border-border bg-page pl-9 pr-8 text-sm text-ink focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 cursor-pointer"
            >
              {LIMIT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
            <ChevronDown className="absolute right-2.5 h-3.5 w-3.5 text-ink-tertiary pointer-events-none" />
          </div>
          <Button icon={<Search className="h-4 w-4" />} onClick={handleSubmit} loading={loading}>分析</Button>
        </div>
      </div>

      {/* 推荐关键词 */}
      {suggestedKeywords.length > 0 && (
        <div className="rounded-2xl border border-border bg-surface p-4 shadow-sm">
          <div className="mb-3 flex items-center gap-2">
            <Tag className="h-3.5 w-3.5 text-primary" />
            <span className="text-xs font-medium text-ink-secondary">快速探索</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {suggestedKeywords.map((item) => (
              <button
                key={item.keyword}
                onClick={() => runInsight(item.keyword)}
                className={`group flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-medium transition-all ${
                  activeKeyword === item.keyword
                    ? "bg-primary text-white shadow-sm"
                    : "bg-page text-ink-secondary hover:bg-primary/8 hover:text-primary"
                }`}
              >
                {item.source === "topic" ? <Rss className="h-3 w-3" /> : <Flame className="h-3 w-3" />}
                {item.keyword}
                {item.count != null && (
                  <span className={`rounded-full px-1.5 text-[10px] ${
                    activeKeyword === item.keyword ? "bg-white/20 text-white" : "bg-border-light text-ink-tertiary"
                  }`}>{item.count}</span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* 加载 */}
      {loading && <LoadingHint tab="insight" isInit={false} />}

      {/* 无结果 */}
      {!loading && !hasResults && (
        <div className="flex flex-col items-center rounded-2xl border border-dashed border-border py-16 text-center">
          <Compass className="h-8 w-8 text-ink-tertiary/30" />
          <p className="mt-4 text-sm text-ink-tertiary">
            {suggestedKeywords.length > 0 ? "点击关键词或输入自定义关键词开始分析" : "输入关键词开始探索领域洞察"}
          </p>
        </div>
      )}

      {/* ---- 四项结果 ---- */}
      {!loading && hasResults && (
        <div className="space-y-5">
          {/* 时间线 */}
          {timelineData && (
            <CollapsibleSection title="时间线" icon={<Clock className="h-4 w-4 text-primary" />} onRefresh={refreshTimeline} defaultOpen>
              <TimelineContent data={timelineData} />
            </CollapsibleSection>
          )}

          {/* 演化趋势 */}
          {evolutionData && (
            <CollapsibleSection title="演化趋势" icon={<TrendingUp className="h-4 w-4 text-primary" />} onRefresh={refreshEvolution} defaultOpen>
              <EvolutionContent data={evolutionData} />
            </CollapsibleSection>
          )}

          {/* 质量分析 */}
          {qualityData && (
            <CollapsibleSection title="质量分析" icon={<BarChart3 className="h-4 w-4 text-primary" />} onRefresh={refreshQuality}>
              <QualityContent data={qualityData} />
            </CollapsibleSection>
          )}

          {/* 研究空白 */}
          {gapsData && (
            <CollapsibleSection title="研究空白" icon={<Target className="h-4 w-4 text-warning" />} onRefresh={refreshGaps} defaultOpen>
              <ResearchGapsContent data={gapsData} />
            </CollapsibleSection>
          )}
        </div>
      )}
    </div>
  );
}

/* ==================== 可折叠区块 ==================== */
function CollapsibleSection({ title, icon, onRefresh, defaultOpen = false, children }: {
  title: string; icon: React.ReactNode; onRefresh?: () => void;
  defaultOpen?: boolean; children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [refreshing, setRefreshing] = useState(false);

  const handleRefresh = async () => {
    if (!onRefresh) return;
    setRefreshing(true);
    try { await onRefresh(); } catch { /* ignore */ }
    finally { setRefreshing(false); }
  };

  return (
    <div className="animate-fade-in rounded-2xl border border-border bg-surface shadow-sm">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-5 py-4 text-left"
      >
        {icon}
        <span className="flex-1 text-sm font-semibold text-ink">{title}</span>
        {onRefresh && (
          <span
            onClick={(e) => { e.stopPropagation(); handleRefresh(); }}
            className="rounded-lg p-1.5 text-ink-tertiary hover:bg-hover hover:text-primary transition-colors"
          >
            <RotateCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
          </span>
        )}
        {open ? <ChevronDown className="h-4 w-4 text-ink-tertiary" /> : <ChevronRight className="h-4 w-4 text-ink-tertiary" />}
      </button>
      {open && <div className="border-t border-border px-5 pb-5 pt-4">{children}</div>}
    </div>
  );
}

/* ==================== 时间线内容 ==================== */
function TimelineContent({ data }: { data: TimelineResponse }) {
  return (
    <div className="space-y-6">
      {data.seminal.length > 0 && (
        <div>
          <p className="mb-3 flex items-center gap-1.5 text-xs font-semibold text-ink-secondary">
            <Star className="h-3.5 w-3.5 text-warning" /> 开创性论文
          </p>
          <div className="space-y-2">
            {data.seminal.map((e) => (
              <div key={e.paper_id} className="flex items-center justify-between rounded-xl border border-warning/20 bg-warning-light p-4">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Star className="h-4 w-4 shrink-0 text-warning" />
                    <PaperLink id={e.paper_id} title={e.title} />
                  </div>
                  {e.why_seminal && <p className="mt-1 pl-6 text-xs text-ink-secondary">{e.why_seminal}</p>}
                </div>
                <div className="shrink-0 pl-4 text-right">
                  <span className="text-lg font-bold text-warning">{e.seminal_score.toFixed(2)}</span>
                  <p className="text-xs text-ink-tertiary">{e.year}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div>
        <p className="mb-3 flex items-center gap-1.5 text-xs font-semibold text-ink-secondary">
          <Clock className="h-3.5 w-3.5 text-primary" /> 时间轴 ({data.timeline.length} 篇)
        </p>
        <div className="relative ml-3 border-l-2 border-border-light pl-5 space-y-1">
          {data.timeline.map((e) => (
            <div key={e.paper_id} className="relative rounded-xl px-3 py-2 transition-colors hover:bg-hover">
              <span className="absolute -left-[1.625rem] top-1/2 h-2.5 w-2.5 -translate-y-1/2 rounded-full border-2 border-primary bg-surface" />
              <div className="flex items-center gap-3">
                <span className="w-10 shrink-0 text-xs font-semibold text-primary">{e.year}</span>
                <PaperLink id={e.paper_id} title={e.title} className="min-w-0 flex-1 truncate" />
                <div className="flex shrink-0 gap-2 text-[10px] text-ink-tertiary">
                  <span>↓{e.indegree}</span><span>↑{e.outdegree}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {data.milestones.length > 0 && (
        <div>
          <p className="mb-3 flex items-center gap-1.5 text-xs font-semibold text-ink-secondary">
            <Lightbulb className="h-3.5 w-3.5 text-info" /> 里程碑
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            {data.milestones.map((m) => (
              <div key={m.paper_id} className="flex items-center gap-3 rounded-xl bg-info-light p-3">
                <Lightbulb className="h-4 w-4 shrink-0 text-info" />
                <PaperLink id={m.paper_id} title={m.title} className="flex-1 truncate" />
                <span className="text-xs font-medium text-info">{m.year}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ==================== 演化内容 ==================== */
function EvolutionContent({ data }: { data: EvolutionResponse }) {
  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl bg-page p-4">
          <p className="mb-1 text-[10px] font-medium uppercase tracking-widest text-ink-tertiary">趋势总结</p>
          <p className="text-sm leading-relaxed text-ink-secondary">{data.summary.trend_summary}</p>
        </div>
        <div className="rounded-xl bg-page p-4">
          <p className="mb-1 text-[10px] font-medium uppercase tracking-widest text-ink-tertiary">阶段转变</p>
          <p className="text-sm leading-relaxed text-ink-secondary">{data.summary.phase_shift_signals}</p>
        </div>
        <div className="rounded-xl bg-primary/5 p-4">
          <p className="mb-1 text-[10px] font-medium uppercase tracking-widest text-primary">下周关注</p>
          <p className="text-sm font-medium leading-relaxed text-ink">{data.summary.next_week_focus}</p>
        </div>
      </div>

      <div>
        <p className="mb-3 flex items-center gap-1.5 text-xs font-semibold text-ink-secondary">
          <BarChart3 className="h-3.5 w-3.5 text-info" /> 年度分布
        </p>
        <div className="space-y-2">
          {data.year_buckets.map((b) => {
            const maxCount = Math.max(...data.year_buckets.map((x) => x.paper_count), 1);
            const pct = Math.max((b.paper_count / maxCount) * 100, 3);
            return (
              <div key={b.year} className="flex items-center gap-4 rounded-xl px-3 py-2 transition-colors hover:bg-hover">
                <span className="w-12 shrink-0 text-sm font-bold text-ink">{b.year}</span>
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-page">
                      <div className="bar-animate h-full rounded-full bg-gradient-to-r from-primary to-primary/60" style={{ width: `${pct}%` }} />
                    </div>
                    <span className="w-10 text-right text-xs font-medium text-ink-secondary">{b.paper_count}</span>
                  </div>
                  {b.top_titles[0] && <p className="mt-0.5 truncate text-[10px] text-ink-tertiary">{b.top_titles[0]}</p>}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* ==================== 质量分析内容 ==================== */
function QualityContent({ data }: { data: GraphQuality }) {
  const metrics = [
    { label: "节点数", value: data.node_count, icon: Layers, color: "primary" },
    { label: "边数", value: data.edge_count, icon: Network, color: "info" },
    { label: "密度", value: data.density.toFixed(4), icon: BarChart3, color: "warning" },
    { label: "连通比例", value: `${(data.connected_node_ratio * 100).toFixed(1)}%`, icon: TrendingUp, color: "success" },
    { label: "日期覆盖", value: `${(data.publication_date_coverage * 100).toFixed(1)}%`, icon: Clock, color: "info" },
  ] as const;

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
      {metrics.map((m) => (
        <div key={m.label} className={`stat-gradient-${m.color} rounded-2xl border border-border p-4`}>
          <m.icon className={`h-4 w-4 text-${m.color} mb-2`} />
          <p className="text-xl font-bold text-ink">{m.value}</p>
          <p className="text-xs text-ink-tertiary">{m.label}</p>
        </div>
      ))}
    </div>
  );
}

/* ==================== 研究空白内容 ==================== */
function ResearchGapsContent({ data }: { data: ResearchGapsResponse }) {
  const { network_stats, analysis } = data;
  const { research_gaps, method_comparison, trend_analysis, overall_summary } = analysis;

  return (
    <div className="space-y-6">
      {/* 网络统计 */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        <NetStat label="总论文" value={network_stats.total_papers} />
        <NetStat label="引用边" value={network_stats.edge_count} />
        <NetStat label="密度" value={network_stats.density.toFixed(4)} />
        <NetStat label="连通率" value={`${(network_stats.connected_ratio * 100).toFixed(1)}%`} />
        <NetStat label="孤立论文" value={network_stats.isolated_count} highlight />
      </div>

      {/* 总结 */}
      {overall_summary && (
        <div className="rounded-xl bg-page p-5">
          <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-ink-secondary">
            <Target className="h-3.5 w-3.5" /> 分析总结
          </p>
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-secondary">{overall_summary}</p>
        </div>
      )}

      {/* 研究空白列表 */}
      {research_gaps.length > 0 && (
        <div>
          <p className="mb-3 flex items-center gap-1.5 text-xs font-semibold text-ink-secondary">
            <AlertTriangle className="h-3.5 w-3.5 text-warning" /> 识别到 {research_gaps.length} 个研究空白
          </p>
          <div className="space-y-3">
            {research_gaps.map((gap, i) => <GapCard key={i} gap={gap} index={i} />)}
          </div>
        </div>
      )}

      {/* 方法对比矩阵 */}
      {method_comparison.methods.length > 0 && (
        <div>
          <p className="mb-3 flex items-center gap-1.5 text-xs font-semibold text-ink-secondary">
            <Layers className="h-3.5 w-3.5 text-info" /> 方法对比矩阵
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th className="px-3 py-2 text-left font-medium text-ink-tertiary">方法</th>
                  {method_comparison.dimensions.map((dim) => (
                    <th key={dim} className="px-3 py-2 text-center font-medium text-ink-tertiary">{dim}</th>
                  ))}
                  <th className="px-3 py-2 text-left font-medium text-ink-tertiary">来源</th>
                </tr>
              </thead>
              <tbody>
                {method_comparison.methods.map((m, i) => (
                  <tr key={i} className="border-b border-border/50 transition-colors hover:bg-hover">
                    <td className="px-3 py-2 font-medium text-ink">{m.name}</td>
                    {method_comparison.dimensions.map((dim) => (
                      <td key={dim} className="px-3 py-2 text-center">
                        <StrengthBadge value={m.scores[dim]} />
                      </td>
                    ))}
                    <td className="px-3 py-2 text-xs text-ink-tertiary">{m.papers.join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {method_comparison.underexplored_combinations.length > 0 && (
            <div className="mt-4 rounded-xl bg-warning/5 p-4">
              <p className="mb-2 text-xs font-semibold text-warning">未被探索的方法组合</p>
              <ul className="space-y-1">
                {method_comparison.underexplored_combinations.map((c, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-ink-secondary">
                    <Zap className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />{c}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* 趋势分析 */}
      <div className="grid gap-4 sm:grid-cols-3">
        {trend_analysis.hot_directions.length > 0 && (
          <div className="rounded-xl bg-error/5 p-4">
            <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-error">
              <Flame className="h-3.5 w-3.5" /> 热门方向
            </p>
            <ul className="space-y-1">
              {trend_analysis.hot_directions.map((d, i) => (
                <li key={i} className="text-sm text-ink-secondary">• {d}</li>
              ))}
            </ul>
          </div>
        )}
        {trend_analysis.declining_areas.length > 0 && (
          <div className="rounded-xl bg-page p-4">
            <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-ink-tertiary">
              <ArrowDown className="h-3.5 w-3.5" /> 式微方向
            </p>
            <ul className="space-y-1">
              {trend_analysis.declining_areas.map((d, i) => (
                <li key={i} className="text-sm text-ink-secondary">• {d}</li>
              ))}
            </ul>
          </div>
        )}
        {trend_analysis.emerging_opportunities.length > 0 && (
          <div className="rounded-xl bg-success/5 p-4">
            <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-success">
              <Zap className="h-3.5 w-3.5" /> 新兴机会
            </p>
            <ul className="space-y-1">
              {trend_analysis.emerging_opportunities.map((d, i) => (
                <li key={i} className="text-sm text-ink-secondary">• {d}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
