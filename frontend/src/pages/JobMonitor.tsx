import { useEffect, useState, useCallback } from "react";
import { jobApi, type DurableJobItem, type DurableJobGraph } from "@/services/api";

const STATUS_COLORS: Record<string, string> = {
  queued: "bg-gray-100 text-gray-600",
  running: "bg-blue-100 text-blue-700",
  succeeded: "bg-green-100 text-green-800",
  partially_succeeded: "bg-yellow-100 text-yellow-800",
  failed: "bg-red-100 text-red-700",
  cancelled: "bg-gray-100 text-gray-400",
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
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Job Monitor</h1>
        <div className="flex gap-2">
          {paused ? (
            <button
              className="bg-green-600 text-white px-3 py-1.5 rounded text-sm hover:bg-green-700"
              onClick={doResume}
            >
              Resume Queue
            </button>
          ) : (
            <button
              className="bg-yellow-600 text-white px-3 py-1.5 rounded text-sm hover:bg-yellow-700"
              onClick={doPause}
            >
              Pause Queue
            </button>
          )}
          <button
            className="bg-blue-600 text-white px-3 py-1.5 rounded text-sm hover:bg-blue-700"
            onClick={refresh}
          >
            Refresh
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
        <p className="text-gray-500">Loading...</p>
      ) : (
        <div className="space-y-2">
          {jobs.map((j) => (
            <div
              key={j.id}
              className={`border rounded p-3 cursor-pointer hover:border-blue-400 ${
                selected?.id === j.id ? "border-blue-500 bg-blue-50" : ""
              }`}
              onClick={() => openGraph(j.id)}
            >
              <div className="flex items-center gap-2">
                <span
                  className={`px-2 py-0.5 rounded text-xs font-medium ${
                    STATUS_COLORS[j.status] ?? "bg-gray-100"
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
                    {(j as any).authority === "go_core" ? "Go" : "Py"}
                  </span>
                )}
                <span className="text-xs text-gray-400 ml-auto">{j.id}</span>
              </div>
              {j.progress?.message && (
                <p className="text-xs text-gray-600 mt-1">{j.progress.message}</p>
              )}
              <div className="flex items-center gap-2 mt-1">
                <div className="flex-1 bg-gray-200 rounded-full h-1.5">
                  <div
                    className="bg-blue-500 rounded-full h-1.5"
                    style={{
                      width:
                        j.progress?.total
                          ? `${Math.min(100, ((j.progress?.current ?? 0) / (j.progress?.total || 1)) * 100)}%`
                          : "0%",
                    }}
                  />
                </div>
                <span className="text-xs text-gray-500">
                  {j.progress?.current ?? 0}/{j.progress?.total ?? 0}
                </span>
              </div>
              <div className="flex gap-2 mt-2">
                <button
                  className="text-red-600 text-xs hover:underline"
                  onClick={(e) => {
                    e.stopPropagation();
                    doCancel(j.id);
                  }}
                >
                  Cancel
                </button>
                <button
                  className="text-blue-600 text-xs hover:underline"
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
          {!jobs.length && <p className="text-gray-400 text-sm">No jobs found.</p>}
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
              className="text-gray-400 text-sm ml-auto hover:text-gray-600"
              onClick={() => setSelected(null)}
            >
              ✕
            </button>
          </div>

          {/* Tasks */}
          <div>
            <h4 className="text-sm font-medium text-gray-600 mb-2">
              Tasks ({selected.tasks.length})
            </h4>
            <div className="space-y-1">
              {selected.tasks.map((t) => (
                <div key={t.id} className="flex items-center gap-2 text-xs border rounded p-2">
                  <span
                    className={`px-1.5 py-0.5 rounded ${
                      STATUS_COLORS[t.status] ?? "bg-gray-100"
                    }`}
                  >
                    {t.status}
                  </span>
                  <span className="font-mono">{t.capability}</span>
                  <span className="text-gray-400 ml-auto">attempt {t.attempt_count}</span>
                  <span className="text-gray-400">{t.resource_class}</span>
                  {t.last_error && (
                    <span className="text-red-500 text-xs truncate max-w-48">{t.last_error}</span>
                  )}
                  <button
                    className="text-blue-600 hover:underline"
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
              <h4 className="text-sm font-medium text-gray-600 mb-2">
                Attempts ({selected.attempts.length})
              </h4>
              <div className="space-y-1">
                {selected.attempts.map((a) => (
                  <div key={a.id} className="flex items-center gap-2 text-xs text-gray-600">
                    <span className="font-mono">#{a.attempt_no}</span>
                    <span>{a.status}</span>
                    <span className="text-gray-400">{a.executor_id}</span>
                    {a.fencing_token > 0 && (
                      <span className="text-gray-300">fence:{a.fencing_token}</span>
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
