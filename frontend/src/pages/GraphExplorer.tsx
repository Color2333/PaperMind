/**
 * Graph Explorer - 知识图谱探索（自动加载+推荐关键词）
 * @author Bamzc
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { Button, Badge, Spinner } from "@/components/ui";
import { graphApi, topicApi, todayApi, type TodaySummary } from "@/services/api";
import type { Topic, CitationTree, TimelineResponse, GraphQuality, EvolutionResponse, SurveyResponse } from "@/types";
import {
  Search, Network, Clock, BarChart3, TrendingUp, BookOpen, Star, ArrowRight,
  ArrowDown, ArrowUp, Layers, Compass, FileText, Lightbulb, HelpCircle,
  Tag, Rss, Flame,
} from "lucide-react";

const TABS = [
  { id: "timeline", label: "时间线", icon: Clock },
  { id: "citation", label: "引用树", icon: Network },
  { id: "quality", label: "质量分析", icon: BarChart3 },
  { id: "evolution", label: "演化趋势", icon: TrendingUp },
  { id: "survey", label: "综述生成", icon: FileText },
] as const;

export default function GraphExplorer() {
  const [activeTab, setActiveTab] = useState("timeline");
  const [keyword, setKeyword] = useState("");
  const [paperId, setPaperId] = useState("");
  const [timelineData, setTimelineData] = useState<TimelineResponse | null>(null);
  const [citationData, setCitationData] = useState<CitationTree | null>(null);
  const [qualityData, setQualityData] = useState<GraphQuality | null>(null);
  const [evolutionData, setEvolutionData] = useState<EvolutionResponse | null>(null);
  const [surveyData, setSurveyData] = useState<SurveyResponse | null>(null);
  const [loading, setLoading] = useState(false);

  /* 推荐数据 */
  const [topics, setTopics] = useState<Topic[]>([]);
  const [hotKeywords, setHotKeywords] = useState<{ keyword: string; count: number }[]>([]);
  const [initLoading, setInitLoading] = useState(true);
  const [activeKeyword, setActiveKeyword] = useState<string | null>(null);
  const autoLoaded = useRef(false);

  /* 页面加载：获取订阅主题和热词 */
  useEffect(() => {
    (async () => {
      setInitLoading(true);
      try {
        const [topicRes, todayRes] = await Promise.all([
          topicApi.list(true).catch(() => ({ items: [] as Topic[] })),
          todayApi.summary().catch(() => null as TodaySummary | null),
        ]);
        setTopics(topicRes.items);
        if (todayRes?.hot_keywords) setHotKeywords(todayRes.hot_keywords);
      } catch {} finally { setInitLoading(false); }
    })();
  }, []);

  /* 自动加载第一个关键词的时间线 */
  useEffect(() => {
    if (autoLoaded.current || initLoading) return;
    const firstKw = topics[0]?.name || hotKeywords[0]?.keyword;
    if (firstKw) {
      autoLoaded.current = true;
      queryByKeyword(firstKw);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initLoading, topics, hotKeywords]);

  const queryByKeyword = useCallback(async (kw: string) => {
    setKeyword(kw);
    setActiveKeyword(kw);
    setLoading(true);
    try {
      switch (activeTab) {
        case "timeline": setTimelineData(await graphApi.timeline(kw)); break;
        case "quality": setQualityData(await graphApi.quality(kw)); break;
        case "evolution": setEvolutionData(await graphApi.evolution(kw)); break;
        case "survey": setSurveyData(await graphApi.survey(kw)); break;
        default: setTimelineData(await graphApi.timeline(kw)); setActiveTab("timeline"); break;
      }
    } catch {} finally { setLoading(false); }
  }, [activeTab]);

  const handleQuery = useCallback(async () => {
    setLoading(true);
    setActiveKeyword(keyword.trim() || null);
    try {
      switch (activeTab) {
        case "timeline": if (keyword.trim()) setTimelineData(await graphApi.timeline(keyword)); break;
        case "citation": if (paperId.trim()) setCitationData(await graphApi.citationTree(paperId)); break;
        case "quality": if (keyword.trim()) setQualityData(await graphApi.quality(keyword)); break;
        case "evolution": if (keyword.trim()) setEvolutionData(await graphApi.evolution(keyword)); break;
        case "survey": if (keyword.trim()) setSurveyData(await graphApi.survey(keyword)); break;
      }
    } catch {} finally { setLoading(false); }
  }, [activeTab, keyword, paperId]);

  /* 收集所有可用的推荐关键词（去重） */
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

  const hasResults = (activeTab === "timeline" && timelineData) ||
    (activeTab === "citation" && citationData) ||
    (activeTab === "quality" && qualityData) ||
    (activeTab === "evolution" && evolutionData) ||
    (activeTab === "survey" && surveyData);

  return (
    <div className="animate-fade-in space-y-6">
      {/* 页面头 */}
      <div className="page-hero rounded-2xl p-6">
        <div className="flex items-center gap-3">
          <div className="rounded-xl bg-primary/10 p-2.5"><Compass className="h-5 w-5 text-primary" /></div>
          <div>
            <h1 className="text-2xl font-bold text-ink">知识图谱</h1>
            <p className="mt-0.5 text-sm text-ink-secondary">探索引用关系、领域时间线和知识脉络</p>
          </div>
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
                onClick={() => queryByKeyword(item.keyword)}
                className={`group flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-medium transition-all ${
                  activeKeyword === item.keyword
                    ? "bg-primary text-white shadow-sm"
                    : "bg-page text-ink-secondary hover:bg-primary/8 hover:text-primary"
                }`}
              >
                {item.source === "topic" ? (
                  <Rss className="h-3 w-3" />
                ) : (
                  <Flame className="h-3 w-3" />
                )}
                {item.keyword}
                {item.count != null && (
                  <span className={`rounded-full px-1.5 text-[10px] ${
                    activeKeyword === item.keyword
                      ? "bg-white/20 text-white"
                      : "bg-border-light text-ink-tertiary"
                  }`}>
                    {item.count}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* 功能标签 */}
      <div className="flex gap-1 rounded-2xl bg-page p-1.5">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex flex-1 items-center justify-center gap-2 rounded-xl py-2.5 text-xs font-medium transition-all ${
              activeTab === tab.id
                ? "bg-surface text-primary shadow-sm"
                : "text-ink-tertiary hover:text-ink"
            }`}
          >
            <tab.icon className="h-3.5 w-3.5" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* 搜索 */}
      <div className="rounded-2xl border border-border bg-surface p-5 shadow-sm">
        <div className="flex gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-tertiary" />
            {activeTab === "citation" ? (
              <input
                placeholder="输入论文 ID..."
                value={paperId}
                onChange={(e) => setPaperId(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleQuery(); }}
                className="h-11 w-full rounded-xl border border-border bg-page pl-10 pr-4 text-sm text-ink placeholder:text-ink-placeholder focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            ) : (
              <input
                placeholder="输入关键词: transformer, reinforcement learning..."
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleQuery(); }}
                className="h-11 w-full rounded-xl border border-border bg-page pl-10 pr-4 text-sm text-ink placeholder:text-ink-placeholder focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            )}
          </div>
          <Button icon={<Search className="h-4 w-4" />} onClick={handleQuery} loading={loading}>查询</Button>
        </div>
      </div>

      {/* 加载状态 */}
      {(loading || initLoading) && <Spinner text={initLoading ? "加载推荐数据..." : "查询中..."} />}

      {/* 无结果提示 */}
      {!loading && !initLoading && !hasResults && (
        <div className="flex flex-col items-center rounded-2xl border border-dashed border-border py-16 text-center">
          <div className="rounded-2xl bg-page p-5">
            <Compass className="h-8 w-8 text-ink-tertiary/30" />
          </div>
          <p className="mt-4 text-sm text-ink-tertiary">
            {suggestedKeywords.length > 0
              ? "点击上方关键词快速探索，或在搜索框输入自定义关键词"
              : "输入关键词开始探索知识图谱"}
          </p>
        </div>
      )}

      {/* 结果 */}
      {!loading && activeTab === "timeline" && timelineData && <TimelineView data={timelineData} />}
      {!loading && activeTab === "citation" && citationData && <CitationTreeView data={citationData} />}
      {!loading && activeTab === "quality" && qualityData && <QualityView data={qualityData} />}
      {!loading && activeTab === "evolution" && evolutionData && <EvolutionView data={evolutionData} />}
      {!loading && activeTab === "survey" && surveyData && <SurveyView data={surveyData} />}
    </div>
  );
}

/* ========== 时间线 ========== */
function TimelineView({ data }: { data: TimelineResponse }) {
  return (
    <div className="space-y-6 animate-fade-in">
      {data.seminal.length > 0 && (
        <Section title="开创性论文" icon={<Star className="h-4 w-4 text-warning" />} desc="该领域最具影响力的论文">
          <div className="space-y-2">
            {data.seminal.map((e) => (
              <div key={e.paper_id} className="hover-lift flex items-center justify-between rounded-xl border border-warning/20 bg-warning-light p-4">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Star className="h-4 w-4 shrink-0 text-warning" />
                    <span className="truncate text-sm font-medium text-ink">{e.title}</span>
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
        </Section>
      )}

      <Section title="时间线" icon={<Clock className="h-4 w-4 text-primary" />} desc={`${data.timeline.length} 篇论文`}>
        <div className="relative ml-3 border-l-2 border-border-light pl-5 space-y-1">
          {data.timeline.map((e) => (
            <div key={e.paper_id} className="relative rounded-xl px-3 py-2 transition-colors hover:bg-hover">
              <span className="absolute -left-[1.625rem] top-1/2 h-2.5 w-2.5 -translate-y-1/2 rounded-full border-2 border-primary bg-surface" />
              <div className="flex items-center gap-3">
                <span className="w-10 shrink-0 text-xs font-semibold text-primary">{e.year}</span>
                <span className="min-w-0 flex-1 truncate text-sm text-ink">{e.title}</span>
                <div className="flex shrink-0 gap-2 text-[10px] text-ink-tertiary">
                  <span>↓{e.indegree}</span><span>↑{e.outdegree}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </Section>

      {data.milestones.length > 0 && (
        <Section title="里程碑" icon={<Lightbulb className="h-4 w-4 text-info" />}>
          <div className="grid gap-2 sm:grid-cols-2">
            {data.milestones.map((m) => (
              <div key={m.paper_id} className="flex items-center gap-3 rounded-xl bg-info-light p-3">
                <Lightbulb className="h-4 w-4 shrink-0 text-info" />
                <span className="flex-1 truncate text-sm text-ink">{m.title}</span>
                <span className="text-xs font-medium text-info">{m.year}</span>
              </div>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}

/* ========== 引用树 ========== */
function CitationTreeView({ data }: { data: CitationTree }) {
  return (
    <Section title={data.root_title || "引用树"} icon={<Network className="h-4 w-4 text-primary" />}
      desc={`${data.nodes.length} 节点 · ${data.edge_count} 引用边`}>
      <div className="space-y-4">
        {data.ancestors.length > 0 && (
          <div>
            <p className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-widest text-ink-tertiary">
              <ArrowUp className="h-3 w-3" /> 被引用
            </p>
            <div className="space-y-1">
              {data.ancestors.map((edge, i) => {
                const node = data.nodes.find((n) => n.id === edge.source);
                return (
                  <div key={i} className="flex items-center gap-3 rounded-xl bg-page px-4 py-2.5">
                    <Badge variant="info">L{edge.depth}</Badge>
                    <span className="flex-1 truncate text-sm text-ink">{node?.title || edge.source}</span>
                    {node?.year && <span className="text-xs text-ink-tertiary">{node.year}</span>}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <div className="flex items-center gap-3 rounded-2xl border-2 border-primary/30 bg-primary/5 px-5 py-4">
          <Network className="h-5 w-5 text-primary" />
          <span className="text-base font-bold text-ink">{data.root_title}</span>
        </div>

        {data.descendants.length > 0 && (
          <div>
            <p className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-widest text-ink-tertiary">
              <ArrowDown className="h-3 w-3" /> 引用了
            </p>
            <div className="space-y-1">
              {data.descendants.map((edge, i) => {
                const node = data.nodes.find((n) => n.id === edge.target);
                return (
                  <div key={i} className="flex items-center gap-3 rounded-xl bg-page px-4 py-2.5">
                    <Badge variant="success">L{edge.depth}</Badge>
                    <span className="flex-1 truncate text-sm text-ink">{node?.title || edge.target}</span>
                    {node?.year && <span className="text-xs text-ink-tertiary">{node.year}</span>}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </Section>
  );
}

/* ========== 质量分析 ========== */
function QualityView({ data }: { data: GraphQuality }) {
  const metrics = [
    { label: "节点数", value: data.node_count, icon: Layers, color: "primary" },
    { label: "边数", value: data.edge_count, icon: Network, color: "info" },
    { label: "密度", value: data.density.toFixed(4), icon: BarChart3, color: "warning" },
    { label: "连通比例", value: `${(data.connected_node_ratio * 100).toFixed(1)}%`, icon: TrendingUp, color: "success" },
    { label: "日期覆盖", value: `${(data.publication_date_coverage * 100).toFixed(1)}%`, icon: Clock, color: "info" },
  ] as const;

  return (
    <Section title="图谱质量" icon={<BarChart3 className="h-4 w-4 text-primary" />} desc={`关键词: ${data.keyword}`}>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {metrics.map((m) => (
          <div key={m.label} className={`stat-gradient-${m.color} rounded-2xl border border-border p-4`}>
            <m.icon className={`h-4 w-4 text-${m.color} mb-2`} />
            <p className="text-xl font-bold text-ink">{m.value}</p>
            <p className="text-xs text-ink-tertiary">{m.label}</p>
          </div>
        ))}
      </div>
    </Section>
  );
}

/* ========== 演化趋势 ========== */
function EvolutionView({ data }: { data: EvolutionResponse }) {
  return (
    <div className="space-y-6 animate-fade-in">
      <Section title="趋势摘要" icon={<TrendingUp className="h-4 w-4 text-primary" />}>
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
      </Section>

      <Section title="年度分布" icon={<BarChart3 className="h-4 w-4 text-info" />}>
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
      </Section>
    </div>
  );
}

/* ========== 综述 ========== */
function SurveyView({ data }: { data: SurveyResponse }) {
  return (
    <div className="space-y-6 animate-fade-in">
      <Section title="综述" icon={<FileText className="h-4 w-4 text-primary" />} desc={`关键词: ${data.keyword}`}>
        <div className="rounded-xl bg-page p-5">
          <p className="text-sm leading-relaxed text-ink-secondary">{data.summary.overview}</p>
        </div>
      </Section>

      {data.summary.stages.length > 0 && (
        <Section title="发展阶段" icon={<ArrowRight className="h-4 w-4 text-primary" />}>
          <div className="relative ml-3 border-l-2 border-border-light pl-5 space-y-2">
            {data.summary.stages.map((s, i) => (
              <div key={i} className="relative rounded-xl bg-page px-4 py-3">
                <span className="absolute -left-[1.625rem] top-4 h-2.5 w-2.5 rounded-full border-2 border-primary bg-surface" />
                <p className="text-sm text-ink-secondary">{s}</p>
              </div>
            ))}
          </div>
        </Section>
      )}

      {data.summary.reading_list.length > 0 && (
        <Section title="推荐阅读" icon={<BookOpen className="h-4 w-4 text-info" />}>
          <div className="grid gap-2 sm:grid-cols-2">
            {data.summary.reading_list.map((item, i) => (
              <div key={i} className="flex items-center gap-2 rounded-xl bg-info-light p-3 text-sm text-ink-secondary">
                <BookOpen className="h-3.5 w-3.5 shrink-0 text-info" />{item}
              </div>
            ))}
          </div>
        </Section>
      )}

      {data.summary.open_questions.length > 0 && (
        <Section title="开放问题" icon={<HelpCircle className="h-4 w-4 text-warning" />}>
          <div className="space-y-2">
            {data.summary.open_questions.map((q, i) => (
              <div key={i} className="flex items-start gap-3 rounded-xl bg-warning-light p-3">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-warning/20 text-[10px] font-bold text-warning">
                  {i + 1}
                </span>
                <p className="text-sm text-ink-secondary">{q}</p>
              </div>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}

/* ========== 通用 Section ========== */
function Section({ title, icon, desc, children }: { title: string; icon: React.ReactNode; desc?: string; children: React.ReactNode }) {
  return (
    <div className="animate-fade-in rounded-2xl border border-border bg-surface p-5 shadow-sm">
      <div className="mb-4 flex items-center gap-2">
        {icon}
        <div>
          <h3 className="text-sm font-semibold text-ink">{title}</h3>
          {desc && <p className="text-xs text-ink-tertiary">{desc}</p>}
        </div>
      </div>
      {children}
    </div>
  );
}
