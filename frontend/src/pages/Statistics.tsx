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
  unread: "bg-slate-400",
  skimmed: "bg-yellow-500",
  deep_read: "bg-primary",
};

const SOURCE_COLORS: Record<string, string> = {
  arxiv: "bg-red-500",
  semantic_scholar: "bg-blue-500",
  reference_import: "bg-green-500",
  unknown: "bg-gray-500",
  initial_import: "bg-purple-500",
  manual_collect: "bg-orange-500",
  auto_collect: "bg-cyan-500",
  agent_collect: "bg-pink-500",
  subscription_ingest: "bg-indigo-500",
};

function SectionCard({
  title,
  icon,
  action,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="border-border bg-surface rounded-2xl border p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {icon}
          <h3 className="text-ink text-sm font-semibold">{title}</h3>
        </div>
        {action}
      </div>
      {children}
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  sub,
  color,
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
    <div
      className={`stat-gradient-${color} border-border bg-surface rounded-2xl border p-5 text-left shadow-sm`}
    >
      <div className="flex items-center justify-between">
        <div className={`rounded-xl p-2.5 ${iconColors[color]} bg-white/60 dark:bg-white/5`}>
          {icon}
        </div>
      </div>
      <p className="text-ink mt-3 text-2xl font-bold tracking-tight">{value}</p>
      <p className="text-ink-tertiary mt-0.5 text-xs">{label}</p>
      {sub && <p className="text-ink-secondary text-xs">{sub}</p>}
    </div>
  );
}

function TopicCard({ stat }: { stat: TopicStats }) {
  const total = stat.status_dist.unread + stat.status_dist.skimmed + stat.status_dist.deep_read;
  const readRate =
    total > 0
      ? (((stat.status_dist.skimmed + stat.status_dist.deep_read) / total) * 100).toFixed(0)
      : 0;

  return (
    <div className="bg-surface border-border hover-lift space-y-3 rounded-xl border p-4 transition-all">
      <div className="flex items-center justify-between">
        <h3 className="mr-3 flex-1 truncate text-sm font-semibold">{stat.topic_name}</h3>
        <span className="text-muted-foreground bg-page shrink-0 rounded-full px-2 py-1 text-xs font-medium">
          {stat.paper_count} 篇
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="flex items-center gap-2">
          <div className="bg-primary/10 flex h-7 w-7 items-center justify-center rounded-lg">
            <Quote className="text-primary h-3.5 w-3.5" />
          </div>
          <div>
            <p className="text-base font-bold">{stat.total_citations.toLocaleString()}</p>
            <p className="text-muted-foreground text-[10px]">总引用</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="bg-success/10 flex h-7 w-7 items-center justify-center rounded-lg">
            <TrendingUp className="text-success h-3.5 w-3.5" />
          </div>
          <div>
            <p className="text-base font-bold">{stat.recent_30d}</p>
            <p className="text-muted-foreground text-[10px]">30天活跃</p>
          </div>
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex justify-between text-xs">
          <span className="text-muted-foreground">阅读进度</span>
          <span className="text-primary font-medium">{readRate}%</span>
        </div>
        <div className="bg-page flex h-2 overflow-hidden rounded-full shadow-inner">
          {total > 0 && (
            <>
              <div
                className="bg-primary h-full rounded-l-full"
                style={{ width: `${(stat.status_dist.deep_read / total) * 100}%` }}
              />
              <div
                className="h-full bg-yellow-500"
                style={{ width: `${(stat.status_dist.skimmed / total) * 100}%` }}
              />
              <div
                className="h-full rounded-r-full bg-slate-300 dark:bg-slate-600"
                style={{ width: `${(stat.status_dist.unread / total) * 100}%` }}
              />
            </>
          )}
        </div>
        <div className="text-muted-foreground flex justify-between text-[10px]">
          <span className="flex items-center gap-1">
            <span className="bg-primary h-1.5 w-1.5 rounded-full" />
            精读 {stat.status_dist.deep_read}
          </span>
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-yellow-500" />
            粗读 {stat.status_dist.skimmed}
          </span>
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-slate-300 dark:bg-slate-600" />
            未读 {stat.status_dist.unread}
          </span>
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
      <span className="text-ink w-24 shrink-0 truncate text-sm font-medium">{stat.topic_name}</span>
      <div className="bg-page relative h-7 flex-1 overflow-hidden rounded-lg shadow-inner">
        <div
          className={`h-full ${c.bar} bar-animate rounded-lg transition-all duration-700 ease-out`}
          style={{ width: `${(stat.paper_count / max) * 100}%` }}
        />
        <span className="text-ink absolute top-1/2 right-3 -translate-y-1/2 text-xs font-bold">
          {stat.paper_count}
        </span>
      </div>
    </div>
  );
}

function MonthlyTrend({ data }: { data: PaperDistributionResponse }) {
  const months = data.by_month;
  const maxCount = Math.max(...months.map((m) => m.count), 1);
  const total = months.reduce((sum, m) => sum + m.count, 0);
  const avg = months.length > 0 ? Math.round(total / months.length) : 0;
  const latest = months[months.length - 1]?.count ?? 0;
  const prev = months[months.length - 2]?.count ?? 0;
  const trend = prev > 0 ? Math.round(((latest - prev) / prev) * 100) : 0;

  return (
    <SectionCard title="月度入库趋势" icon={<Activity className="text-primary h-4 w-4" />}>
      {months.length === 0 ? (
        <div className="text-muted-foreground py-8 text-center text-sm">暂无数据</div>
      ) : (
        <div className="flex gap-6">
          <div className="flex min-w-[140px] flex-col justify-between">
            <div>
              <p className="text-ink text-3xl font-bold">{total.toLocaleString()}</p>
              <p className="text-muted-foreground text-xs">近{months.length}月总计</p>
            </div>
            <div className="space-y-2">
              <div className="flex items-baseline gap-2">
                <span className="text-ink text-lg font-semibold">{avg}</span>
                <span className="text-muted-foreground text-xs">月均</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span
                  className={`text-sm font-semibold ${trend >= 0 ? "text-success" : "text-error"}`}
                >
                  {trend >= 0 ? "+" : ""}
                  {trend}%
                </span>
                <span className="text-muted-foreground text-xs">环比</span>
              </div>
            </div>
          </div>
          <div className="flex h-32 flex-1 items-end gap-1.5">
            {months.map((m, i) => {
              const heightPct = (m.count / maxCount) * 100;
              const isLatest = i === months.length - 1;
              return (
                <div
                  key={m.month}
                  className="group relative flex h-full flex-1 flex-col items-center justify-end"
                >
                  <div
                    className={`w-full rounded-t transition-all duration-500 ${
                      isLatest ? "bg-primary" : "bg-primary/30 hover:bg-primary/50"
                    }`}
                    style={{ height: `${Math.max(heightPct, 4)}%` }}
                  />
                  <div className="absolute bottom-full z-10 mb-2 hidden group-hover:block">
                    <div className="bg-ink text-surface rounded-lg px-2 py-1 text-xs whitespace-nowrap">
                      <p className="font-semibold">{m.count} 篇</p>
                      <p className="text-[10px] opacity-70">{m.month}</p>
                    </div>
                  </div>
                  {isLatest && (
                    <span className="text-primary absolute -top-5 text-[10px] font-semibold">
                      {m.count}
                    </span>
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
  const years = data.by_year
    .filter((y) => y.year !== "未知")
    .sort((a, b) => b.year.localeCompare(a.year));
  const maxCount = Math.max(...years.map((y) => y.count), 1);

  const colors = [
    "bg-primary",
    "bg-info",
    "bg-success",
    "bg-warning",
    "bg-pink-500",
    "bg-purple-500",
  ];

  return (
    <SectionCard title="论文年份分布" icon={<Calendar className="text-primary h-4 w-4" />}>
      {years.length === 0 ? (
        <div className="text-muted-foreground py-8 text-center text-sm">暂无年份数据</div>
      ) : (
        <div className="space-y-3">
          {years.slice(0, 6).map((y, i) => (
            <div key={y.year} className="flex items-center gap-3">
              <span className="text-muted-foreground w-10 shrink-0 font-mono text-sm">
                {y.year}
              </span>
              <div className="bg-page relative h-7 flex-1 overflow-hidden rounded-lg shadow-inner">
                <div
                  className={`h-full ${colors[i % colors.length]} bar-animate rounded-lg`}
                  style={{ width: `${(y.count / maxCount) * 100}%` }}
                />
                <span className="text-ink absolute top-1/2 right-3 -translate-y-1/2 text-xs font-bold">
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
    <SectionCard title="论文来源" icon={<Globe className="text-info h-4 w-4" />}>
      {sources.length === 0 ? (
        <div className="text-muted-foreground py-8 text-center text-sm">暂无来源数据</div>
      ) : (
        <div className="space-y-3">
          {sources.map((s) => {
            const pct = total > 0 ? ((s.count / total) * 100).toFixed(0) : 0;
            return (
              <div key={s.raw_source} className="flex items-center gap-3">
                <div
                  className={`h-2.5 w-2.5 shrink-0 rounded-full ${SOURCE_COLORS[s.raw_source] || "bg-gray-500"}`}
                />
                <span className="flex-1 truncate text-sm">{s.source}</span>
                <div className="bg-page h-1.5 w-20 shrink-0 overflow-hidden rounded-full shadow-inner">
                  <div
                    className={`h-full ${SOURCE_COLORS[s.raw_source] || "bg-gray-500"} bar-animate rounded-full`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="w-10 shrink-0 text-right text-xs font-bold">{pct}%</span>
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
  const maxCount = Math.max(...venues.map((v) => v.count), 1);

  const medals = ["text-amber-500", "text-slate-400", "text-orange-400"];

  return (
    <SectionCard title="顶会/期刊分布" icon={<Layers className="text-warning h-4 w-4" />}>
      {venues.length === 0 ? (
        <div className="text-muted-foreground py-8 text-center text-sm">暂无数据</div>
      ) : (
        <div className="space-y-3">
          {venues.slice(0, 5).map((v, i) => (
            <div key={v.venue} className="flex items-center gap-3">
              <span
                className={`w-6 shrink-0 text-right text-lg font-bold ${i < 3 ? medals[i] : "text-muted-foreground"}`}
              >
                {i + 1}
              </span>
              <span className="flex-1 truncate text-sm font-medium">{v.venue}</span>
              <div className="bg-page h-1.5 w-16 shrink-0 overflow-hidden rounded-full shadow-inner">
                <div
                  className="bg-warning/70 bar-animate h-full rounded-full"
                  style={{ width: `${(v.count / maxCount) * 100}%` }}
                />
              </div>
              <span className="w-8 shrink-0 text-right text-xs font-bold">{v.count}</span>
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
        <div className="text-muted-foreground py-8 text-center text-sm">暂无数据</div>
      ) : (
        <div className="space-y-3">
          {actions.map((a) => {
            const pct = total > 0 ? ((a.count / total) * 100).toFixed(0) : 0;
            return (
              <div key={a.raw_source} className="flex items-center gap-3">
                <div
                  className={`h-2.5 w-2.5 shrink-0 rounded-full ${SOURCE_COLORS[a.raw_source] || "bg-gray-500"}`}
                />
                <span className="flex-1 truncate text-sm">{a.source}</span>
                <div className="bg-page h-1.5 w-20 shrink-0 overflow-hidden rounded-full shadow-inner">
                  <div
                    className={`h-full ${SOURCE_COLORS[a.raw_source] || "bg-gray-500"} bar-animate rounded-full`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="w-10 shrink-0 text-right text-xs font-bold">{pct}%</span>
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
        <div className="text-muted-foreground py-8 text-center text-sm">暂无数据</div>
      ) : (
        <>
          <div className="bg-page mb-4 flex h-3 overflow-hidden rounded-full shadow-inner">
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
                <div
                  className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 ${
                    s.raw_status === "deep_read"
                      ? "bg-primary/10"
                      : s.raw_status === "skimmed"
                        ? "bg-yellow-500/10"
                        : "bg-slate-100 dark:bg-slate-800"
                  }`}
                >
                  <div
                    className={`h-2 w-2 rounded-full ${STATUS_COLORS[s.raw_status] || "bg-gray-500"}`}
                  />
                  <span className="text-xs font-medium">{s.status}</span>
                </div>
                <p className="mt-2 text-xl font-bold">{s.count}</p>
                <p className="text-muted-foreground text-[10px]">
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
      const [t, d] = await Promise.all([topicApi.stats(), topicApi.distribution()]);
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
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="text-muted-foreground h-8 w-8 animate-spin" />
      </div>
    );
  }

  const topics = topicData?.topics ?? [];
  const totalPapers = topics.reduce((sum, t) => sum + t.paper_count, 0);
  const totalCitations = topics.reduce((sum, t) => sum + t.total_citations, 0);
  const maxPaperCount = Math.max(...topics.map((t) => t.paper_count), 1);

  return (
    <div className="animate-fade-in space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="bg-primary/10 rounded-xl p-2.5">
            <BarChart3 className="text-primary h-5 w-5" />
          </div>
          <div>
            <h1 className="text-ink text-2xl font-bold">统计分析</h1>
            <p className="text-ink-secondary mt-0.5 text-sm">主题与论文数据总览</p>
          </div>
        </div>
        <button
          type="button"
          onClick={loadData}
          className="border-border bg-surface text-ink-secondary hover:bg-hover flex cursor-pointer items-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium transition-colors"
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
            value={topics.filter((t) => t.recent_30d > 0).length}
            sub="30天内有新增"
            color="warning"
          />
        </div>
      )}

      {distData && (
        <>
          <MonthlyTrend data={distData} />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <YearDistribution data={distData} />
            <SourceDistribution data={distData} />
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <VenueDistribution data={distData} />
            <ActionSourceStats data={distData} />
          </div>
          <ReadStatusOverview data={distData} />
        </>
      )}

      {topics.length > 0 && (
        <div className="space-y-4">
          <SectionCard title="主题对比" icon={<BarChart3 className="text-primary h-4 w-4" />}>
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
          <SectionCard title="主题详情" icon={<BookOpen className="text-primary h-4 w-4" />}>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
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
