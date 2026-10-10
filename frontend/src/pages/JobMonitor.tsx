import { useEffect, useState, useCallback } from "react";
import { jobApi, type DurableJobItem, type DurableJobGraph } from "@/services/api";
import { ListTodo } from "lucide-react";

const STATUS_COLORS: Record<string, string> = {
  queued: "bg-hover text-ink-secondary",
  running: "bg-info-light text-info",
  succeeded: "bg-green-100 text-green-800",
  partially_succeeded: "bg-yellow-100 text-yellow-800",
  failed: "bg-red-100 text-red-700",
  cancelled: "bg-hover text-ink-tertiary",
  dead_letter: "bg-red-200 text-red-900",
  manual_recovery: "bg-purple-100 text-purple-800",
};

export default function JobMonitor() {
  const [jobs, setJobs] = useState<DurableJobItem[]>([]);
  const [selected, setSelected] = useState<DurableJobGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const [paused, setPaused] = useState(false);
  const [kindFilter, setKindFilter] = useState("");

  const refresh = useCallback(async () => {
    try {
      const data = await jobApi.list({ kind: kindFilter || undefined, limit: 50 });
      setJobs(data.items);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [kindFilter]);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 5000);
    return () => clearInterval(interval);
  }, [refresh]);

  const openGraph = async (jobId: string) => {
    const graph = await jobApi.graph(jobId);
    setSelected(graph);
  };

  const doCancel = async (jobId: string) => {
    await jobApi.cancel(jobId);
    refresh();
    if (selected?.id === jobId) openGraph(jobId);
  };

  const doRetry = async (jobId: string) => {
    await jobApi.retry(jobId);
    refresh();
  };

  const doPause = async () => {
    await jobApi.pauseQueue();
    setPaused(true);
  };

  const doResume = async () => {
    await jobApi.resumeQueue();
    setPaused(false);
  };

  return (
    <div className="animate-fade-in space-y-6">
      <div className="page-hero flex items-center justify-between rounded-2xl p-6">
        <div className="flex items-center gap-3">
          <div className="bg-primary/10 rounded-xl p-2.5">
            <ListTodo className="text-primary h-5 w-5" />
          </div>
          <div>
            <h1 className="text-ink text-2xl font-bold">任务监控</h1>
            <p className="text-ink-secondary mt-0.5 text-sm">权威任务队列：状态、重试与队列控制</p>
          </div>
        </div>
        <div className="flex gap-2">
          {paused ? (
            <button
              className="bg-success text-white px-3 py-1.5 rounded-lg text-sm hover:bg-success/85 transition-colors"
              onClick={doResume}
            >
              恢复队列
            </button>
          ) : (
            <button
              className="bg-warning text-white px-3 py-1.5 rounded-lg text-sm hover:bg-warning/85 transition-colors"
              onClick={doPause}
            >
              暂停队列
            </button>
          )}
          <button
            className="gradient-primary shadow-warm-xs text-white px-3 py-1.5 rounded-lg text-sm transition-all hover:shadow-warm-md"
            onClick={refresh}
          >
            刷新
          </button>
        </div>
      </div>

      {/* kind 筛选 */}
      <input
        className="border rounded px-3 py-2 w-64 text-sm"
        placeholder="Filter by kind..."
        value={kindFilter}
        onChange={(e) => setKindFilter(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && refresh()}
      />

      {/* Jobs 列表 */}
      {loading && !jobs.length ? (
        <p className="text-ink-tertiary">Loading...</p>
      ) : (
        <div className="space-y-2">
          {jobs.map((j) => (
            <div
              key={j.id}
              className={`border rounded p-3 cursor-pointer hover:border-blue-400 ${
                selected?.id === j.id ? "border-primary bg-primary-50" : ""
              }`}
              onClick={() => openGraph(j.id)}
            >
              <div className="flex items-center gap-2">
                <span
                  className={`px-2 py-0.5 rounded text-xs font-medium ${
                    STATUS_COLORS[j.status] ?? "bg-hover"
                  }`}
                >
                  {j.status}
                </span>
                <span className="font-medium text-sm">{j.kind}</span>
                {(j as any).authority && (
                  <span
                    className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                      (j as any).authority === "go_core"
                        ? "bg-cyan-100 text-cyan-700"
                        : "bg-orange-100 text-orange-700"
                    }`}
                  >
                    {(j as any).authority === "go_core" ? "Go" : "存档"}
                  </span>
                )}
                <span className="text-xs text-ink-tertiary ml-auto">{j.id}</span>
              </div>
              {j.progress?.message && (
                <p className="text-xs text-ink-secondary mt-1">{j.progress.message}</p>
              )}
              <div className="flex items-center gap-2 mt-1">
                <div className="flex-1 bg-active rounded-full h-1.5">
                  <div
                    className="bg-primary rounded-full h-1.5"
                    style={{
                      width:
                        j.progress?.total
                          ? `${Math.min(100, ((j.progress?.current ?? 0) / (j.progress?.total || 1)) * 100)}%`
                          : "0%",
                    }}
                  />
                </div>
                <span className="text-xs text-ink-tertiary">
                  {j.progress?.current ?? 0}/{j.progress?.total ?? 0}
                </span>
              </div>
              <div className="flex gap-2 mt-2">
                <button
                  className="text-error text-xs hover:underline"
                  onClick={(e) => {
                    e.stopPropagation();
                    doCancel(j.id);
                  }}
                >
                  Cancel
                </button>
                <button
                  className="text-primary text-xs hover:underline"
                  onClick={(e) => {
                    e.stopPropagation();
                    doRetry(j.id);
                  }}
                >
                  Retry
                </button>
              </div>
            </div>
          ))}
          {!jobs.length && <p className="text-ink-tertiary text-sm">No jobs found.</p>}
        </div>
      )}

      {/* Job graph 详情 */}
      {selected && (
        <div className="bg-white rounded-lg shadow p-4 space-y-4">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold">{selected.kind}</h3>
            <span
              className={`px-2 py-0.5 rounded text-xs ${STATUS_COLORS[selected.status] ?? ""}`}
            >
              {selected.status}
            </span>
            {(selected as any).authority && (
              <span
                className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                  (selected as any).authority === "go_core"
                    ? "bg-cyan-100 text-cyan-700"
                    : "bg-orange-100 text-orange-700"
                }`}
              >
                {(selected as any).authority === "go_core" ? "Go Authority" : "Python Durable"}
              </span>
            )}
            <button
              className="text-ink-tertiary text-sm ml-auto hover:text-ink-secondary"
              onClick={() => setSelected(null)}
            >
              ✕
            </button>
          </div>

          {/* Tasks */}
          <div>
            <h4 className="text-sm font-medium text-ink-secondary mb-2">
              Tasks ({selected.tasks.length})
            </h4>
            <div className="space-y-1">
              {selected.tasks.map((t) => (
                <div key={t.id} className="flex items-center gap-2 text-xs border rounded p-2">
                  <span
                    className={`px-1.5 py-0.5 rounded ${
                      STATUS_COLORS[t.status] ?? "bg-hover"
                    }`}
                  >
                    {t.status}
                  </span>
                  <span className="font-mono">{t.capability}</span>
                  <span className="text-ink-tertiary ml-auto">attempt {t.attempt_count}</span>
                  <span className="text-ink-tertiary">{t.resource_class}</span>
                  {t.last_error && (
                    <span className="text-red-500 text-xs truncate max-w-48">{t.last_error}</span>
                  )}
                  <button
                    className="text-primary hover:underline"
                    onClick={async (e) => {
                      e.stopPropagation();
                      await jobApi.retryTask(t.id);
                      openGraph(selected.id);
                    }}
                  >
                    retry
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* Attempts */}
          {selected.attempts.length > 0 && (
            <div>
              <h4 className="text-sm font-medium text-ink-secondary mb-2">
                Attempts ({selected.attempts.length})
              </h4>
              <div className="space-y-1">
                {selected.attempts.map((a) => (
                  <div key={a.id} className="flex items-center gap-2 text-xs text-ink-secondary">
                    <span className="font-mono">#{a.attempt_no}</span>
                    <span>{a.status}</span>
                    <span className="text-ink-tertiary">{a.executor_id}</span>
                    {a.fencing_token > 0 && (
                      <span className="text-ink-placeholder">fence:{a.fencing_token}</span>
                    )}
                    {a.error_message && (
                      <span className="text-red-500 truncate max-w-48">{a.error_message}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
