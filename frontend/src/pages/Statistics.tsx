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
  "unread": "bg-muted-foreground/30",
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
    <div className="bg-card rounded-xl border p-4 space-y-3 hover-lift">
      <div className="flex items-center justify-between">
        <h3 className="font-medium text-sm truncate flex-1 mr-2">{stat.topic_name}</h3>
        <span className="text-xs text-muted-foreground shrink-0">{stat.paper_count} 篇</span>
      </div>
      
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="flex items-center gap-1.5">
          <Quote className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-muted-foreground">引用</span>
          <span className="ml-auto font-medium">{stat.total_citations.toLocaleString()}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <TrendingUp className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-muted-foreground">活跃度</span>
          <span className="ml-auto font-medium">{stat.recent_30d}</span>
        </div>
      </div>

      <div className="space-y-1">
        <div className="flex justify-between text-xs text-muted-foreground">
          <span>阅读率 {readRate}%</span>
        </div>
        <div className="h-1.5 bg-muted rounded-full overflow-hidden flex">
          {total > 0 && (
            <>
              <div
                className="bg-primary h-full"
                style={{ width: `${(stat.status_dist.deep_read / total) * 100}%` }}
              />
              <div
                className="bg-yellow-500 h-full"
                style={{ width: `${(stat.status_dist.skimmed / total) * 100}%` }}
              />
              <div
                className="bg-muted-foreground/30 h-full"
                style={{ width: `${(stat.status_dist.unread / total) * 100}%` }}
              />
            </>
          )}
        </div>
        <div className="flex justify-between text-[10px] text-muted-foreground">
          <span>精读 {stat.status_dist.deep_read}</span>
          <span>粗读 {stat.status_dist.skimmed}</span>
          <span>未读 {stat.status_dist.unread}</span>
        </div>
      </div>
    </div>
  );
}

function CitationBar({ stat, max }: { stat: TopicStats; max: number }) {
  return (
    <div className="flex items-center gap-3 py-1.5">
      <span className="text-xs w-24 truncate shrink-0">{stat.topic_name}</span>
      <div className="flex-1 h-3 bg-muted rounded-full overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-indigo-500 to-purple-500"
          style={{ width: `${(stat.total_citations / max) * 100}%` }}
        />
      </div>
      <span className="text-xs w-16 text-right shrink-0">{stat.total_citations.toLocaleString()}</span>
    </div>
  );
}

function YearDistribution({ data }: { data: PaperDistributionResponse }) {
  const years = data.by_year.filter(y => y.year !== "未知").sort((a, b) => b.year.localeCompare(a.year));
  const maxCount = Math.max(...years.map(y => y.count), 1);

  return (
    <div className="bg-card rounded-xl border p-5 space-y-3">
      <div className="flex items-center gap-2">
        <Calendar className="w-4 h-4 text-muted-foreground" />
        <h3 className="font-medium text-sm">论文年份分布</h3>
        <span className="text-xs text-muted-foreground ml-auto">{years.reduce((s, y) => s + y.count, 0)} 篇</span>
      </div>
      {years.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-4">暂无年份数据</p>
      ) : (
        <div className="space-y-2">
          {years.slice(0, 8).map((y) => (
            <div key={y.year} className="flex items-center gap-3">
              <span className="text-xs w-12 shrink-0">{y.year}</span>
              <div className="flex-1 h-5 bg-muted rounded overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-indigo-400 to-indigo-600"
                  style={{ width: `${(y.count / maxCount) * 100}%` }}
                />
              </div>
              <span className="text-xs w-8 text-right shrink-0">{y.count}</span>
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
    <div className="bg-card rounded-xl border p-5 space-y-3">
      <div className="flex items-center gap-2">
        <Globe className="w-4 h-4 text-muted-foreground" />
        <h3 className="font-medium text-sm">论文来源</h3>
        <span className="text-xs text-muted-foreground ml-auto">{total} 篇</span>
      </div>
      {sources.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-4">暂无来源数据</p>
      ) : (
        <div className="space-y-2">
          {sources.map((s) => (
            <div key={s.raw_source} className="flex items-center gap-3">
              <div className={`w-2 h-2 rounded-full shrink-0 ${SOURCE_COLORS[s.raw_source] || "bg-gray-500"}`} />
              <span className="text-xs flex-1 truncate">{s.source}</span>
              <span className="text-xs font-medium shrink-0">{s.count}</span>
              <span className="text-xs text-muted-foreground w-10 text-right shrink-0">
                {total > 0 ? ((s.count / total) * 100).toFixed(0) : 0}%
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MonthlyTrend({ data }: { data: PaperDistributionResponse }) {
  const months = data.by_month;
  const maxCount = Math.max(...months.map(m => m.count), 1);

  return (
    <div className="bg-card rounded-xl border p-5 space-y-3">
      <div className="flex items-center gap-2">
        <Activity className="w-4 h-4 text-muted-foreground" />
        <h3 className="font-medium text-sm">月度入库趋势</h3>
        <span className="text-xs text-muted-foreground ml-auto">近12个月</span>
      </div>
      {months.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-4">暂无数据</p>
      ) : (
        <div className="flex items-end gap-1.5 h-24">
          {months.map((m) => (
            <div key={m.month} className="flex-1 flex flex-col items-center gap-1.5">
              <div
                className="w-full bg-gradient-to-t from-indigo-500 to-indigo-400 rounded-sm"
                style={{ height: `${Math.max((m.count / maxCount) * 80, 4)}px` }}
              />
              <span className="text-[9px] text-muted-foreground">{m.month.slice(5)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function VenueDistribution({ data }: { data: PaperDistributionResponse }) {
  const venues = data.by_venue;
  const maxCount = Math.max(...venues.map(v => v.count), 1);

  return (
    <div className="bg-card rounded-xl border p-5 space-y-3">
      <div className="flex items-center gap-2">
        <Layers className="w-4 h-4 text-muted-foreground" />
        <h3 className="font-medium text-sm">顶会/期刊分布</h3>
        <span className="text-xs text-muted-foreground ml-auto">Top 10</span>
      </div>
      {venues.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-4">暂无数据</p>
      ) : (
        <div className="space-y-2">
          {venues.slice(0, 10).map((v) => (
            <div key={v.venue} className="flex items-center gap-3">
              <span className="text-xs w-20 truncate shrink-0">{v.venue}</span>
              <div className="flex-1 h-3 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-emerald-500 to-teal-500"
                  style={{ width: `${(v.count / maxCount) * 100}%` }}
                />
              </div>
              <span className="text-xs w-8 text-right shrink-0">{v.count}</span>
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
    <div className="bg-card rounded-xl border p-5 space-y-3">
      <div className="flex items-center gap-2">
        <TrendingDown className="w-4 h-4 text-muted-foreground" />
        <h3 className="font-medium text-sm">入库来源统计</h3>
        <span className="text-xs text-muted-foreground ml-auto">{total} 篇</span>
      </div>
      {actions.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-4">暂无数据</p>
      ) : (
        <div className="space-y-2">
          {actions.map((a) => (
            <div key={a.raw_source} className="flex items-center gap-3">
              <div className={`w-2 h-2 rounded-full shrink-0 ${SOURCE_COLORS[a.raw_source] || "bg-gray-500"}`} />
              <span className="text-xs flex-1 truncate">{a.source}</span>
              <span className="text-xs font-medium shrink-0">{a.count}</span>
              <span className="text-xs text-muted-foreground w-10 text-right shrink-0">
                {total > 0 ? ((a.count / total) * 100).toFixed(0) : 0}%
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ReadStatusOverview({ data }: { data: PaperDistributionResponse }) {
  const statuses = data.by_status;
  const total = statuses.reduce((sum, s) => sum + s.count, 0);

  return (
    <div className="bg-card rounded-xl border p-5 space-y-3">
      <div className="flex items-center gap-2">
        <BookOpen className="w-4 h-4 text-muted-foreground" />
        <h3 className="font-medium text-sm">阅读状态概览</h3>
        <span className="text-xs text-muted-foreground ml-auto">{total} 篇</span>
      </div>
      {statuses.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-4">暂无数据</p>
      ) : (
        <>
          <div className="h-2.5 bg-muted rounded-full overflow-hidden flex">
            {statuses.map((s) => (
              <div
                key={s.raw_status}
                className={`${STATUS_COLORS[s.raw_status] || "bg-gray-500"} h-full`}
                style={{ width: `${total > 0 ? (s.count / total) * 100 : 0}%` }}
              />
            ))}
          </div>
          <div className="flex justify-between text-xs">
            {statuses.map((s) => (
              <div key={s.raw_status} className="flex items-center gap-1.5">
                <div className={`w-2 h-2 rounded-full ${STATUS_COLORS[s.raw_status] || "bg-gray-500"}`} />
                <span className="text-muted-foreground">{s.status}</span>
                <span className="font-medium">{s.count}</span>
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
          <h2 className="text-lg font-medium text-ink">主题对比</h2>
          <div className="bg-card rounded-xl border p-4 space-y-1">
            {topics.map((stat) => (
              <CitationBar key={stat.topic_id} stat={stat} max={maxCitations} />
            ))}
          </div>
        </div>
      )}

      <div className="space-y-4">
        <h2 className="text-lg font-medium text-ink">主题详情</h2>
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
