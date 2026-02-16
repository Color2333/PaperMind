/**
 * Dashboard - 系统总览
 * 覆盖 API: /health, /system/status, /metrics/costs, /pipelines/runs
 * @author Bamzc
 */
import { useEffect, useState } from "react";
import { Card, CardHeader, Badge, Spinner, Button } from "@/components/ui";
import { systemApi, metricsApi, pipelineApi } from "@/services/api";
import { formatUSD, formatDuration, timeAgo } from "@/lib/utils";
import type { SystemStatus, CostMetrics, PipelineRun } from "@/types";
import {
  Activity,
  Tags,
  FileText,
  GitBranch,
  DollarSign,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  RefreshCw,
  TrendingUp,
  Zap,
} from "lucide-react";

export default function Dashboard() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [costs, setCosts] = useState<CostMetrics | null>(null);
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [s, c, r] = await Promise.all([
        systemApi.status(),
        metricsApi.costs(7),
        pipelineApi.runs(10),
      ]);
      setStatus(s);
      setCosts(c);
      setRuns(r.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  if (loading) return <Spinner text="加载系统状态..." />;
  if (error) {
    return (
      <div className="flex flex-col items-center py-16">
        <XCircle className="h-12 w-12 text-error" />
        <p className="mt-3 text-sm text-error">{error}</p>
        <Button variant="secondary" className="mt-4" onClick={loadData}>
          重试
        </Button>
      </div>
    );
  }

  const isHealthy = status?.health?.status === "ok";

  return (
    <div className="animate-fade-in space-y-6">
      {/* 标题 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-ink">Dashboard</h1>
          <p className="mt-1 text-sm text-ink-secondary">系统总览与运行状态</p>
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

      {/* 健康状态横幅 */}
      <Card
        className={
          isHealthy
            ? "border-success/30 bg-success-light"
            : "border-error/30 bg-error-light"
        }
      >
        <div className="flex items-center gap-3">
          {isHealthy ? (
            <CheckCircle2 className="h-5 w-5 text-success" />
          ) : (
            <AlertTriangle className="h-5 w-5 text-error" />
          )}
          <div>
            <p className="text-sm font-medium text-ink">
              {isHealthy ? "系统运行正常" : "系统异常"}
            </p>
            <p className="text-xs text-ink-secondary">
              {status?.health?.app} · {status?.health?.env}
            </p>
          </div>
        </div>
      </Card>

      {/* 统计卡片 */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          icon={<Tags className="h-5 w-5" />}
          label="主题"
          value={status?.counts?.topics ?? 0}
          sub={`${status?.counts?.enabled_topics ?? 0} 个已启用`}
          color="primary"
        />
        <StatCard
          icon={<FileText className="h-5 w-5" />}
          label="论文"
          value={status?.counts?.papers_latest_200 ?? 0}
          sub="近200篇"
          color="info"
        />
        <StatCard
          icon={<GitBranch className="h-5 w-5" />}
          label="Pipeline 运行"
          value={status?.counts?.runs_latest_50 ?? 0}
          sub={`${status?.counts?.failed_runs_latest_50 ?? 0} 个失败`}
          color="warning"
        />
        <StatCard
          icon={<DollarSign className="h-5 w-5" />}
          label="7日成本"
          value={formatUSD(costs?.total_cost_usd ?? 0)}
          sub={`${costs?.calls ?? 0} 次调用`}
          color="success"
        />
      </div>

      {/* 成本明细 + 最近运行 */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* 成本明细 + 可视化 */}
        <Card>
          <CardHeader title="成本明细" description="按阶段和模型统计" />
          {costs && costs.by_stage.length > 0 ? (
            <div className="space-y-4">
              {/* 按阶段条形图 */}
              <div>
                <p className="mb-2 text-xs font-medium uppercase tracking-wider text-ink-tertiary">
                  按阶段
                </p>
                <div className="space-y-2">
                  {costs.by_stage.map((s) => {
                    const maxCost = Math.max(...costs.by_stage.map((x) => x.total_cost_usd), 0.001);
                    const pct = Math.max((s.total_cost_usd / maxCost) * 100, 2);
                    return (
                      <div key={s.stage} className="rounded-lg bg-page px-3 py-2">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <Zap className="h-3.5 w-3.5 text-warning" />
                            <span className="text-sm text-ink">{s.stage}</span>
                          </div>
                          <div className="text-right">
                            <span className="text-sm font-medium text-ink">
                              {formatUSD(s.total_cost_usd)}
                            </span>
                            <span className="ml-2 text-xs text-ink-tertiary">
                              {s.calls} 次
                            </span>
                          </div>
                        </div>
                        <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-border-light">
                          <div
                            className="h-full rounded-full bg-warning transition-all"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
              {/* 按模型条形图 */}
              {costs.by_model.length > 0 && (
                <div>
                  <p className="mb-2 text-xs font-medium uppercase tracking-wider text-ink-tertiary">
                    按模型
                  </p>
                  <div className="space-y-2">
                    {costs.by_model.map((m) => {
                      const maxCost = Math.max(...costs.by_model.map((x) => x.total_cost_usd), 0.001);
                      const pct = Math.max((m.total_cost_usd / maxCost) * 100, 2);
                      return (
                        <div key={`${m.provider}-${m.model}`} className="rounded-lg bg-page px-3 py-2">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <TrendingUp className="h-3.5 w-3.5 text-info" />
                              <span className="text-sm text-ink">
                                {m.provider}/{m.model}
                              </span>
                            </div>
                            <span className="text-sm font-medium text-ink">
                              {formatUSD(m.total_cost_usd)}
                            </span>
                          </div>
                          <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-border-light">
                            <div
                              className="h-full rounded-full bg-info transition-all"
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
              <div className="flex items-center justify-between border-t border-border pt-3">
                <span className="text-sm text-ink-secondary">Token 用量</span>
                <span className="text-xs text-ink-tertiary">
                  输入 {(costs.input_tokens ?? 0).toLocaleString()} · 输出{" "}
                  {(costs.output_tokens ?? 0).toLocaleString()}
                </span>
              </div>
            </div>
          ) : (
            <p className="py-4 text-center text-sm text-ink-tertiary">暂无数据</p>
          )}
        </Card>

        {/* 最近 Pipeline 运行 */}
        <Card>
          <CardHeader title="最近运行" description="Pipeline 执行记录" />
          {runs.length > 0 ? (
            <div className="space-y-2">
              {runs.map((run) => (
                <div
                  key={run.id}
                  className="flex items-center justify-between rounded-lg bg-page px-3 py-2.5"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <StatusBadge status={run.status} />
                      <span className="truncate text-sm font-medium text-ink">
                        {run.pipeline_name}
                      </span>
                    </div>
                    {run.error_message && (
                      <p className="mt-0.5 truncate text-xs text-error">
                        {run.error_message}
                      </p>
                    )}
                  </div>
                  <div className="shrink-0 text-right">
                    {run.elapsed_ms != null && (
                      <span className="text-xs text-ink-tertiary">
                        {formatDuration(run.elapsed_ms)}
                      </span>
                    )}
                    <p className="text-xs text-ink-tertiary">
                      {timeAgo(run.created_at)}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="py-4 text-center text-sm text-ink-tertiary">暂无运行记录</p>
          )}
        </Card>
      </div>

      {/* 最近一次运行 */}
      {status?.latest_run && (
        <Card className="border-primary/20">
          <CardHeader title="最近一次 Pipeline" />
          <div className="flex items-center gap-4">
            <StatusBadge status={status.latest_run.status} />
            <div>
              <p className="text-sm font-medium text-ink">
                {status.latest_run.pipeline_name}
              </p>
              <p className="text-xs text-ink-secondary">
                {timeAgo(status.latest_run.created_at)}
                {status.latest_run.error_message &&
                  ` · ${status.latest_run.error_message}`}
              </p>
            </div>
          </div>
        </Card>
      )}
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
  sub: string;
  color: "primary" | "info" | "warning" | "success";
}) {
  const colorMap = {
    primary: "text-primary bg-primary-light",
    info: "text-info bg-info-light",
    warning: "text-warning bg-warning-light",
    success: "text-success bg-success-light",
  };

  return (
    <Card>
      <div className="flex items-start gap-3">
        <div className={`rounded-lg p-2.5 ${colorMap[color]}`}>{icon}</div>
        <div>
          <p className="text-xs text-ink-tertiary">{label}</p>
          <p className="mt-0.5 text-xl font-bold text-ink">{value}</p>
          <p className="text-xs text-ink-secondary">{sub}</p>
        </div>
      </div>
    </Card>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { variant: "success" | "warning" | "error" | "info"; icon: React.ReactNode }> = {
    succeeded: { variant: "success", icon: <CheckCircle2 className="h-3 w-3" /> },
    running: { variant: "info", icon: <Activity className="h-3 w-3" /> },
    pending: { variant: "warning", icon: <Clock className="h-3 w-3" /> },
    failed: { variant: "error", icon: <XCircle className="h-3 w-3" /> },
  };
  const item = map[status] ?? map.pending;
  return (
    <Badge variant={item.variant}>
      <span className="mr-1">{item.icon}</span>
      {status}
    </Badge>
  );
}
