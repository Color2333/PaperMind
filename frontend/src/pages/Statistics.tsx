/**
 * Statistics - 主题统计分析
 * @author Color2333
 */
import { useEffect, useState } from "react";
import { topicApi } from "@/services/api";
import type { TopicStats, TopicStatsResponse, PaperDistributionResponse } from "@/types";
import {
  BarChart3,
  BookOpen,
  Quote,
  TrendingUp,
  Loader2,
  RefreshCw,
  Calendar,
  Globe,
  TrendingDown,
  Activity,
  Layers,
} from "lucide-react";

const STATUS_COLORS: Record<string, string> = {
  "unread": "bg-slate-400",
  "skimmed": "bg-yellow-500",
  "deep_read": "bg-primary",
};

const SOURCE_COLORS: Record<string, string> = {
  arxiv: "bg-red-500",
  "semantic_scholar": "bg-blue-500",
  reference_import: "bg-green-500",
  unknown: "bg-gray-500",
  "initial_import": "bg-purple-500",
  "manual_collect": "bg-orange-500",
  "auto_collect": "bg-cyan-500",
  "agent_collect": "bg-pink-500",
  "subscription_ingest": "bg-indigo-500",
};

const GRADIENT_COLORS = [
  "from-indigo-500 to-purple-500",
  "from-emerald-500 to-teal-500",
  "from-orange-500 to-amber-500",
  "from-pink-500 to-rose-500",
  "from-cyan-500 to-blue-500",
];

function StatCard({
  icon, label, value, sub, color,
}: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  sub?: string;
  color: "primary" | "info" | "warning" | "success";
}) {
  const iconColors = {
    primary: "text-primary",
    info: "text-info",
    warning: "text-warning",
    success: "text-success",
  };

  return (
    <div className={`stat-gradient-${color} rounded-2xl border border-border bg-surface p-5 text-left shadow-sm`}>
      <div className="flex items-center justify-between">
        <div className={`rounded-xl p-2.5 ${iconColors[color]} bg-white/60 dark:bg-white/5`}>{icon}</div>
      </div>
      <p className="mt-3 text-2xl font-bold tracking-tight text-ink">{value}</p>
      <p className="mt-0.5 text-xs text-ink-tertiary">{label}</p>
      {sub && <p className="text-xs text-ink-secondary">{sub}</p>}
    </div>
  );
}

function TopicCard({ stat }: { stat: TopicStats }) {
  const total = stat.status_dist.unread + stat.status_dist.skimmed + stat.status_dist.deep_read;
  const readRate = total > 0 ? ((stat.status_dist.skimmed + stat.status_dist.deep_read) / total * 100).toFixed(0) : 0;

  return (
    <div className="bg-card rounded-xl border p-5 space-y-4 hover-lift transition-all hover:shadow-md">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-sm truncate flex-1 mr-3">{stat.topic_name}</h3>
        <span className="text-xs font-medium text-muted-foreground bg-muted px-2 py-1 rounded-full shrink-0">{stat.paper_count} 篇</span>
      </div>
      
      <div className="grid grid-cols-2 gap-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
            <Quote className="w-4 h-4 text-primary" />
          </div>
          <div>
            <p className="text-lg font-bold">{stat.total_citations.toLocaleString()}</p>
            <p className="text-[10px] text-muted-foreground">总引用</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-emerald-500/10 flex items-center justify-center">
            <TrendingUp className="w-4 h-4 text-emerald-500" />
          </div>
          <div>
            <p className="text-lg font-bold">{stat.recent_30d}</p>
            <p className="text-[10px] text-muted-foreground">30天活跃</p>
          </div>
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex justify-between text-xs">
          <span className="text-muted-foreground">阅读进度</span>
          <span className="font-medium text-primary">{readRate}%</span>
        </div>
        <div className="h-2.5 bg-muted rounded-full overflow-hidden flex shadow-inner">
          {total > 0 && (
            <>
              <div
                className="bg-primary h-full rounded-l-full"
                style={{ width: `${(stat.status_dist.deep_read / total) * 100}%` }}
              />
              <div
                className="bg-yellow-500 h-full"
                style={{ width: `${(stat.status_dist.skimmed / total) * 100}%` }}
              />
              <div
                className="bg-slate-300 dark:bg-slate-600 h-full rounded-r-full"
                style={{ width: `${(stat.status_dist.unread / total) * 100}%` }}
              />
            </>
          )}
        </div>
        <div className="flex justify-between text-[11px] text-muted-foreground">
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-primary" />精读 {stat.status_dist.deep_read}</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-yellow-500" />粗读 {stat.status_dist.skimmed}</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-slate-300 dark:bg-slate-600" />未读 {stat.status_dist.unread}</span>
        </div>
      </div>
    </div>
  );
}

function CitationBar({ stat, max, index }: { stat: TopicStats; max: number; index: number }) {
  const gradient = GRADIENT_COLORS[index % GRADIENT_COLORS.length];
  return (
    <div className="flex items-center gap-4 py-2">
      <span className="text-sm w-28 truncate shrink-0 font-medium">{stat.topic_name}</span>
      <div className="flex-1 h-6 bg-muted rounded-lg overflow-hidden shadow-inner">
        <div
          className={`h-full bg-gradient-to-r ${gradient} rounded-lg transition-all duration-500`}
          style={{ width: `${(stat.total_citations / max) * 100}%` }}
        />
      </div>
      <span className="text-sm font-bold w-16 text-right shrink-0">{stat.total_citations.toLocaleString()}</span>
    </div>
  );
}

function YearDistribution({ data }: { data: PaperDistributionResponse }) {
  const years = data.by_year.filter(y => y.year !== "未知").sort((a, b) => b.year.localeCompare(a.year));
  const maxCount = Math.max(...years.map(y => y.count), 1);

  return (
    <div className="bg-card rounded-xl border p-5 space-y-4">
      <div className="flex items-center gap-2">
        <Calendar className="w-5 h-5 text-primary" />
        <h3 className="font-semibold">论文年份分布</h3>
        <span className="text-xs text-muted-foreground ml-auto">{years.reduce((s, y) => s + y.count, 0)} 篇</span>
      </div>
      {years.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-6">暂无年份数据</p>
      ) : (
        <div className="space-y-3">
          {years.slice(0, 6).map((y, i) => (
            <div key={y.year} className="flex items-center gap-3">
              <span className="text-sm font-mono w-12 shrink-0 text-muted-foreground">{y.year}</span>
              <div className="flex-1 h-7 bg-muted rounded-lg overflow-hidden shadow-inner relative">
                <div
                  className={`h-full bg-gradient-to-r ${GRADIENT_COLORS[i % GRADIENT_COLORS.length]} rounded-lg`}
                  style={{ width: `${(y.count / maxCount) * 100}%` }}
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-bold text-foreground">
                  {y.count}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SourceDistribution({ data }: { data: PaperDistributionResponse }) {
  const sources = data.by_source;
  const total = sources.reduce((sum, s) => sum + s.count, 0);

  return (
    <div className="bg-card rounded-xl border p-5 space-y-4">
      <div className="flex items-center gap-2">
        <Globe className="w-5 h-5 text-blue-500" />
        <h3 className="font-semibold">论文来源</h3>
        <span className="text-xs text-muted-foreground ml-auto">{total} 篇</span>
      </div>
      {sources.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-6">暂无来源数据</p>
      ) : (
        <div className="space-y-3">
          {sources.map((s) => {
            const pct = total > 0 ? ((s.count / total) * 100).toFixed(0) : 0;
            return (
              <div key={s.raw_source} className="flex items-center gap-3">
                <div className={`w-3 h-3 rounded-full shrink-0 ${SOURCE_COLORS[s.raw_source] || "bg-gray-500"}`} />
                <span className="text-sm flex-1 truncate">{s.source}</span>
                <div className="w-24 h-2 bg-muted rounded-full overflow-hidden shrink-0 shadow-inner">
                  <div
                    className={`h-full ${SOURCE_COLORS[s.raw_source] || "bg-gray-500"} rounded-full`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="text-xs font-bold w-12 text-right shrink-0">{pct}%</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function MonthlyTrend({ data }: { data: PaperDistributionResponse }) {
  const months = data.by_month;
  const maxCount = Math.max(...months.map(m => m.count), 1);

  return (
    <div className="bg-card rounded-xl border p-5 space-y-4">
      <div className="flex items-center gap-2">
        <Activity className="w-5 h-5 text-emerald-500" />
        <h3 className="font-semibold">月度入库趋势</h3>
        <span className="text-xs text-muted-foreground ml-auto">近12个月</span>
      </div>
      {months.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-6">暂无数据</p>
      ) : (
        <div className="relative h-32 w-full">
          <div className="absolute inset-0 flex items-end gap-2">
            {months.map((m, i) => {
              const heightPct = Math.max((m.count / maxCount) * 100, 4);
              return (
                <div
                  key={m.month}
                  className="flex-1 flex flex-col items-center justify-end h-full"
                >
                  <div
                    className={`w-full bg-gradient-to-t ${GRADIENT_COLORS[i % GRADIENT_COLORS.length]} rounded-t-lg shadow-md transition-all duration-300 hover:brightness-110`}
                    style={{ height: `${heightPct}%` }}
                  />
                </div>
              );
            })}
          </div>
          <div className="absolute bottom-0 left-0 right-0 flex items-end gap-2 pointer-events-none">
            {months.map((m) => (
              <div key={m.month} className="flex-1 flex justify-center">
                <span className="text-[10px] text-muted-foreground font-mono">
                  {m.month.slice(5)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function VenueDistribution({ data }: { data: PaperDistributionResponse }) {
  const venues = data.by_venue;
  const maxCount = Math.max(...venues.map(v => v.count), 1);

  return (
    <div className="bg-card rounded-xl border p-5 space-y-4">
      <div className="flex items-center gap-2">
        <Layers className="w-5 h-5 text-amber-500" />
        <h3 className="font-semibold">顶会/期刊分布</h3>
        <span className="text-xs text-muted-foreground ml-auto">Top 5</span>
      </div>
      {venues.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-6">暂无数据</p>
      ) : (
        <div className="space-y-3">
          {venues.slice(0, 5).map((v, i) => (
            <div key={v.venue} className="flex items-center gap-3">
              <span className={`text-lg font-bold w-6 text-right shrink-0 ${i === 0 ? 'text-amber-500' : i === 1 ? 'text-slate-400' : i === 2 ? 'text-orange-400' : 'text-muted-foreground'}`}>
                {i + 1}
              </span>
              <span className="text-sm flex-1 truncate font-medium">{v.venue}</span>
              <div className="w-20 h-2 bg-muted rounded-full overflow-hidden shrink-0 shadow-inner">
                <div
                  className="h-full bg-gradient-to-r from-amber-500 to-orange-500 rounded-full"
                  style={{ width: `${(v.count / maxCount) * 100}%` }}
                />
              </div>
              <span className="text-xs font-bold w-8 text-right shrink-0">{v.count}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ActionSourceStats({ data }: { data: PaperDistributionResponse }) {
  const actions = data.by_action_source;
  const total = actions.reduce((sum, a) => sum + a.count, 0);

  return (
    <div className="bg-card rounded-xl border p-5 space-y-4">
      <div className="flex items-center gap-2">
        <TrendingDown className="w-5 h-5 text-purple-500" />
        <h3 className="font-semibold">入库来源统计</h3>
        <span className="text-xs text-muted-foreground ml-auto">{total} 篇</span>
      </div>
      {actions.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-6">暂无数据</p>
      ) : (
        <div className="space-y-3">
          {actions.map((a) => {
            const pct = total > 0 ? ((a.count / total) * 100).toFixed(0) : 0;
            return (
              <div key={a.raw_source} className="flex items-center gap-3">
                <div className={`w-3 h-3 rounded-full shrink-0 ${SOURCE_COLORS[a.raw_source] || "bg-gray-500"}`} />
                <span className="text-sm flex-1 truncate">{a.source}</span>
                <div className="w-24 h-2 bg-muted rounded-full overflow-hidden shrink-0 shadow-inner">
                  <div
                    className={`h-full ${SOURCE_COLORS[a.raw_source] || "bg-gray-500"} rounded-full`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="text-xs font-bold w-12 text-right shrink-0">{pct}%</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ReadStatusOverview({ data }: { data: PaperDistributionResponse }) {
  const statuses = data.by_status;
  const total = statuses.reduce((sum, s) => sum + s.count, 0);

  return (
    <div className="bg-card rounded-xl border p-5 space-y-4">
      <div className="flex items-center gap-2">
        <BookOpen className="w-5 h-5 text-cyan-500" />
        <h3 className="font-semibold">阅读状态概览</h3>
        <span className="text-xs text-muted-foreground ml-auto">{total} 篇</span>
      </div>
      {statuses.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-6">暂无数据</p>
      ) : (
        <>
          <div className="h-4 bg-muted rounded-full overflow-hidden flex shadow-inner">
            {statuses.map((s) => (
              <div
                key={s.raw_status}
                className={`${STATUS_COLORS[s.raw_status] || "bg-gray-500"} h-full`}
                style={{ width: `${total > 0 ? (s.count / total) * 100 : 0}%` }}
              />
            ))}
          </div>
          <div className="grid grid-cols-3 gap-4">
            {statuses.map((s) => (
              <div key={s.raw_status} className="text-center">
                <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full ${s.raw_status === 'deep_read' ? 'bg-primary/10' : s.raw_status === 'skimmed' ? 'bg-yellow-500/10' : 'bg-slate-100 dark:bg-slate-800'}`}>
                  <div className={`w-2.5 h-2.5 rounded-full ${STATUS_COLORS[s.raw_status] || "bg-gray-500"}`} />
                  <span className="text-xs font-medium">{s.status}</span>
                </div>
                <p className="text-xl font-bold mt-2">{s.count}</p>
                <p className="text-[10px] text-muted-foreground">
                  {total > 0 ? ((s.count / total) * 100).toFixed(0) : 0}%
                </p>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export default function Statistics() {
  const [topicData, setTopicData] = useState<TopicStatsResponse | null>(null);
  const [distData, setDistData] = useState<PaperDistributionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [t, d] = await Promise.all([
        topicApi.stats(),
        topicApi.distribution(),
      ]);
      setTopicData(t);
      setDistData(d);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <p className="text-destructive">{error}</p>
        <button
          type="button"
          onClick={loadData}
          className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
        >
          <RefreshCw className="w-4 h-4" />
          重试
        </button>
      </div>
    );
  }

  const topics = topicData?.topics ?? [];
  const totalPapers = topics.reduce((sum, t) => sum + t.paper_count, 0);
  const totalCitations = topics.reduce((sum, t) => sum + t.total_citations, 0);
  const totalRecent = topics.reduce((sum, t) => sum + t.recent_30d, 0);
  const maxCitations = Math.max(...topics.map(t => t.total_citations), 1);

  return (
    <div className="animate-fade-in space-y-6">
      <div className="page-hero rounded-2xl p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-xl bg-primary/10 p-2.5">
              <BarChart3 className="h-5 w-5 text-primary" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-ink">主题统计</h1>
              <p className="mt-0.5 text-sm text-ink-secondary">论文库数据分析与可视化</p>
            </div>
          </div>
          <button
            type="button"
            onClick={loadData}
            className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
          >
            <RefreshCw className="w-4 h-4" />
            刷新
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={<BookOpen className="h-5 w-5" />}
          label="论文总数"
          value={totalPapers}
          sub={`${topics.length} 个主题`}
          color="primary"
        />
        <StatCard
          icon={<Quote className="h-5 w-5" />}
          label="总引用数"
          value={totalCitations.toLocaleString()}
          color="info"
        />
        <StatCard
          icon={<TrendingUp className="h-5 w-5" />}
          label="30天活跃"
          value={totalRecent}
          sub="新增论文"
          color="success"
        />
        <StatCard
          icon={<Activity className="h-5 w-5" />}
          label="阅读率"
          value={totalPapers > 0 ? Math.round(((topics.reduce((sum, t) => sum + t.status_dist.skimmed + t.status_dist.deep_read, 0)) / totalPapers) * 100) : 0}
          sub="已读论文"
          color="warning"
        />
      </div>

      {distData && (
        <>
          <MonthlyTrend data={distData} />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <YearDistribution data={distData} />
            <SourceDistribution data={distData} />
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <VenueDistribution data={distData} />
            <ActionSourceStats data={distData} />
          </div>
          <ReadStatusOverview data={distData} />
        </>
      )}

      {topics.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-lg font-semibold text-ink">主题对比</h2>
          <div className="bg-card rounded-xl border p-4">
            {topics.map((stat, i) => (
              <CitationBar key={stat.topic_id} stat={stat} max={maxCitations} index={i} />
            ))}
          </div>
        </div>
      )}

      <div className="space-y-4">
        <h2 className="text-lg font-semibold text-ink">主题详情</h2>
        {topics.length === 0 ? (
          <div className="text-center text-muted-foreground py-8">暂无主题数据</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {topics.map((stat) => (
              <TopicCard key={stat.topic_id} stat={stat} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
