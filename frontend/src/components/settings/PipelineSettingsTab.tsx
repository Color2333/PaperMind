import { useState, useCallback, useEffect } from "react";
import { GitBranch, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { pipelineApi } from "@/services/api";
import { cn } from "@/lib/utils";
import { formatDuration, timeAgo } from "@/lib/utils";
import { StatusDot } from "./shared";
import type { PipelineRun } from "@/types";

export function PipelineSettingsTab() {
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"all" | "succeeded" | "failed" | "running">("all");

  const loadRuns = useCallback(async () => {
    try { setRuns((await pipelineApi.runs(50)).items || []); } catch { /* quiet */ } finally { setLoading(false); }
  }, []);

  useEffect(() => { loadRuns(); }, [loadRuns]);

  if (loading) return <div className="flex h-64 items-center justify-center"><Spinner /></div>;

  const filtered = filter === "all" ? runs : runs.filter((r) => r.status === filter);
  const counts = { all: runs.length, succeeded: runs.filter((r) => r.status === "succeeded").length, failed: runs.filter((r) => r.status === "failed").length, running: runs.filter((r) => r.status === "running" || r.status === "pending").length };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-ink">Pipeline 运行记录</h2>
        <p className="mt-1 text-sm text-ink-secondary">查看和管理 Pipeline 执行历史</p>
      </div>

      <div className="flex items-center gap-2">
        {(["all", "succeeded", "failed", "running"] as const).map((f) => (
          <button type="button" key={f} onClick={() => setFilter(f)} className={cn("rounded-lg px-3 py-1.5 text-xs font-medium transition-colors", filter === f ? "bg-primary text-white" : "bg-hover text-ink-secondary hover:text-ink")}>
            {f === "all" ? `全部 (${counts.all})` : f === "succeeded" ? `成功 (${counts.succeeded})` : f === "failed" ? `失败 (${counts.failed})` : `进行中 (${counts.running})`}
          </button>
        ))}
        <Button variant="ghost" size="sm" onClick={loadRuns} className="ml-auto"><RefreshCw className="h-3.5 w-3.5" /></Button>
      </div>

      {filtered.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border p-8 text-center">
          <GitBranch className="mx-auto h-8 w-8 text-ink-tertiary" />
          <p className="mt-2 text-sm text-ink-secondary">暂无运行记录</p>
        </div>
      ) : (
        <div className="max-h-[400px] space-y-1 overflow-y-auto">
          {filtered.map((run) => (
            <div key={run.id} className="flex items-center gap-3 rounded-lg px-3 py-2.5 hover:bg-hover">
              <StatusDot status={run.status} />
              <span className="font-medium text-ink">{run.pipeline_name}</span>
              {run.paper_id && <span className="font-mono text-[10px] text-ink-tertiary">{run.paper_id.slice(0, 8)}</span>}
              <span className="ml-auto text-xs text-ink-tertiary">{run.elapsed_ms != null ? formatDuration(run.elapsed_ms) : ""}</span>
              <span className="text-xs text-ink-tertiary">{timeAgo(run.created_at)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
