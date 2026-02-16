/**
 * Pipelines - Pipeline 运行记录
 * 覆盖 API: GET /pipelines/runs
 * @author Bamzc
 */
import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardHeader, Button, Badge, Spinner, Empty } from "@/components/ui";
import { pipelineApi } from "@/services/api";
import { formatDuration, timeAgo } from "@/lib/utils";
import type { PipelineRun } from "@/types";
import {
  GitBranch,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Clock,
  Activity,
  Filter,
} from "lucide-react";

export default function Pipelines() {
  const navigate = useNavigate();
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [limit, setLimit] = useState(50);
  const [filter, setFilter] = useState<string>("all");

  const loadRuns = useCallback(async () => {
    setLoading(true);
    try {
      const res = await pipelineApi.runs(limit);
      setRuns(res.items);
    } catch {
      /* 静默 */
    } finally {
      setLoading(false);
    }
  }, [limit]);

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  const filtered =
    filter === "all" ? runs : runs.filter((r) => r.status === filter);

  const statusCounts = {
    all: runs.length,
    succeeded: runs.filter((r) => r.status === "succeeded").length,
    failed: runs.filter((r) => r.status === "failed").length,
    running: runs.filter((r) => r.status === "running").length,
    pending: runs.filter((r) => r.status === "pending").length,
  };

  return (
    <div className="animate-fade-in space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-ink">Pipelines</h1>
          <p className="mt-1 text-sm text-ink-secondary">
            Skim / Deep / Embed Pipeline 运行记录
          </p>
        </div>
        <div className="flex gap-2">
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="h-9 rounded-lg border border-border bg-surface px-3 text-sm text-ink focus:border-primary focus:outline-none"
          >
            <option value={30}>30 条</option>
            <option value={50}>50 条</option>
            <option value={100}>100 条</option>
          </select>
          <Button
            variant="secondary"
            size="sm"
            icon={<RefreshCw className="h-3.5 w-3.5" />}
            onClick={loadRuns}
          >
            刷新
          </Button>
        </div>
      </div>

      {/* 状态筛选 */}
      <div className="flex gap-2">
        {(
          [
            { key: "all", label: "全部", icon: <Filter className="h-3.5 w-3.5" /> },
            {
              key: "succeeded",
              label: "成功",
              icon: <CheckCircle2 className="h-3.5 w-3.5" />,
            },
            {
              key: "failed",
              label: "失败",
              icon: <XCircle className="h-3.5 w-3.5" />,
            },
            {
              key: "running",
              label: "运行中",
              icon: <Activity className="h-3.5 w-3.5" />,
            },
            {
              key: "pending",
              label: "等待中",
              icon: <Clock className="h-3.5 w-3.5" />,
            },
          ] as const
        ).map((item) => (
          <button
            key={item.key}
            onClick={() => setFilter(item.key)}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium transition-all ${
              filter === item.key
                ? "bg-primary-light text-primary"
                : "bg-hover text-ink-secondary hover:text-ink"
            }`}
          >
            {item.icon}
            {item.label}
            <span className="ml-0.5 text-ink-tertiary">
              ({statusCounts[item.key]})
            </span>
          </button>
        ))}
      </div>

      {loading ? (
        <Spinner text="加载运行记录..." />
      ) : filtered.length === 0 ? (
        <Empty
          icon={<GitBranch className="h-12 w-12" />}
          title="暂无运行记录"
          description="执行 Skim 或 Deep Read 后会显示运行记录"
        />
      ) : (
        <Card padding={false}>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border">
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-ink-tertiary">
                    状态
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-ink-tertiary">
                    Pipeline
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-ink-tertiary">
                    Paper ID
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-ink-tertiary">
                    决策备注
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-ink-tertiary">
                    耗时
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-ink-tertiary">
                    时间
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-light">
                {filtered.map((run) => (
                  <tr
                    key={run.id}
                    className="transition-colors hover:bg-hover"
                  >
                    <td className="px-4 py-3">
                      <StatusBadge status={run.status} />
                    </td>
                    <td className="px-4 py-3 text-sm font-medium text-ink">
                      {run.pipeline_name}
                    </td>
                    <td className="px-4 py-3">
                      {run.paper_id ? (
                        <button
                          onClick={() => navigate(`/papers/${run.paper_id}`)}
                          className="font-mono text-xs text-primary hover:underline"
                          title={run.paper_id}
                        >
                          {run.paper_id.slice(0, 8)}...
                        </button>
                      ) : (
                        <span className="text-xs text-ink-tertiary">-</span>
                      )}
                    </td>
                    <td className="max-w-[200px] px-4 py-3">
                      {run.decision_note ? (
                        <span className="truncate text-xs text-ink-secondary">
                          {run.decision_note}
                        </span>
                      ) : run.error_message ? (
                        <span className="truncate text-xs text-error">
                          {run.error_message}
                        </span>
                      ) : (
                        <span className="text-xs text-ink-tertiary">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-ink-secondary">
                      {run.elapsed_ms != null
                        ? formatDuration(run.elapsed_ms)
                        : "-"}
                    </td>
                    <td className="px-4 py-3 text-xs text-ink-tertiary">
                      {timeAgo(run.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<
    string,
    { variant: "success" | "warning" | "error" | "info"; label: string }
  > = {
    succeeded: { variant: "success", label: "成功" },
    running: { variant: "info", label: "运行中" },
    pending: { variant: "warning", label: "等待" },
    failed: { variant: "error", label: "失败" },
  };
  const item = map[status] ?? map.pending;
  return <Badge variant={item.variant}>{item.label}</Badge>;
}
