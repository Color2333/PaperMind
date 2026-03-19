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
} from "lucide-react";

const SOURCE_COLORS: Record<string, string> = {
  arxiv: "bg-red-500",
  "semantic_scholar": "bg-blue-500",
  reference_import: "bg-green-500",
  unknown: "bg-gray-500",
};

function TopicCard({ stat }: { stat: TopicStats }) {
  const total = stat.status_dist.unread + stat.status_dist.skimmed + stat.status_dist.deep_read;
  const readRate = total > 0 ? ((stat.status_dist.skimmed + stat.status_dist.deep_read) / total * 100).toFixed(0) : 0;

  return (
    <div className="bg-card rounded-lg border p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-medium text-sm">{stat.topic_name}</h3>
        <span className="text-xs text-muted-foreground">{stat.paper_count} 篇</span>
      </div>
      
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="flex items-center gap-1.5">
          <BookOpen className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-muted-foreground">论文</span>
          <span className="ml-auto font-medium">{stat.paper_count}</span>
        </div>
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
        <div className="flex items-center gap-1.5">
          <BarChart3 className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-muted-foreground">阅读率</span>
          <span className="ml-auto font-medium">{readRate}%</span>
        </div>
      </div>

      <div className="space-y-1">
        <div className="flex justify-between text-xs text-muted-foreground">
          <span>阅读进度</span>
          <span>{readRate}%</span>
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
    <div className="flex items-center gap-3">
      <span className="text-xs w-24 truncate">{stat.topic_name}</span>
      <div className="flex-1 h-4 bg-muted rounded-full overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-indigo-500 to-purple-500"
          style={{ width: `${(stat.total_citations / max) * 100}%` }}
        />
      </div>
      <span className="text-xs w-16 text-right">{stat.total_citations.toLocaleString()}</span>
    </div>
  );
}

function YearDistribution({ data }: { data: PaperDistributionResponse }) {
  const years = data.by_year.filter(y => y.year !== "未知").sort((a, b) => b.year.localeCompare(a.year));
  const maxCount = Math.max(...years.map(y => y.count), 1);
  const total = years.reduce((sum, y) => sum + y.count, 0);

  return (
    <div className="bg-card rounded-lg border p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Calendar className="w-4 h-4 text-muted-foreground" />
        <h3 className="font-medium text-sm">论文年份分布</h3>
        <span className="text-xs text-muted-foreground ml-auto">{total} 篇有年份</span>
      </div>
      {years.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-4">暂无年份数据</p>
      ) : (
        <div className="space-y-1.5">
          {years.slice(0, 10).map((y) => (
            <div key={y.year} className="flex items-center gap-3">
              <span className="text-xs w-12">{y.year}</span>
              <div className="flex-1 h-5 bg-muted rounded overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-indigo-400 to-indigo-600"
                  style={{ width: `${(y.count / maxCount) * 100}%` }}
                />
              </div>
              <span className="text-xs w-8 text-right">{y.count}</span>
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
    <div className="bg-card rounded-lg border p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Globe className="w-4 h-4 text-muted-foreground" />
        <h3 className="font-medium text-sm">论文来源分布</h3>
        <span className="text-xs text-muted-foreground ml-auto">{total} 篇</span>
      </div>
      {sources.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-4">暂无来源数据</p>
      ) : (
        <div className="space-y-2">
          {sources.map((s) => (
            <div key={s.raw_source} className="flex items-center gap-3">
              <div className={`w-2 h-2 rounded-full ${SOURCE_COLORS[s.raw_source] || "bg-gray-500"}`} />
              <span className="text-xs flex-1">{s.source}</span>
              <span className="text-xs font-medium">{s.count}</span>
              <span className="text-xs text-muted-foreground w-10 text-right">
                {total > 0 ? ((s.count / total) * 100).toFixed(0) : 0}%
              </span>
            </div>
          ))}
        </div>
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
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">主题统计</h1>
        <button
          type="button"
          onClick={loadData}
          className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
        >
          <RefreshCw className="w-4 h-4" />
          刷新
        </button>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div className="bg-card rounded-lg border p-4">
          <div className="text-2xl font-semibold">{totalPapers}</div>
          <div className="text-sm text-muted-foreground">论文总数</div>
        </div>
        <div className="bg-card rounded-lg border p-4">
          <div className="text-2xl font-semibold">{totalCitations.toLocaleString()}</div>
          <div className="text-sm text-muted-foreground">总引用数</div>
        </div>
        <div className="bg-card rounded-lg border p-4">
          <div className="text-2xl font-semibold">{totalRecent}</div>
          <div className="text-sm text-muted-foreground">30天活跃</div>
        </div>
      </div>

      {distData && (
        <div className="grid grid-cols-2 gap-4">
          <YearDistribution data={distData} />
          <SourceDistribution data={distData} />
        </div>
      )}

      {topics.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-lg font-medium">主题对比</h2>
          <div className="bg-card rounded-lg border p-4 space-y-2">
            {topics.map((stat) => (
              <CitationBar key={stat.topic_id} stat={stat} max={maxCitations} />
            ))}
          </div>
        </div>
      )}

      <div className="space-y-4">
        <h2 className="text-lg font-medium">主题详情</h2>
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
