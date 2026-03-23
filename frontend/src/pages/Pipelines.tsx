/**
 * Pipelines - 运行记录（现代精致版）
 * @author Color2333
 */
import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Badge, Spinner, Empty } from "@/components/ui";
import { pipelineApi } from "@/services/api";
import { formatDuration, timeAgo } from "@/lib/utils";
import type { PipelineRun } from "@/types";
import { GitBranch, RefreshCw, CheckCircle2, XCircle, Clock, Activity, Cpu } from "lucide-react";

const STATUS_FILTERS = [
  { key: "all", label: "全部" },
  { key: "succeeded", label: "成功" },
  { key: "failed", label: "失败" },
  { key: "running", label: "运行中" },
  { key: "pending", label: "等待中" },
] as const;

export default function Pipelines() {
  const navigate = useNavigate();
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [limit, setLimit] = useState(50);
  const [filter, setFilter] = useState("all");

  const loadRuns = useCallback(async () => {
    setLoading(true);
    try {
      const res = await pipelineApi.runs(limit);
      setRuns(res.items);
    } catch {
    } finally {
      setLoading(false);
    }
  }, [limit]);

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  const filtered = filter === "all" ? runs : runs.filter((r) => r.status === filter);
  const counts: Record<string, number> = {
    all: runs.length,
    succeeded: runs.filter((r) => r.status === "succeeded").length,
    failed: runs.filter((r) => r.status === "failed").length,
    running: runs.filter((r) => r.status === "running").length,
    pending: runs.filter((r) => r.status === "pending").length,
  };

  return (
    <div className="animate-fade-in space-y-6">
      {/* 页面头 */}
      <div className="page-hero flex items-center justify-between rounded-2xl p-6">
        <div className="flex items-center gap-3">
          <div className="bg-primary/10 rounded-xl p-2.5">
            <Cpu className="text-primary h-5 w-5" />
          </div>
          <div>
            <h1 className="text-ink text-2xl font-bold">Pipelines</h1>
            <p className="text-ink-secondary mt-0.5 text-sm">Skim / Deep / Embed 运行记录</p>
          </div>
        </div>
        <div className="flex gap-2">
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="border-border bg-surface text-ink focus:border-primary h-8 rounded-lg border px-2 text-xs focus:outline-none"
          >
            <option value={30}>30</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
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

      {/* 筛选 */}
      <div className="bg-page flex gap-1 rounded-2xl p-1.5">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-xl py-2 text-xs font-medium transition-all ${
              filter === f.key
                ? "bg-surface text-primary shadow-sm"
                : "text-ink-tertiary hover:text-ink"
            }`}
          >
            {f.label}
            <span className="bg-page text-ink-tertiary rounded-full px-1.5 text-[10px]">
              {counts[f.key]}
            </span>
          </button>
        ))}
      </div>

      {/* 内容 */}
      {loading ? (
        <Spinner text="加载运行记录..." />
      ) : filtered.length === 0 ? (
        <Empty
          icon={<GitBranch className="h-14 w-14" />}
          title="暂无运行记录"
          description="执行 Skim 或 Deep Read 后会显示记录"
        />
      ) : (
        <div className="border-border bg-surface rounded-2xl border shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-border border-b">
                  {["状态", "Pipeline", "Paper", "备注", "耗时", "时间"].map((h) => (
                    <th
                      key={h}
                      className="text-ink-tertiary px-4 py-3 text-left text-[10px] font-semibold tracking-widest uppercase"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-border-light divide-y">
                {filtered.map((run) => (
                  <tr key={run.id} className="hover:bg-hover transition-colors">
                    <td className="px-4 py-3">
                      <RunStatus status={run.status} />
                    </td>
                    <td className="text-ink px-4 py-3 text-sm font-medium">{run.pipeline_name}</td>
                    <td className="px-4 py-3">
                      {run.paper_id ? (
                        <button
                          onClick={() => navigate(`/papers/${run.paper_id}`)}
                          className="text-primary font-mono text-xs hover:underline"
                        >
                          {run.paper_id.slice(0, 8)}…
                        </button>
                      ) : (
                        <span className="text-ink-tertiary text-xs">—</span>
                      )}
                    </td>
                    <td className="max-w-[200px] px-4 py-3">
                      {run.decision_note ? (
                        <span className="text-ink-secondary truncate text-xs">
                          {run.decision_note}
                        </span>
                      ) : run.error_message ? (
                        <span className="text-error truncate text-xs">{run.error_message}</span>
                      ) : (
                        <span className="text-ink-tertiary text-xs">—</span>
                      )}
                    </td>
                    <td className="text-ink-secondary px-4 py-3 text-xs">
                      {run.elapsed_ms != null ? formatDuration(run.elapsed_ms) : "—"}
                    </td>
                    <td className="text-ink-tertiary px-4 py-3 text-xs">
                      {timeAgo(run.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function RunStatus({ status }: { status: string }) {
  const map: Record<string, { bg: string; dot: string; label: string }> = {
    succeeded: { bg: "bg-success-light", dot: "bg-success", label: "成功" },
    running: { bg: "bg-info-light", dot: "bg-info status-running", label: "运行中" },
    pending: { bg: "bg-warning-light", dot: "bg-warning", label: "等待" },
    failed: { bg: "bg-error-light", dot: "bg-error", label: "失败" },
  };
  const m = map[status] || map.pending;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-medium ${m.bg}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${m.dot}`} />
      {m.label}
    </span>
  );
}
