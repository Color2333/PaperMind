/**
 * Statistics - 主题统计分析
 * @author Color2333
 */
import { useEffect, useState, useCallback } from "react";
import { topicApi } from "@/services/api";
import type { TopicStats, TopicStatsResponse, PaperDistributionResponse } from "@/types";
import {
  BookOpen,
  Quote,
  TrendingUp,
  Loader2,
  RefreshCw,
  Calendar,
  Globe,
  Activity,
  Layers,
  BarChart3,
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

function SectionCard({ title, icon, action, children }: {
  title: string;
  icon: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {icon}
          <h3 className="text-sm font-semibold text-ink">{title}</h3>
        </div>
        {action}
      </div>
      {children}
    </div>
  );
}

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
    <div className="bg-surface rounded-xl border border-border p-4 space-y-3 hover-lift transition-all">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-sm truncate flex-1 mr-3">{stat.topic_name}</h3>
        <span className="text-xs font-medium text-muted-foreground bg-page px-2 py-1 rounded-full shrink-0">{stat.paper_count} 篇</span>
      </div>
      
      <div className="grid grid-cols-2 gap-3">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center">
            <Quote className="w-3.5 h-3.5 text-primary" />
          </div>
          <div>
            <p className="text-base font-bold">{stat.total_citations.toLocaleString()}</p>
            <p className="text-[10px] text-muted-foreground">总引用</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-success/10 flex items-center justify-center">
            <TrendingUp className="w-3.5 h-3.5 text-success" />
          </div>
          <div>
            <p className="text-base font-bold">{stat.recent_30d}</p>
            <p className="text-[10px] text-muted-foreground">30天活跃</p>
          </div>
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex justify-between text-xs">
          <span className="text-muted-foreground">阅读进度</span>
          <span className="font-medium text-primary">{readRate}%</span>
        </div>
        <div className="h-2 bg-page rounded-full overflow-hidden flex shadow-inner">
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
        <div className="flex justify-between text-[10px] text-muted-foreground">
          <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-primary" />精读 {stat.status_dist.deep_read}</span>
          <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-yellow-500" />粗读 {stat.status_dist.skimmed}</span>
          <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-slate-300 dark:bg-slate-600" />未读 {stat.status_dist.unread}</span>
        </div>
      </div>
    </div>
  );
}

function CitationBar({ stat, max, index }: { stat: TopicStats; max: number; index: number }) {
  const colors = [
    { bar: "bg-primary/80", glow: "bg-primary/20" },
    { bar: "bg-info/80", glow: "bg-info/20" },
    { bar: "bg-success/80", glow: "bg-success/20" },
    { bar: "bg-warning/80", glow: "bg-warning/20" },
  ];
  const c = colors[index % colors.length];

  return (
    <div className="group flex items-center gap-4 py-2.5">
      <span className="text-sm w-24 truncate shrink-0 font-medium text-ink">{stat.topic_name}</span>
      <div className="flex-1 h-7 bg-page rounded-lg overflow-hidden shadow-inner relative">
        <div
          className={`h-full ${c.bar} rounded-lg transition-all duration-700 ease-out bar-animate`}
          style={{ width: `${(stat.paper_count / max) * 100}%` }}
        />
        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-bold text-ink">
          {stat.paper_count}
        </span>
      </div>
    </div>
  );
}

function MonthlyTrend({ data }: { data: PaperDistributionResponse }) {
  const months = data.by_month;
  const maxCount = Math.max(...months.map(m => m.count), 1);
  const total = months.reduce((sum, m) => sum + m.count, 0);
  const avg = months.length > 0 ? Math.round(total / months.length) : 0;
  const latest = months[months.length - 1]?.count ?? 0;
  const prev = months[months.length - 2]?.count ?? 0;
  const trend = prev > 0 ? Math.round(((latest - prev) / prev) * 100) : 0;

  return (
    <SectionCard title="月度入库趋势" icon={<Activity className="h-4 w-4 text-primary" />}>
      {months.length === 0 ? (
        <div className="py-8 text-center text-sm text-muted-foreground">暂无数据</div>
      ) : (
        <div className="flex gap-6">
          <div className="flex flex-col justify-between min-w-[140px]">
            <div>
              <p className="text-3xl font-bold text-ink">{total.toLocaleString()}</p>
              <p className="text-xs text-muted-foreground">近{months.length}月总计</p>
            </div>
            <div className="space-y-2">
              <div className="flex items-baseline gap-2">
                <span className="text-lg font-semibold text-ink">{avg}</span>
                <span className="text-xs text-muted-foreground">月均</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className={`text-sm font-semibold ${trend >= 0 ? 'text-success' : 'text-error'}`}>
                  {trend >= 0 ? '+' : ''}{trend}%
                </span>
                <span className="text-xs text-muted-foreground">环比</span>
              </div>
            </div>
          </div>
          <div className="flex-1 flex items-end gap-1.5 h-32">
            {months.map((m, i) => {
              const heightPct = (m.count / maxCount) * 100;
              const isLatest = i === months.length - 1;
              return (
                <div key={m.month} className="flex-1 group relative flex flex-col items-center justify-end h-full">
                  <div
                    className={`w-full rounded-t transition-all duration-500 ${
                      isLatest 
                        ? 'bg-primary' 
                        : 'bg-primary/30 hover:bg-primary/50'
                    }`}
                    style={{ height: `${Math.max(heightPct, 4)}%` }}
                  />
                  <div className="absolute bottom-full mb-2 hidden group-hover:block z-10">
                    <div className="bg-ink text-surface text-xs rounded-lg px-2 py-1 whitespace-nowrap">
                      <p className="font-semibold">{m.count} 篇</p>
                      <p className="text-[10px] opacity-70">{m.month}</p>
                    </div>
                  </div>
                  {isLatest && (
                    <span className="absolute -top-5 text-[10px] font-semibold text-primary">{m.count}</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </SectionCard>
  );
}

function YearDistribution({ data }: { data: PaperDistributionResponse }) {
  const years = data.by_year.filter(y => y.year !== "未知").sort((a, b) => b.year.localeCompare(a.year));
  const maxCount = Math.max(...years.map(y => y.count), 1);

  const colors = ["bg-primary", "bg-info", "bg-success", "bg-warning", "bg-pink-500", "bg-purple-500"];

  return (
    <SectionCard title="论文年份分布" icon={<Calendar className="h-4 w-4 text-primary" />}>
      {years.length === 0 ? (
        <div className="py-8 text-center text-sm text-muted-foreground">暂无年份数据</div>
      ) : (
        <div className="space-y-3">
          {years.slice(0, 6).map((y, i) => (
            <div key={y.year} className="flex items-center gap-3">
              <span className="text-sm font-mono w-10 shrink-0 text-muted-foreground">{y.year}</span>
              <div className="flex-1 h-7 bg-page rounded-lg overflow-hidden shadow-inner relative">
                <div
                  className={`h-full ${colors[i % colors.length]} rounded-lg bar-animate`}
                  style={{ width: `${(y.count / maxCount) * 100}%` }}
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-bold text-ink">
                  {y.count}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function SourceDistribution({ data }: { data: PaperDistributionResponse }) {
  const sources = data.by_source;
  const total = sources.reduce((sum, s) => sum + s.count, 0);

  return (
    <SectionCard title="论文来源" icon={<Globe className="h-4 w-4 text-info" />}>
      {sources.length === 0 ? (
        <div className="py-8 text-center text-sm text-muted-foreground">暂无来源数据</div>
      ) : (
        <div className="space-y-3">
          {sources.map((s) => {
            const pct = total > 0 ? ((s.count / total) * 100).toFixed(0) : 0;
            return (
              <div key={s.raw_source} className="flex items-center gap-3">
                <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${SOURCE_COLORS[s.raw_source] || "bg-gray-500"}`} />
                <span className="text-sm flex-1 truncate">{s.source}</span>
                <div className="w-20 h-1.5 bg-page rounded-full overflow-hidden shrink-0 shadow-inner">
                  <div
                    className={`h-full ${SOURCE_COLORS[s.raw_source] || "bg-gray-500"} rounded-full bar-animate`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="text-xs font-bold w-10 text-right shrink-0">{pct}%</span>
              </div>
            );
          })}
        </div>
      )}
    </SectionCard>
  );
}

function VenueDistribution({ data }: { data: PaperDistributionResponse }) {
  const venues = data.by_venue;
  const maxCount = Math.max(...venues.map(v => v.count), 1);

  const medals = ["text-amber-500", "text-slate-400", "text-orange-400"];

  return (
    <SectionCard title="顶会/期刊分布" icon={<Layers className="h-4 w-4 text-warning" />}>
      {venues.length === 0 ? (
        <div className="py-8 text-center text-sm text-muted-foreground">暂无数据</div>
      ) : (
        <div className="space-y-3">
          {venues.slice(0, 5).map((v, i) => (
            <div key={v.venue} className="flex items-center gap-3">
              <span className={`text-lg font-bold w-6 text-right shrink-0 ${i < 3 ? medals[i] : "text-muted-foreground"}`}>
                {i + 1}
              </span>
              <span className="text-sm flex-1 truncate font-medium">{v.venue}</span>
              <div className="w-16 h-1.5 bg-page rounded-full overflow-hidden shrink-0 shadow-inner">
                <div
                  className="h-full bg-warning/70 rounded-full bar-animate"
                  style={{ width: `${(v.count / maxCount) * 100}%` }}
                />
              </div>
              <span className="text-xs font-bold w-8 text-right shrink-0">{v.count}</span>
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function ActionSourceStats({ data }: { data: PaperDistributionResponse }) {
  const actions = data.by_action_source;
  const total = actions.reduce((sum, a) => sum + a.count, 0);

  return (
    <SectionCard title="入库来源统计" icon={<Activity className="h-4 w-4 text-purple-500" />}>
      {actions.length === 0 ? (
        <div className="py-8 text-center text-sm text-muted-foreground">暂无数据</div>
      ) : (
        <div className="space-y-3">
          {actions.map((a) => {
            const pct = total > 0 ? ((a.count / total) * 100).toFixed(0) : 0;
            return (
              <div key={a.raw_source} className="flex items-center gap-3">
                <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${SOURCE_COLORS[a.raw_source] || "bg-gray-500"}`} />
                <span className="text-sm flex-1 truncate">{a.source}</span>
                <div className="w-20 h-1.5 bg-page rounded-full overflow-hidden shrink-0 shadow-inner">
                  <div
                    className={`h-full ${SOURCE_COLORS[a.raw_source] || "bg-gray-500"} rounded-full bar-animate`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="text-xs font-bold w-10 text-right shrink-0">{pct}%</span>
              </div>
            );
          })}
        </div>
      )}
    </SectionCard>
  );
}

function ReadStatusOverview({ data }: { data: PaperDistributionResponse }) {
  const statuses = data.by_status;
  const total = statuses.reduce((sum, s) => sum + s.count, 0);

  return (
    <SectionCard title="阅读状态概览" icon={<BookOpen className="h-4 w-4 text-cyan-500" />}>
      {statuses.length === 0 ? (
        <div className="py-8 text-center text-sm text-muted-foreground">暂无数据</div>
      ) : (
        <>
          <div className="h-3 bg-page rounded-full overflow-hidden flex shadow-inner mb-4">
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
                <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full ${
                  s.raw_status === 'deep_read' ? 'bg-primary/10' : 
                  s.raw_status === 'skimmed' ? 'bg-yellow-500/10' : 
                  'bg-slate-100 dark:bg-slate-800'
                }`}>
                  <div className={`w-2 h-2 rounded-full ${STATUS_COLORS[s.raw_status] || "bg-gray-500"}`} />
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
    </SectionCard>
  );
}

export default function Statistics() {
  const [topicData, setTopicData] = useState<TopicStatsResponse | null>(null);
  const [distData, setDistData] = useState<PaperDistributionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
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
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const topics = topicData?.topics ?? [];
  const totalPapers = topics.reduce((sum, t) => sum + t.paper_count, 0);
  const totalCitations = topics.reduce((sum, t) => sum + t.total_citations, 0);
  const maxPaperCount = Math.max(...topics.map(t => t.paper_count), 1);

  return (
    <div className="animate-fade-in space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="rounded-xl bg-primary/10 p-2.5">
            <BarChart3 className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-ink">统计分析</h1>
            <p className="mt-0.5 text-sm text-ink-secondary">主题与论文数据总览</p>
          </div>
        </div>
        <button
          type="button"
          onClick={loadData}
          className="flex items-center gap-2 rounded-lg border border-border bg-surface px-4 py-2 text-sm font-medium text-ink-secondary transition-colors hover:bg-hover cursor-pointer"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          刷新
        </button>
      </div>

      {topics.length > 0 && (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard
            icon={<BookOpen className="h-5 w-5" />}
            label="论文总量"
            value={totalPapers.toLocaleString()}
            sub={`${topics.length} 个主题`}
            color="primary"
          />
          <StatCard
            icon={<Quote className="h-5 w-5" />}
            label="总引用数"
            value={totalCitations.toLocaleString()}
            sub="跨所有主题"
            color="info"
          />
          <StatCard
            icon={<TrendingUp className="h-5 w-5" />}
            label="总引用数"
            value={totalCitations.toLocaleString()}
            sub="跨所有主题"
            color="success"
          />
          <StatCard
            icon={<Activity className="h-5 w-5" />}
            label="活跃主题"
            value={topics.filter(t => t.recent_30d > 0).length}
            sub="30天内有新增"
            color="warning"
          />
        </div>
      )}

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
          <SectionCard title="主题对比" icon={<BarChart3 className="h-4 w-4 text-primary" />}>
            <div className="space-y-1">
              {topics.map((stat, i) => (
                <CitationBar key={stat.topic_id} stat={stat} max={maxPaperCount} index={i} />
              ))}
            </div>
          </SectionCard>
        </div>
      )}

      {topics.length > 0 && (
        <div className="space-y-4">
          <SectionCard title="主题详情" icon={<BookOpen className="h-4 w-4 text-primary" />}>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {topics.map((stat) => (
                <TopicCard key={stat.topic_id} stat={stat} />
              ))}
            </div>
          </SectionCard>
        </div>
      )}
    </div>
  );
}
