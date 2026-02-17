/**
 * Dashboard - 系统总览（现代精致版）
 * @author Bamzc
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Badge, Spinner } from "@/components/ui";
import { systemApi, metricsApi, pipelineApi, todayApi, type TodaySummary } from "@/services/api";
import { formatUSD, formatDuration, timeAgo } from "@/lib/utils";
import type { SystemStatus, CostMetrics, PipelineRun } from "@/types";
import {
  Activity,
  FileText,
  DollarSign,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  RefreshCw,
  TrendingUp,
  Zap,
  Sparkles,
  ArrowUpRight,
  BarChart3,
  Cpu,
  BookOpen,
} from "lucide-react";

const STAGE_LABELS: Record<string, string> = {
  skim: "粗读分析",
  deep_dive: "深度精读",
  rag: "RAG 问答",
  reasoning_chain: "推理链分析",
  vision_figure: "图表解读",
  agent_chat: "Agent 对话",
  embed: "向量化",
  graph_evolution: "演化分析",
  graph_survey: "综述生成",
  graph_research_gaps: "研究空白",
  wiki_paper: "论文 Wiki",
  wiki_outline: "Wiki 大纲",
  wiki_section: "Wiki 章节",
  wiki_overview: "Wiki 概述",
  keyword_suggest: "关键词建议",
};

export default function Dashboard() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [costs, setCosts] = useState<CostMetrics | null>(null);
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [today, setToday] = useState<TodaySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [s, c, r, t] = await Promise.all([
        systemApi.status(),
        metricsApi.costs(7),
        pipelineApi.runs(10),
        todayApi.summary().catch(() => null),
      ]);
      setStatus(s);
      setCosts(c);
      setRuns(r.items);
      setToday(t);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadData(); }, []);

  if (loading) return <Spinner text="加载系统状态..." />;
  if (error) {
    return (
      <div className="flex flex-col items-center py-20">
        <div className="rounded-2xl bg-error-light p-6">
          <XCircle className="mx-auto h-10 w-10 text-error" />
        </div>
        <p className="mt-4 text-sm text-error">{error}</p>
        <Button variant="secondary" className="mt-4" onClick={loadData}>重试</Button>
      </div>
    );
  }

  const isHealthy = status?.health?.status === "ok";
  const todayNew = today?.today_new ?? 0;
  const weekNew = today?.week_new ?? 0;
  const totalPapers = today?.total_papers ?? (status?.counts?.papers_latest_200 ?? 0);

  return (
    <div className="animate-fade-in space-y-6">
      {/* Hero 区域 */}
      <div className="page-hero rounded-2xl p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-xl bg-primary/10 p-2.5"><Activity className="h-5 w-5 text-primary" /></div>
            <div>
              <h1 className="text-2xl font-bold text-ink">Dashboard</h1>
              <p className="mt-0.5 text-sm text-ink-secondary">系统总览与运行状态</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className={`flex items-center gap-2 rounded-full px-4 py-1.5 text-xs font-medium ${
              isHealthy ? "bg-success-light text-success" : "bg-error-light text-error"
            }`}>
              <span className={`h-2 w-2 rounded-full ${isHealthy ? "bg-success" : "bg-error"}`} />
              {isHealthy ? "系统正常" : "系统异常"}
            </div>
            <Button
              variant="secondary"
              size="sm"
              icon={<RefreshCw className="h-3.5 w-3.5" />}
              onClick={loadData}
            >
              刷新
            </Button>
          </div>
        </div>
      </div>

      {/* 统计卡片 */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          icon={<FileText className="h-5 w-5" />}
          label="今日新增"
          value={todayNew}
          sub={`本周 ${weekNew} 篇`}
          color="primary"
          onClick={() => navigate("/papers")}
        />
        <StatCard
          icon={<BookOpen className="h-5 w-5" />}
          label="论文总量"
          value={totalPapers}
          sub={`${status?.counts?.enabled_topics ?? 0} 个订阅`}
          color="info"
          onClick={() => navigate("/papers")}
        />
        <StatCard
          icon={<Cpu className="h-5 w-5" />}
          label="Pipeline"
          value={status?.counts?.runs_latest_50 ?? 0}
          sub={`${status?.counts?.failed_runs_latest_50 ?? 0} 个失败`}
          color="warning"
          onClick={() => navigate("/pipelines")}
        />
        <StatCard
          icon={<DollarSign className="h-5 w-5" />}
          label="7日成本"
          value={formatUSD(costs?.total_cost_usd ?? 0)}
          sub={`${costs?.calls ?? 0} 次调用`}
          color="success"
        />
      </div>

      {/* 主内容区：成本 + 活动 */}
      <div className="grid gap-6 lg:grid-cols-5">
        {/* 成本分析 - 更宽 */}
        <div className="space-y-6 lg:col-span-3">
          <SectionCard title="成本分析" icon={<BarChart3 className="h-4 w-4 text-primary" />}>
            {costs && costs.by_stage.length > 0 ? (
              <div className="space-y-5">
                <div className="space-y-3">
                  <p className="text-xs font-medium uppercase tracking-widest text-ink-tertiary">按阶段</p>
                  {costs.by_stage.map((s) => {
                    const maxCost = Math.max(...costs.by_stage.map((x) => x.total_cost_usd), 0.001);
                    const pct = Math.max((s.total_cost_usd / maxCost) * 100, 3);
                    return (
                      <div key={s.stage} className="group">
                        <div className="mb-1 flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <Zap className="h-3 w-3 text-warning" />
                            <span className="text-sm text-ink">{STAGE_LABELS[s.stage] || s.stage}</span>
                          </div>
                          <div className="flex items-baseline gap-2">
                            <span className="text-sm font-semibold text-ink">{formatUSD(s.total_cost_usd)}</span>
                            <span className="text-xs text-ink-tertiary">{s.calls}次</span>
                          </div>
                        </div>
                        <div className="h-2 w-full overflow-hidden rounded-full bg-page">
                          <div
                            className="bar-animate h-full rounded-full bg-gradient-to-r from-warning to-warning/60"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>

                {costs.by_model.length > 0 && (
                  <div className="space-y-3">
                    <p className="text-xs font-medium uppercase tracking-widest text-ink-tertiary">按模型</p>
                    {costs.by_model.map((m) => {
                      const maxCost = Math.max(...costs.by_model.map((x) => x.total_cost_usd), 0.001);
                      const pct = Math.max((m.total_cost_usd / maxCost) * 100, 3);
                      return (
                        <div key={`${m.provider}-${m.model}`} className="group">
                          <div className="mb-1 flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <TrendingUp className="h-3 w-3 text-info" />
                              <span className="text-sm text-ink">{m.provider}/{m.model}</span>
                            </div>
                            <span className="text-sm font-semibold text-ink">{formatUSD(m.total_cost_usd)}</span>
                          </div>
                          <div className="h-2 w-full overflow-hidden rounded-full bg-page">
                            <div
                              className="bar-animate h-full rounded-full bg-gradient-to-r from-info to-info/60"
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}

                <div className="flex items-center justify-between rounded-xl bg-page px-4 py-3">
                  <span className="text-sm text-ink-secondary">Token 用量</span>
                  <div className="flex gap-4 text-xs">
                    <span className="text-ink-tertiary">
                      输入 <strong className="text-ink">{(costs.input_tokens ?? 0).toLocaleString()}</strong>
                    </span>
                    <span className="text-ink-tertiary">
                      输出 <strong className="text-ink">{(costs.output_tokens ?? 0).toLocaleString()}</strong>
                    </span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="py-8 text-center text-sm text-ink-tertiary">暂无成本数据</div>
            )}
          </SectionCard>
        </div>

        {/* 活动记录 */}
        <div className="space-y-6 lg:col-span-2">
          <SectionCard title="最近活动" icon={<Activity className="h-4 w-4 text-primary" />}>
            {runs.length > 0 ? (
              <div className="space-y-1">
                {runs.map((run) => (
                  <button
                    key={run.id}
                    onClick={() => navigate("/pipelines")}
                    className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-hover"
                  >
                    <RunStatusDot status={run.status} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-ink">{run.pipeline_name}</p>
                      {run.error_message && (
                        <p className="truncate text-xs text-error">{run.error_message}</p>
                      )}
                    </div>
                    <div className="shrink-0 text-right">
                      {run.elapsed_ms != null && (
                        <p className="text-xs text-ink-tertiary">{formatDuration(run.elapsed_ms)}</p>
                      )}
                      <p className="text-xs text-ink-tertiary">{timeAgo(run.created_at)}</p>
                    </div>
                  </button>
                ))}
              </div>
            ) : (
              <div className="py-8 text-center text-sm text-ink-tertiary">暂无运行记录</div>
            )}
          </SectionCard>

          {/* 推荐论文 */}
          {today && today.recommendations.length > 0 && (
            <SectionCard title="推荐阅读" icon={<Sparkles className="h-4 w-4 text-warning" />}>
              <div className="space-y-1">
                {today.recommendations.slice(0, 4).map((rec) => (
                  <button
                    key={rec.id}
                    onClick={() => navigate(`/papers/${rec.id}`)}
                    className="flex w-full items-start gap-3 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-hover"
                  >
                    <div className="mt-0.5 shrink-0 rounded-lg bg-warning-light p-1.5">
                      <Sparkles className="h-3.5 w-3.5 text-warning" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="line-clamp-2 text-sm font-medium leading-snug text-ink">
                        {rec.title_zh || rec.title}
                      </p>
                      <p className="mt-0.5 text-xs text-ink-tertiary">
                        相似度 {(rec.similarity * 100).toFixed(0)}%
                      </p>
                    </div>
                    <ArrowUpRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-tertiary" />
                  </button>
                ))}
              </div>
            </SectionCard>
          )}
        </div>
      </div>
    </div>
  );
}

/* ========== 子组件 ========== */

function SectionCard({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-5 shadow-sm">
      <div className="mb-4 flex items-center gap-2">
        {icon}
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
      </div>
      {children}
    </div>
  );
}

function StatCard({
  icon, label, value, sub, color, onClick,
}: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  sub: string;
  color: "primary" | "info" | "warning" | "success";
  onClick?: () => void;
}) {
  const iconColors = {
    primary: "text-primary",
    info: "text-info",
    warning: "text-warning",
    success: "text-success",
  };

  return (
    <button
      onClick={onClick}
      className={`hover-lift stat-gradient-${color} group rounded-2xl border border-border bg-surface p-5 text-left shadow-sm transition-all`}
    >
      <div className="flex items-center justify-between">
        <div className={`rounded-xl p-2.5 ${iconColors[color]} bg-white/60 dark:bg-white/5`}>{icon}</div>
        {onClick && <ArrowUpRight className="h-4 w-4 text-ink-tertiary opacity-0 transition-opacity group-hover:opacity-100" />}
      </div>
      <p className="mt-3 text-2xl font-bold tracking-tight text-ink">{value}</p>
      <p className="mt-0.5 text-xs text-ink-tertiary">{label}</p>
      <p className="text-xs text-ink-secondary">{sub}</p>
    </button>
  );
}

function RunStatusDot({ status }: { status: string }) {
  const map: Record<string, string> = {
    succeeded: "bg-success",
    running: "bg-info status-running",
    pending: "bg-warning",
    failed: "bg-error",
  };
  return (
    <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${map[status] || "bg-ink-tertiary"}`} />
  );
}
