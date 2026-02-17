/**
 * Pipelines - 运行记录（现代精致版）
 * @author Bamzc
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
    try { const res = await pipelineApi.runs(limit); setRuns(res.items); }
    catch {} finally { setLoading(false); }
  }, [limit]);

  useEffect(() => { loadRuns(); }, [loadRuns]);

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
          <div className="rounded-xl bg-primary/10 p-2.5"><Cpu className="h-5 w-5 text-primary" /></div>
          <div>
            <h1 className="text-2xl font-bold text-ink">Pipelines</h1>
            <p className="mt-0.5 text-sm text-ink-secondary">Skim / Deep / Embed 运行记录</p>
          </div>
        </div>
        <div className="flex gap-2">
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="h-8 rounded-lg border border-border bg-surface px-2 text-xs text-ink focus:border-primary focus:outline-none"
          >
            <option value={30}>30</option><option value={50}>50</option><option value={100}>100</option>
          </select>
          <Button variant="secondary" size="sm" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={loadRuns}>刷新</Button>
        </div>
      </div>

      {/* 筛选 */}
      <div className="flex gap-1 rounded-2xl bg-page p-1.5">
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
            <span className="rounded-full bg-page px-1.5 text-[10px] text-ink-tertiary">{counts[f.key]}</span>
          </button>
        ))}
      </div>

      {/* 内容 */}
      {loading ? (
        <Spinner text="加载运行记录..." />
      ) : filtered.length === 0 ? (
        <Empty icon={<GitBranch className="h-14 w-14" />} title="暂无运行记录" description="执行 Skim 或 Deep Read 后会显示记录" />
      ) : (
        <div className="rounded-2xl border border-border bg-surface shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border">
                  {["状态", "Pipeline", "Paper", "备注", "耗时", "时间"].map((h) => (
                    <th key={h} className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-widest text-ink-tertiary">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border-light">
                {filtered.map((run) => (
                  <tr key={run.id} className="transition-colors hover:bg-hover">
                    <td className="px-4 py-3"><RunStatus status={run.status} /></td>
                    <td className="px-4 py-3 text-sm font-medium text-ink">{run.pipeline_name}</td>
                    <td className="px-4 py-3">
                      {run.paper_id ? (
                        <button onClick={() => navigate(`/papers/${run.paper_id}`)} className="font-mono text-xs text-primary hover:underline">{run.paper_id.slice(0, 8)}…</button>
                      ) : <span className="text-xs text-ink-tertiary">—</span>}
                    </td>
                    <td className="max-w-[200px] px-4 py-3">
                      {run.decision_note ? <span className="truncate text-xs text-ink-secondary">{run.decision_note}</span>
                       : run.error_message ? <span className="truncate text-xs text-error">{run.error_message}</span>
                       : <span className="text-xs text-ink-tertiary">—</span>}
                    </td>
                    <td className="px-4 py-3 text-xs text-ink-secondary">{run.elapsed_ms != null ? formatDuration(run.elapsed_ms) : "—"}</td>
                    <td className="px-4 py-3 text-xs text-ink-tertiary">{timeAgo(run.created_at)}</td>
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
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-medium ${m.bg}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${m.dot}`} />
      {m.label}
    </span>
  );
}
