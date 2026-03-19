/**
 * Dashboard - 系统总览（现代精致版）
 * @author Color2333
 */
import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Badge } from "@/components/ui";
import { StatCardSkeleton } from "@/components/Skeleton";
import { useGlobalTasks } from "@/contexts/GlobalTaskContext";
import { systemApi, metricsApi, pipelineApi, todayApi } from "@/services/api";
import { formatDuration, timeAgo } from "@/lib/utils";
import type { SystemStatus, CostMetrics, PipelineRun, TodaySummary } from "@/types";
import {
  Activity,
  FileText,
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
  Loader2,
} from "lucide-react";

const STAGE_LABELS: Record<string, string> = {
  skim: "粗读分析",
  deep_dive: "深度精读",
  deep: "深度精读",
  rag: "RAG 问答",
  reasoning_chain: "推理链分析",
  vision_figure: "图表解读",
  vision: "视觉模型",
  agent_chat: "Agent 对话",
  embed: "向量化",
  embedding: "向量化",
  graph_evolution: "演化分析",
  graph_survey: "综述生成",
  graph_research_gaps: "研究空白",
  graph_timeline: "时间线分析",
  graph_citation_tree: "引用树分析",
  graph_quality: "质量评估",
  wiki_paper: "论文 Wiki",
  wiki_outline: "Wiki 大纲",
  wiki_section: "Wiki 章节",
  wiki_overview: "Wiki 概述",
  keyword_suggest: "关键词建议",
  pdf_reader_ai: "PDF 阅读助手",
  daily_brief: "研究简报",
  translate: "标题翻译",
};

const PIPELINE_LABELS: Record<string, string> = {
  skim: "粗读分析",
  deep_dive: "深度精读",
  embed_paper: "向量化",
  ingest_arxiv: "arXiv 收集",
  ingest_arxiv_with_ids: "订阅收集",
  daily_brief: "每日简报",
  daily_graph_maintenance: "图维护",
};

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { activeTasks, hasRunning } = useGlobalTasks();
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [costs, setCosts] = useState<CostMetrics | null>(null);
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [today, setToday] = useState<TodaySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [costDays, setCostDays] = useState<number>(7);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, c, r, t] = await Promise.all([
        systemApi.status(),
        metricsApi.costs(costDays),
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
  }, [costDays]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  if (loading) return <StatCardSkeleton />;
  if (error) {
    return (
      <div className="flex flex-col items-center py-20">
        <div className="bg-error-light rounded-2xl p-6">
          <XCircle className="text-error mx-auto h-10 w-10" />
        </div>
        <p className="text-error mt-4 text-sm">{error}</p>
        <Button variant="secondary" className="mt-4" onClick={loadData}>
          重试
        </Button>
      </div>
    );
  }

  const isHealthy = status?.health?.status === "ok";
  const todayNew = today?.today_new ?? 0;
  const weekNew = today?.week_new ?? 0;
  const totalPapers = today?.total_papers ?? status?.counts?.papers_latest_200 ?? 0;

  return (
    <div className="animate-fade-in space-y-6">
      {/* Hero 区域 */}
      <div className="page-hero rounded-2xl p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="bg-primary/10 rounded-xl p-2.5">
              <Activity className="text-primary h-5 w-5" />
            </div>
            <div>
              <h1 className="text-ink text-2xl font-bold">Dashboard</h1>
              <p className="text-ink-secondary mt-0.5 text-sm">系统总览与运行状态</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {hasRunning && (
              <div className="bg-primary/10 text-primary flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                <span>{activeTasks.length} 个任务运行中</span>
              </div>
            )}
            <div
              className={`flex items-center gap-2 rounded-full px-4 py-1.5 text-xs font-medium ${
                isHealthy ? "bg-success-light text-success" : "bg-error-light text-error"
              }`}
            >
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
          icon={<Zap className="h-5 w-5" />}
          label={costDays > 0 ? `${costDays}日 Token` : "历史 Token"}
          value={fmtTokens((costs?.input_tokens ?? 0) + (costs?.output_tokens ?? 0))}
          sub={`${costs?.calls ?? 0} 次调用`}
          color="success"
        />
      </div>

      {/* 主内容区：左侧数据 + 右侧任务 */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* 左侧：成本分析 + 活动记录 */}
        <div className="space-y-6 lg:col-span-2">
          {/* Token 用量分析 */}
          <SectionCard
            title="Token 用量分析"
            icon={<BarChart3 className="text-primary h-4 w-4" />}
            action={
              <div className="border-border bg-page flex items-center rounded-lg border p-0.5">
                {[
                  { label: "1d", days: 1 },
                  { label: "7d", days: 7 },
                  { label: "30d", days: 30 },
                  { label: "历史", days: 0 },
                ].map((opt) => (
                  <button
                    key={opt.days}
                    onClick={() => setCostDays(opt.days)}
                    className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                      costDays === opt.days
                        ? "bg-primary text-white"
                        : "text-ink-tertiary hover:text-ink"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            }
          >
            {costs && costs.by_stage.length > 0 ? (
              <div className="space-y-5">
                {/* 总量概览 */}
                <div className="grid grid-cols-3 gap-3">
                  <div className="bg-page rounded-xl p-3 text-center">
                    <p className="text-ink text-lg font-bold">
                      {fmtTokens((costs.input_tokens ?? 0) + (costs.output_tokens ?? 0))}
                    </p>
                    <p className="text-ink-tertiary text-[10px]">总 Token</p>
                  </div>
                  <div className="bg-page rounded-xl p-3 text-center">
                    <p className="text-info text-lg font-bold">
                      {fmtTokens(costs.input_tokens ?? 0)}
                    </p>
                    <p className="text-ink-tertiary text-[10px]">输入</p>
                  </div>
                  <div className="bg-page rounded-xl p-3 text-center">
                    <p className="text-warning text-lg font-bold">
                      {fmtTokens(costs.output_tokens ?? 0)}
                    </p>
                    <p className="text-ink-tertiary text-[10px]">输出</p>
                  </div>
                </div>

                {/* 按阶段 */}
                <div className="space-y-3">
                  <p className="text-ink-tertiary text-xs font-medium tracking-widest uppercase">
                    按阶段
                  </p>
                  {costs.by_stage.map((s) => {
                    const stageTotal = (s.input_tokens ?? 0) + (s.output_tokens ?? 0);
                    const maxTokens = Math.max(
                      ...costs.by_stage.map((x) => (x.input_tokens ?? 0) + (x.output_tokens ?? 0)),
                      1
                    );
                    const pct = Math.max((stageTotal / maxTokens) * 100, 3);
                    return (
                      <div key={s.stage} className="group">
                        <div className="mb-1 flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <Zap className="text-warning h-3 w-3" />
                            <span className="text-ink text-sm">
                              {STAGE_LABELS[s.stage] || s.stage}
                            </span>
                          </div>
                          <div className="flex items-baseline gap-3">
                            <span className="text-ink text-sm font-semibold">
                              {fmtTokens(stageTotal)}
                            </span>
                            <span className="text-ink-tertiary text-[10px]">{s.calls}次</span>
                          </div>
                        </div>
                        <div className="bg-page flex h-2 w-full overflow-hidden rounded-full">
                          <div
                            className="bar-animate bg-info/70 h-full rounded-l-full"
                            style={{
                              width: `${maxTokens > 0 ? Math.max(((s.input_tokens ?? 0) / maxTokens) * 100, 1) : 1}%`,
                            }}
                          />
                          <div
                            className="bar-animate bg-warning/70 h-full rounded-r-full"
                            style={{
                              width: `${maxTokens > 0 ? Math.max(((s.output_tokens ?? 0) / maxTokens) * 100, 1) : 1}%`,
                            }}
                          />
                        </div>
                      </div>
                    );
                  })}
                  <div className="text-ink-tertiary flex items-center gap-4 text-[10px]">
                    <span className="flex items-center gap-1">
                      <span className="bg-info/70 inline-block h-2 w-2 rounded-full" />
                      输入
                    </span>
                    <span className="flex items-center gap-1">
                      <span className="bg-warning/70 inline-block h-2 w-2 rounded-full" />
                      输出
                    </span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="text-ink-tertiary py-8 text-center text-sm">暂无 Token 数据</div>
            )}
          </SectionCard>

          {/* 最近活动 */}
          <SectionCard title="最近活动" icon={<Activity className="text-primary h-4 w-4" />}>
            {runs.length > 0 ? (
              <div className="space-y-2">
                {runs.map((run, index) => (
                  <div
                    key={run.id}
                    className="group bg-page hover:bg-hover flex cursor-pointer items-center gap-3 rounded-xl p-3 transition-all"
                    onClick={() => navigate("/pipelines")}
                  >
                    <span className="text-ink-tertiary bg-border-light flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-medium">
                      {index + 1}
                    </span>
                    <RunStatusDot status={run.status} />
                    <div className="min-w-0 flex-1">
                      <div className="mb-0.5 flex items-center gap-2">
                        <p className="text-ink truncate text-sm font-medium">
                          {PIPELINE_LABELS[run.pipeline_name] || run.pipeline_name}
                        </p>
                        {run.elapsed_ms != null && (
                          <span className="text-ink-tertiary shrink-0 text-[10px]">
                            {formatDuration(run.elapsed_ms)}
                          </span>
                        )}
                      </div>
                      <div className="text-ink-tertiary flex items-center gap-2 text-[10px]">
                        <span>{timeAgo(run.created_at)}</span>
                        {run.error_message && (
                          <span className="text-error truncate">{run.error_message}</span>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="py-12 text-center">
                <Activity className="text-ink-tertiary mx-auto mb-3 h-10 w-10" />
                <p className="text-ink-tertiary text-sm">暂无活动记录</p>
                <p className="text-ink-tertiary mt-1 text-xs">运行任务后会在这里显示</p>
              </div>
            )}
          </SectionCard>
        </div>

        {/* 右侧：活跃任务 + 推荐论文 */}
        <div className="space-y-6 lg:col-span-1">
          {/* 活跃任务 */}
          {hasRunning && activeTasks.length > 0 && (
            <SectionCard
              title="运行中"
              icon={<Loader2 className="text-primary h-4 w-4 animate-spin" />}
            >
              <div className="space-y-3">
                {activeTasks.slice(0, 3).map((task) => (
                  <div key={task.task_id} className="bg-page rounded-xl p-3">
                    <div className="mb-2 flex items-center justify-between">
                      <h4 className="text-ink mr-2 flex-1 truncate text-xs font-semibold">
                        {task.title}
                      </h4>
                      <span className="text-primary text-[10px] font-medium">
                        {task.progress_pct}%
                      </span>
                    </div>
                    <div className="bg-page mb-2 h-1.5 w-full overflow-hidden rounded-full">
                      <div
                        className="from-primary to-info h-full rounded-full bg-gradient-to-r transition-all duration-300"
                        style={{ width: `${task.progress_pct}%` }}
                      />
                    </div>
                    <p className="text-ink-secondary truncate text-[10px]">{task.message}</p>
                    {task.elapsed_seconds > 0 && (
                      <p className="text-ink-tertiary mt-1 text-[10px]">
                        {Math.floor(task.elapsed_seconds / 60)}:
                        {(task.elapsed_seconds % 60).toString().padStart(2, "0")}
                      </p>
                    )}
                  </div>
                ))}
                {activeTasks.length > 3 && (
                  <p className="text-ink-tertiary text-center text-[10px]">
                    还有 {activeTasks.length - 3} 个任务...
                  </p>
                )}
              </div>
            </SectionCard>
          )}

          {/* 推荐论文 */}
          {today && today.recommendations.length > 0 && (
            <SectionCard title="推荐阅读" icon={<Sparkles className="text-warning h-4 w-4" />}>
              <div className="space-y-2">
                {today.recommendations.slice(0, 4).map((rec) => (
                  <button
                    key={rec.id}
                    onClick={() => navigate(`/papers/${rec.id}`)}
                    className="block w-full text-left"
                  >
                    <div className="bg-page hover:bg-hover rounded-xl p-3 transition-colors">
                      <p className="text-ink mb-1 line-clamp-2 text-xs font-medium">
                        {rec.title_zh || rec.title}
                      </p>
                      <p className="text-ink-tertiary text-[10px]">
                        相似度 {(rec.similarity * 100).toFixed(0)}%
                      </p>
                    </div>
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
  onClick,
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
      className={`hover-lift stat-gradient-${color} group border-border bg-surface rounded-2xl border p-5 text-left shadow-sm transition-all`}
    >
      <div className="flex items-center justify-between">
        <div className={`rounded-xl p-2.5 ${iconColors[color]} bg-white/60 dark:bg-white/5`}>
          {icon}
        </div>
        {onClick && (
          <ArrowUpRight className="text-ink-tertiary h-4 w-4 opacity-0 transition-opacity group-hover:opacity-100" />
        )}
      </div>
      <p className="text-ink mt-3 text-2xl font-bold tracking-tight">{value}</p>
      <p className="text-ink-tertiary mt-0.5 text-xs">{label}</p>
      <p className="text-ink-secondary text-xs">{sub}</p>
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
