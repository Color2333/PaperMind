/**
 * Dashboard - 系统总览（现代精致版）
 * @author Bamzc
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Badge } from "@/components/ui";
import { StatCardSkeleton } from "@/components/Skeleton";
import { useGlobalTasks } from "@/contexts/GlobalTaskContext";
import { systemApi, metricsApi, pipelineApi, todayApi, type TodaySummary } from "@/services/api";
import { formatDuration, timeAgo } from "@/lib/utils";
import type { SystemStatus, CostMetrics, PipelineRun } from "@/types";
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

  if (loading) return <StatCardSkeleton />;
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
            {hasRunning && (
              <div className="flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                <span>{activeTasks.length} 个任务运行中</span>
              </div>
            )}
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
          icon={<Zap className="h-5 w-5" />}
          label="7日 Token"
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
          <SectionCard title="Token 用量分析" icon={<BarChart3 className="h-4 w-4 text-primary" />}>
            {costs && costs.by_stage.length > 0 ? (
              <div className="space-y-5">
                {/* 总量概览 */}
                <div className="grid grid-cols-3 gap-3">
                  <div className="rounded-xl bg-page p-3 text-center">
                    <p className="text-lg font-bold text-ink">{fmtTokens((costs.input_tokens ?? 0) + (costs.output_tokens ?? 0))}</p>
                    <p className="text-[10px] text-ink-tertiary">总 Token</p>
                  </div>
                  <div className="rounded-xl bg-page p-3 text-center">
                    <p className="text-lg font-bold text-info">{fmtTokens(costs.input_tokens ?? 0)}</p>
                    <p className="text-[10px] text-ink-tertiary">输入</p>
                  </div>
                  <div className="rounded-xl bg-page p-3 text-center">
                    <p className="text-lg font-bold text-warning">{fmtTokens(costs.output_tokens ?? 0)}</p>
                    <p className="text-[10px] text-ink-tertiary">输出</p>
                  </div>
                </div>

                {/* 按阶段 */}
                <div className="space-y-3">
                  <p className="text-xs font-medium uppercase tracking-widest text-ink-tertiary">按阶段</p>
                  {costs.by_stage.map((s) => {
                    const stageTotal = (s.input_tokens ?? 0) + (s.output_tokens ?? 0);
                    const maxTokens = Math.max(...costs.by_stage.map((x) => (x.input_tokens ?? 0) + (x.output_tokens ?? 0)), 1);
                    const pct = Math.max((stageTotal / maxTokens) * 100, 3);
                    return (
                      <div key={s.stage} className="group">
                        <div className="mb-1 flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <Zap className="h-3 w-3 text-warning" />
                            <span className="text-sm text-ink">{STAGE_LABELS[s.stage] || s.stage}</span>
                          </div>
                          <div className="flex items-baseline gap-3">
                            <span className="text-sm font-semibold text-ink">{fmtTokens(stageTotal)}</span>
                            <span className="text-[10px] text-ink-tertiary">{s.calls}次</span>
                          </div>
                        </div>
                        <div className="flex h-2 w-full overflow-hidden rounded-full bg-page">
                          <div
                            className="bar-animate h-full rounded-l-full bg-info/70"
                            style={{ width: `${maxTokens > 0 ? Math.max(((s.input_tokens ?? 0) / maxTokens) * 100, 1) : 1}%` }}
                          />
                          <div
                            className="bar-animate h-full rounded-r-full bg-warning/70"
                            style={{ width: `${maxTokens > 0 ? Math.max(((s.output_tokens ?? 0) / maxTokens) * 100, 1) : 1}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                  <div className="flex items-center gap-4 text-[10px] text-ink-tertiary">
                    <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-info/70" />输入</span>
                    <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-warning/70" />输出</span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="py-8 text-center text-sm text-ink-tertiary">暂无 Token 数据</div>
            )}
          </SectionCard>

          {/* 最近活动 */}
          <SectionCard title="最近活动" icon={<Activity className="h-4 w-4 text-primary" />}>
            {runs.length > 0 ? (
              <div className="space-y-2">
                {runs.map((run, index) => (
                  <div
                    key={run.id}
                    className="group flex items-center gap-3 rounded-xl bg-page p-3 transition-all hover:bg-hover cursor-pointer"
                    onClick={() => navigate("/pipelines")}
                  >
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-medium text-ink-tertiary bg-border-light">
                      {index + 1}
                    </span>
                    <RunStatusDot status={run.status} />
                    <div className="min-w-0 flex-1">
                      <div className="mb-0.5 flex items-center gap-2">
                        <p className="truncate text-sm font-medium text-ink">
                          {PIPELINE_LABELS[run.pipeline_name] || run.pipeline_name}
                        </p>
                        {run.elapsed_ms != null && (
                          <span className="shrink-0 text-[10px] text-ink-tertiary">
                            {formatDuration(run.elapsed_ms)}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 text-[10px] text-ink-tertiary">
                        <span>{timeAgo(run.created_at)}</span>
                        {run.error_message && (
                          <span className="truncate text-error">{run.error_message}</span>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="py-12 text-center">
                <Activity className="mx-auto h-10 w-10 text-ink-tertiary mb-3" />
                <p className="text-sm text-ink-tertiary">暂无活动记录</p>
                <p className="mt-1 text-xs text-ink-tertiary">运行任务后会在这里显示</p>
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
              icon={<Loader2 className="h-4 w-4 text-primary animate-spin" />}
            >
              <div className="space-y-3">
                {activeTasks.slice(0, 3).map((task) => (
                  <div key={task.task_id} className="rounded-xl bg-page p-3">
                    <div className="mb-2 flex items-center justify-between">
                      <h4 className="text-xs font-semibold text-ink truncate flex-1 mr-2">{task.title}</h4>
                      <span className="text-[10px] text-primary font-medium">{task.progress_pct}%</span>
                    </div>
                    <div className="mb-2 h-1.5 w-full overflow-hidden rounded-full bg-page">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-primary to-info transition-all duration-300"
                        style={{ width: `${task.progress_pct}%` }}
                      />
                    </div>
                    <p className="text-[10px] text-ink-secondary truncate">{task.message}</p>
                    {task.elapsed_seconds > 0 && (
                      <p className="mt-1 text-[10px] text-ink-tertiary">
                        {Math.floor(task.elapsed_seconds / 60)}:{(task.elapsed_seconds % 60).toString().padStart(2, '0')}
                      </p>
                    )}
                  </div>
                ))}
                {activeTasks.length > 3 && (
                  <p className="text-center text-[10px] text-ink-tertiary">
                    还有 {activeTasks.length - 3} 个任务...
                  </p>
                )}
              </div>
            </SectionCard>
          )}

          {/* 推荐论文 */}
          {today && today.recommendations.length > 0 && (
            <SectionCard title="推荐阅读" icon={<Sparkles className="h-4 w-4 text-warning" />}>
              <div className="space-y-2">
                {today.recommendations.slice(0, 4).map((rec) => (
                  <button
                    key={rec.id}
                    onClick={() => navigate(`/papers/${rec.id}`)}
                    className="block w-full text-left"
                  >
                    <div className="rounded-xl bg-page p-3 transition-colors hover:bg-hover">
                      <p className="mb-1 text-xs font-medium text-ink line-clamp-2">
                        {rec.title_zh || rec.title}
                      </p>
                      <p className="text-[10px] text-ink-tertiary">
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
