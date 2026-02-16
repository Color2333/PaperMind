/**
 * Graph Explorer - 知识图谱探索
 * 覆盖 API: /graph/citation-tree, /graph/timeline, /graph/quality, /graph/evolution/weekly, /graph/survey
 * @author Bamzc
 */
import { useState } from "react";
import { Card, CardHeader, Button, Input, Tabs, Badge, Spinner, Empty } from "@/components/ui";
import { graphApi } from "@/services/api";
import type {
  CitationTree,
  TimelineResponse,
  GraphQuality,
  EvolutionResponse,
  SurveyResponse,
} from "@/types";
import {
  Search,
  Network,
  Clock,
  BarChart3,
  TrendingUp,
  BookOpen,
  Star,
  ArrowRight,
  ArrowDown,
  ArrowUp,
  Layers,
} from "lucide-react";

const graphTabs = [
  { id: "timeline", label: "时间线" },
  { id: "citation", label: "引用树" },
  { id: "quality", label: "质量分析" },
  { id: "evolution", label: "演化趋势" },
  { id: "survey", label: "综述生成" },
];

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

  const handleQuery = async () => {
    setLoading(true);
    try {
      switch (activeTab) {
        case "timeline": {
          if (!keyword.trim()) return;
          const res = await graphApi.timeline(keyword);
          setTimelineData(res);
          break;
        }
        case "citation": {
          if (!paperId.trim()) return;
          const res = await graphApi.citationTree(paperId);
          setCitationData(res);
          break;
        }
        case "quality": {
          if (!keyword.trim()) return;
          const res = await graphApi.quality(keyword);
          setQualityData(res);
          break;
        }
        case "evolution": {
          if (!keyword.trim()) return;
          const res = await graphApi.evolution(keyword);
          setEvolutionData(res);
          break;
        }
        case "survey": {
          if (!keyword.trim()) return;
          const res = await graphApi.survey(keyword);
          setSurveyData(res);
          break;
        }
      }
    } catch {
      /* 静默 */
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="animate-fade-in space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-ink">Graph Explorer</h1>
        <p className="mt-1 text-sm text-ink-secondary">
          探索论文引用关系、领域时间线和知识脉络
        </p>
      </div>

      <Tabs tabs={graphTabs} active={activeTab} onChange={setActiveTab} />

      {/* 搜索输入 */}
      <Card>
        <div className="flex gap-3">
          {activeTab === "citation" ? (
            <div className="flex-1">
              <Input
                placeholder="输入论文 ID..."
                value={paperId}
                onChange={(e) => setPaperId(e.target.value)}
              />
            </div>
          ) : (
            <div className="flex-1">
              <Input
                placeholder="输入关键词，如: transformer, reinforcement learning..."
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
              />
            </div>
          )}
          <Button
            icon={<Search className="h-4 w-4" />}
            onClick={handleQuery}
            loading={loading}
          >
            查询
          </Button>
        </div>
      </Card>

      {loading && <Spinner text="查询中..." />}

      {/* 结果展示 */}
      {!loading && activeTab === "timeline" && timelineData && (
        <TimelineView data={timelineData} />
      )}
      {!loading && activeTab === "citation" && citationData && (
        <CitationTreeView data={citationData} />
      )}
      {!loading && activeTab === "quality" && qualityData && (
        <QualityView data={qualityData} />
      )}
      {!loading && activeTab === "evolution" && evolutionData && (
        <EvolutionView data={evolutionData} />
      )}
      {!loading && activeTab === "survey" && surveyData && (
        <SurveyView data={surveyData} />
      )}
    </div>
  );
}

function TimelineView({ data }: { data: TimelineResponse }) {
  return (
    <div className="space-y-4 animate-fade-in">
      {/* Seminal Papers */}
      {data.seminal.length > 0 && (
        <Card>
          <CardHeader
            title="开创性论文"
            description="该领域最具影响力的论文"
          />
          <div className="space-y-2">
            {data.seminal.map((entry) => (
              <div
                key={entry.paper_id}
                className="flex items-center justify-between rounded-lg bg-warning-light px-4 py-3"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Star className="h-4 w-4 shrink-0 text-warning" />
                    <span className="truncate text-sm font-medium text-ink">
                      {entry.title}
                    </span>
                  </div>
                  {entry.why_seminal && (
                    <p className="mt-1 pl-6 text-xs text-ink-secondary">
                      {entry.why_seminal}
                    </p>
                  )}
                </div>
                <div className="shrink-0 text-right">
                  <span className="text-sm font-semibold text-warning">
                    {entry.seminal_score.toFixed(2)}
                  </span>
                  <p className="text-xs text-ink-tertiary">{entry.year}</p>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 时间线 */}
      <Card>
        <CardHeader
          title="时间线"
          description={`${data.timeline.length} 篇论文`}
        />
        <div className="space-y-1">
          {data.timeline.map((entry) => (
            <div
              key={entry.paper_id}
              className="flex items-center gap-4 rounded-lg px-3 py-2 hover:bg-hover"
            >
              <span className="w-10 shrink-0 text-xs font-medium text-ink-tertiary">
                {entry.year}
              </span>
              <div className="h-2 w-2 shrink-0 rounded-full bg-primary" />
              <span className="min-w-0 flex-1 truncate text-sm text-ink">
                {entry.title}
              </span>
              <div className="flex shrink-0 gap-2 text-xs text-ink-tertiary">
                <span title="引用入度">↓{entry.indegree}</span>
                <span title="引用出度">↑{entry.outdegree}</span>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Milestones */}
      {data.milestones.length > 0 && (
        <Card>
          <CardHeader title="里程碑论文" />
          <div className="space-y-2">
            {data.milestones.map((m) => (
              <div
                key={m.paper_id}
                className="flex items-center gap-3 rounded-lg bg-info-light px-4 py-2.5"
              >
                <Clock className="h-4 w-4 shrink-0 text-info" />
                <span className="text-sm text-ink">{m.title}</span>
                <span className="ml-auto text-xs text-ink-tertiary">{m.year}</span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function CitationTreeView({ data }: { data: CitationTree }) {
  return (
    <div className="space-y-4 animate-fade-in">
      <Card>
        <CardHeader
          title={data.root_title || "引用树"}
          description={`${data.nodes.length} 个节点 · ${data.edge_count} 条引用边`}
        />

        {/* 节点列表 */}
        <div className="space-y-3">
          {/* 祖先 */}
          {data.ancestors.length > 0 && (
            <div>
              <p className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-ink-tertiary">
                <ArrowUp className="h-3.5 w-3.5" />
                被引用 (Ancestors)
              </p>
              <div className="space-y-1">
                {data.ancestors.map((edge, i) => {
                  const node = data.nodes.find((n) => n.id === edge.source);
                  return (
                    <div
                      key={i}
                      className="flex items-center gap-3 rounded-lg bg-page px-3 py-2"
                    >
                      <Badge variant="info">深度 {edge.depth}</Badge>
                      <span className="truncate text-sm text-ink">
                        {node?.title || edge.source}
                      </span>
                      {node?.year && (
                        <span className="ml-auto text-xs text-ink-tertiary">
                          {node.year}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 根节点 */}
          <div className="flex items-center gap-3 rounded-lg border-2 border-primary/30 bg-primary-50 px-4 py-3">
            <Network className="h-5 w-5 text-primary" />
            <span className="font-semibold text-ink">{data.root_title}</span>
          </div>

          {/* 后裔 */}
          {data.descendants.length > 0 && (
            <div>
              <p className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-ink-tertiary">
                <ArrowDown className="h-3.5 w-3.5" />
                引用了 (Descendants)
              </p>
              <div className="space-y-1">
                {data.descendants.map((edge, i) => {
                  const node = data.nodes.find((n) => n.id === edge.target);
                  return (
                    <div
                      key={i}
                      className="flex items-center gap-3 rounded-lg bg-page px-3 py-2"
                    >
                      <Badge variant="success">深度 {edge.depth}</Badge>
                      <span className="truncate text-sm text-ink">
                        {node?.title || edge.target}
                      </span>
                      {node?.year && (
                        <span className="ml-auto text-xs text-ink-tertiary">
                          {node.year}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}

function QualityView({ data }: { data: GraphQuality }) {
  const metrics = [
    { label: "节点数", value: data.node_count, icon: <Layers className="h-4 w-4" /> },
    { label: "边数", value: data.edge_count, icon: <Network className="h-4 w-4" /> },
    { label: "密度", value: data.density.toFixed(4), icon: <BarChart3 className="h-4 w-4" /> },
    {
      label: "连通节点比例",
      value: `${(data.connected_node_ratio * 100).toFixed(1)}%`,
      icon: <TrendingUp className="h-4 w-4" />,
    },
    {
      label: "发表日期覆盖率",
      value: `${(data.publication_date_coverage * 100).toFixed(1)}%`,
      icon: <Clock className="h-4 w-4" />,
    },
  ];

  return (
    <Card className="animate-fade-in">
      <CardHeader
        title="图谱质量"
        description={`关键词: ${data.keyword}`}
      />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
        {metrics.map((m) => (
          <div key={m.label} className="rounded-lg bg-page p-4">
            <div className="mb-2 text-ink-tertiary">{m.icon}</div>
            <p className="text-xl font-bold text-ink">{m.value}</p>
            <p className="text-xs text-ink-secondary">{m.label}</p>
          </div>
        ))}
      </div>
    </Card>
  );
}

function EvolutionView({ data }: { data: EvolutionResponse }) {
  return (
    <div className="space-y-4 animate-fade-in">
      {/* 趋势摘要 */}
      <Card>
        <CardHeader title="演化趋势摘要" />
        <div className="space-y-3">
          <div className="rounded-lg bg-page p-4">
            <p className="text-xs font-medium uppercase tracking-wider text-ink-tertiary">
              趋势总结
            </p>
            <p className="mt-1 text-sm text-ink-secondary">
              {data.summary.trend_summary}
            </p>
          </div>
          <div className="rounded-lg bg-page p-4">
            <p className="text-xs font-medium uppercase tracking-wider text-ink-tertiary">
              阶段转变信号
            </p>
            <p className="mt-1 text-sm text-ink-secondary">
              {data.summary.phase_shift_signals}
            </p>
          </div>
          <div className="rounded-lg bg-primary-50 p-4">
            <p className="text-xs font-medium uppercase tracking-wider text-primary">
              下周关注点
            </p>
            <p className="mt-1 text-sm font-medium text-ink">
              {data.summary.next_week_focus}
            </p>
          </div>
        </div>
      </Card>

      {/* 年度桶 */}
      <Card>
        <CardHeader title="年度分布" />
        <div className="space-y-2">
          {data.year_buckets.map((bucket) => (
            <div
              key={bucket.year}
              className="flex items-center gap-4 rounded-lg bg-page px-4 py-3"
            >
              <span className="w-12 shrink-0 text-sm font-semibold text-ink">
                {bucket.year}
              </span>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <div
                    className="h-2 rounded-full bg-primary"
                    style={{
                      width: `${Math.min(100, bucket.paper_count * 3)}%`,
                    }}
                  />
                  <span className="text-xs text-ink-secondary">
                    {bucket.paper_count} 篇
                  </span>
                </div>
                {bucket.top_titles.length > 0 && (
                  <p className="mt-1 truncate text-xs text-ink-tertiary">
                    {bucket.top_titles[0]}
                  </p>
                )}
              </div>
              <span className="shrink-0 text-xs text-ink-tertiary">
                avg: {bucket.avg_seminal_score.toFixed(2)}
              </span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function SurveyView({ data }: { data: SurveyResponse }) {
  return (
    <div className="space-y-4 animate-fade-in">
      <Card>
        <CardHeader title="综述" description={`关键词: ${data.keyword}`} />
        <div className="space-y-4">
          <div className="rounded-lg bg-page p-4">
            <p className="text-xs font-medium uppercase tracking-wider text-ink-tertiary">
              概览
            </p>
            <p className="mt-2 text-sm leading-relaxed text-ink-secondary">
              {data.summary.overview}
            </p>
          </div>

          {data.summary.stages.length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-medium text-ink">发展阶段</h4>
              <div className="space-y-1.5">
                {data.summary.stages.map((stage, i) => (
                  <div
                    key={i}
                    className="flex items-start gap-2.5 rounded-lg bg-page px-3 py-2"
                  >
                    <ArrowRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                    <span className="text-sm text-ink-secondary">{stage}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {data.summary.reading_list.length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-medium text-ink">推荐阅读</h4>
              <div className="space-y-1">
                {data.summary.reading_list.map((item, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-2 rounded-lg bg-info-light px-3 py-2 text-sm text-ink-secondary"
                  >
                    <BookOpen className="h-3.5 w-3.5 shrink-0 text-info" />
                    {item}
                  </div>
                ))}
              </div>
            </div>
          )}

          {data.summary.open_questions.length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-medium text-ink">开放问题</h4>
              <div className="space-y-1">
                {data.summary.open_questions.map((q, i) => (
                  <div
                    key={i}
                    className="flex items-start gap-2 rounded-lg bg-warning-light px-3 py-2 text-sm text-ink-secondary"
                  >
                    <span className="shrink-0 font-medium text-warning">
                      Q{i + 1}
                    </span>
                    {q}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
