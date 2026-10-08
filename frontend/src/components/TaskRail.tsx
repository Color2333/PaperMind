/**
 * 任务右栏——Go 权威任务 live 流（知识工作台第三栏）
 * @author Color2333
 */
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Activity, X, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { jobApi, type DurableJobItem } from "@/services/api";

const STATUS_STYLE: Record<string, string> = {
  succeeded: "bg-success-light text-success",
  failed: "bg-error-light text-error",
  dead_letter: "bg-error-light text-error",
  running: "bg-primary/10 text-primary",
  queued: "bg-hover text-ink-tertiary",
  cancelling: "bg-warning-light text-warning",
  cancelled: "bg-hover text-ink-tertiary",
};

export default function TaskRail({ onClose }: { onClose?: () => void }) {
  const navigate = useNavigate();
  const [jobs, setJobs] = useState<DurableJobItem[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await jobApi.list({ limit: 12 });
      setJobs(res.items || []);
    } catch {
      /* 静默——右栏是辅助观测 */
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 6000);
    return () => clearInterval(t);
  }, [refresh]);

  return (
    <aside className="border-border bg-surface hidden h-full w-[280px] shrink-0 flex-col border-l xl:flex">
      <div className="border-border flex items-center gap-2 border-b px-3 py-2.5">
        <Activity className="text-primary h-3.5 w-3.5" />
        <span className="text-ink text-xs font-semibold">任务流</span>
        <span className="bg-hover text-ink-tertiary ml-auto rounded-full px-1.5 py-0.5 text-[10px]">
          live
        </span>
        {onClose && (
          <button
            aria-label="收起任务流"
            onClick={onClose}
            className="text-ink-tertiary hover:bg-hover hover:text-ink rounded p-1"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      <div className="flex-1 space-y-1.5 overflow-y-auto px-2 py-2">
        {jobs.length === 0 && (
          <p className="text-ink-tertiary px-2 py-6 text-center text-xs">暂无任务</p>
        )}
        {jobs.map((j) => {
          const isOpen = expanded === j.id;
          return (
            <div key={j.id}>
              <button
                onClick={() => setExpanded(isOpen ? null : j.id)}
                className="bg-page hover:bg-hover flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-colors"
              >
                <span
                  className={cn(
                    "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium",
                    STATUS_STYLE[j.status] ?? "bg-hover text-ink-tertiary",
                  )}
                >
                  {j.status}
                </span>
                <span className="text-ink min-w-0 flex-1 truncate text-xs font-medium">{j.kind}</span>
                <span className="text-ink-tertiary shrink-0 text-[10px]">
                  {j.authority === "go_core" ? "Go" : "Py"}
                </span>
              </button>
              {isOpen && (
                <div className="border-border-light text-ink-tertiary mt-1 space-y-1 rounded-lg border px-3 py-2 text-[11px]">
                  <p className="truncate font-mono">{j.id}</p>
                  <div className="flex items-center justify-between">
                    <span>{j.progress?.current ?? 0}/{j.progress?.total ?? 0}</span>
                    <button
                      onClick={() => navigate(`/jobs`)}
                      className="text-primary hover:underline"
                    >
                      任务图
                    </button>
                  </div>
                  {j.progress?.message && <p className="truncate">{j.progress.message}</p>}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="border-border border-t px-3 py-2">
        <button
          onClick={() => navigate("/jobs")}
          className="text-ink-secondary hover:bg-hover hover:text-ink flex w-full items-center justify-center gap-1 rounded-lg py-1.5 text-xs transition-colors"
        >
          <X className="h-3 w-3" />
          任务监控全览
        </button>
      </div>
    </aside>
  );
}
