/**
 * Operations - 运维操作
 * 覆盖 API: POST /citations/sync/*, POST /jobs/*, GET /system/status
 * @author Color2333
 */
import { useEffect, useState } from "react";
import { Card, CardHeader, Button, Input } from "@/components/ui";
import { useToast } from "@/contexts/ToastContext";
import { citationApi, jobApi, systemApi, topicApi } from "@/services/api";
import type { CitationSyncResult, SystemStatus, Topic, WorkerHeartbeat } from "@/types";
import {
  Settings,
  Link2,
  Play,
  RefreshCw,
  CheckCircle2,
  AlertTriangle,
  Network,
  Calendar,
  Zap,
  HeartPulse,
  RotateCw,
} from "lucide-react";

interface OperationResult {
  success: boolean;
  message: string;
  data?: unknown;
}

export default function Operations() {
  const { toast } = useToast();
  const [results, setResults] = useState<Record<string, OperationResult>>({});
  const [loadings, setLoadings] = useState<Record<string, boolean>>({});

  /* 引用同步 - 单篇 */
  const [syncPaperId, setSyncPaperId] = useState("");
  /* 引用同步 - 主题 */
  const [syncTopicId, setSyncTopicId] = useState("");
  /* 可观测性：worker 心跳 + 主题抓取错误 */
  const [heartbeat, setHeartbeat] = useState<WorkerHeartbeat | null>(null);
  const [staleThreshold, setStaleThreshold] = useState(1200);
  const [failedTopics, setFailedTopics] = useState<Topic[]>([]);
  const [obsLoading, setObsLoading] = useState(false);
  const [refetchingId, setRefetchingId] = useState<string | null>(null);

  const refreshObservability = async () => {
    setObsLoading(true);
    try {
      const [workerRes, topicsRes] = await Promise.all([
        systemApi.worker(),
        topicApi.list(false, true),
      ]);
      setHeartbeat(workerRes.heartbeat);
      setStaleThreshold(workerRes.stale_threshold);
      setFailedTopics(topicsRes.items);
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "可观测性数据加载失败");
    } finally {
      setObsLoading(false);
    }
  };

  useEffect(() => {
    refreshObservability();
  }, []);

  const handleRefetchTopic = async (id: string, name: string) => {
    setRefetchingId(id);
    try {
      await topicApi.fetch(id);
      toast("success", `✅ 主题「${name}」重新抓取已启动`);
      refreshObservability();
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "重新抓取失败");
    } finally {
      setRefetchingId(null);
    }
  };

  const setLoading = (key: string, val: boolean) =>
    setLoadings((prev) => ({ ...prev, [key]: val }));

  const setResult = (key: string, result: OperationResult) =>
    setResults((prev) => ({ ...prev, [key]: result }));

  const handleSyncPaper = async () => {
    if (!syncPaperId.trim()) { toast("warning", "请输入 Paper ID"); return; }
    setLoading("syncPaper", true);
    try {
      const res = await citationApi.syncPaper(syncPaperId);
      setResult("syncPaper", {
        success: true,
        message: (res.message as string) || "论文引用同步已启动",
        data: res,
      });
      toast(
        "success",
        `✅ ${res.message || "论文引用同步已启动"}\n你可以在侧边栏或 Dashboard 查看进度`
      );
    } catch (err) {
      setResult("syncPaper", {
        success: false,
        message: err instanceof Error ? err.message : "同步失败",
      });
      toast("error", err instanceof Error ? err.message : "同步失败");
    } finally {
      setLoading("syncPaper", false);
    }
  };

  const handleSyncTopic = async () => {
    if (!syncTopicId.trim()) { toast("warning", "请输入 Topic ID"); return; }
    setLoading("syncTopic", true);
    try {
      const res = await citationApi.syncTopic(syncTopicId);
      setResult("syncTopic", {
        success: true,
        message: (res.message as string) || "主题引用同步已启动",
        data: res,
      });
      toast(
        "success",
        `✅ ${res.message || "主题引用同步已启动"}\n你可以在侧边栏或 Dashboard 查看进度`
      );
    } catch (err) {
      setResult("syncTopic", {
        success: false,
        message: err instanceof Error ? err.message : "同步失败",
      });
      toast("error", err instanceof Error ? err.message : "同步失败");
    } finally {
      setLoading("syncTopic", false);
    }
  };

  const handleSyncIncremental = async () => {
    setLoading("syncIncremental", true);
    try {
      const res = await citationApi.syncIncremental();
      setResult("syncIncremental", {
        success: true,
        message: res.message || "增量引用同步已启动",
        data: res,
      });
      toast(
        "success",
        `✅ ${res.message || "增量引用同步已启动"}\n你可以在侧边栏或 Dashboard 查看进度`
      );
    } catch (err) {
      setResult("syncIncremental", {
        success: false,
        message: err instanceof Error ? err.message : "同步失败",
      });
      toast("error", err instanceof Error ? err.message : "同步失败");
    } finally {
      setLoading("syncIncremental", false);
    }
  };

  const handleDailyJob = async () => {
    setLoading("dailyJob", true);
    try {
      const res = await jobApi.dailyRun();
      const message = (res as { message?: string }).message || "每日任务已启动";
      setResult("dailyJob", {
        success: true,
        message,
        data: res,
      });
      toast("success", `✅ ${message}\n你可以在侧边栏或 Dashboard 查看进度`);
    } catch (err) {
      setResult("dailyJob", {
        success: false,
        message: err instanceof Error ? err.message : "执行失败",
      });
      toast("error", err instanceof Error ? err.message : "执行失败");
    } finally {
      setLoading("dailyJob", false);
    }
  };

  const handleWeeklyJob = async () => {
    setLoading("weeklyJob", true);
    try {
      const res = await jobApi.weeklyGraphRun();
      const message = (res as { message?: string }).message || "每周图维护已启动";
      setResult("weeklyJob", {
        success: true,
        message,
        data: res,
      });
      toast("success", `✅ ${message}\n你可以在侧边栏或 Dashboard 查看进度`);
    } catch (err) {
      setResult("weeklyJob", {
        success: false,
        message: err instanceof Error ? err.message : "执行失败",
      });
      toast("error", err instanceof Error ? err.message : "执行失败");
    } finally {
      setLoading("weeklyJob", false);
    }
  };
  const handleCheckHealth = async () => {
    setLoading("health", true);
    try {
      const res = await systemApi.status();
      setResult("health", {
        success: true,
        message: `系统 ${res.health.status === "ok" ? "正常" : "异常"} | ${res.counts.topics} 个主题 | ${res.counts.papers_latest_200} 篇论文`,
        data: res,
      });
    } catch (err) {
      setResult("health", {
        success: false,
        message: err instanceof Error ? err.message : "检查失败",
      });
      toast("error", err instanceof Error ? err.message : "健康检查失败");
    } finally {
      setLoading("health", false);
    }
  };

  return (
    <div className="animate-fade-in space-y-6">
      <div>
        <h1 className="text-ink text-2xl font-bold">Operations</h1>
        <p className="text-ink-secondary mt-1 text-sm">引用同步、定时任务、系统检查等运维操作</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* 引用同步 */}
        <Card>
          <CardHeader
            title="引用同步"
            description="同步论文之间的引用关系"
            action={<Link2 className="text-ink-tertiary h-5 w-5" />}
          />
          <div className="space-y-4">
            {/* 单篇同步 */}
            <div className="space-y-2">
              <p className="text-ink-tertiary text-xs font-medium tracking-wider uppercase">
                单篇论文同步
              </p>
              <div className="flex gap-2">
                <Input
                  placeholder="Paper ID"
                  value={syncPaperId}
                  onChange={(e) => setSyncPaperId(e.target.value)}
                />
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={handleSyncPaper}
                  loading={loadings.syncPaper}
                  className="shrink-0"
                >
                  同步
                </Button>
              </div>
              <ResultMessage result={results.syncPaper} />
            </div>

            {/* 主题同步 */}
            <div className="space-y-2">
              <p className="text-ink-tertiary text-xs font-medium tracking-wider uppercase">
                主题同步
              </p>
              <div className="flex gap-2">
                <Input
                  placeholder="Topic ID"
                  value={syncTopicId}
                  onChange={(e) => setSyncTopicId(e.target.value)}
                />
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={handleSyncTopic}
                  loading={loadings.syncTopic}
                  className="shrink-0"
                >
                  同步
                </Button>
              </div>
              <ResultMessage result={results.syncTopic} />
            </div>

            {/* 增量同步 */}
            <div className="space-y-2">
              <p className="text-ink-tertiary text-xs font-medium tracking-wider uppercase">
                增量同步
              </p>
              <Button
                variant="secondary"
                icon={<RefreshCw className="h-3.5 w-3.5" />}
                onClick={handleSyncIncremental}
                loading={loadings.syncIncremental}
              >
                执行增量同步
              </Button>
              <ResultMessage result={results.syncIncremental} />
            </div>
          </div>
        </Card>

        {/* 定时任务 */}
        <Card>
          <CardHeader
            title="定时任务"
            description="手动触发调度任务"
            action={<Calendar className="text-ink-tertiary h-5 w-5" />}
          />
          <div className="space-y-4">
            {/* 每日任务 */}
            <div className="space-y-2">
              <p className="text-ink-tertiary text-xs font-medium tracking-wider uppercase">
                每日任务 (抓取 + 简报)
              </p>
              <Button
                variant="secondary"
                icon={<Play className="h-3.5 w-3.5" />}
                onClick={handleDailyJob}
                loading={loadings.dailyJob}
              >
                执行每日任务
              </Button>
              <ResultMessage result={results.dailyJob} />
            </div>

            {/* 每周图维护 */}
            <div className="space-y-2">
              <p className="text-ink-tertiary text-xs font-medium tracking-wider uppercase">
                每周图维护 (引用同步)
              </p>
              <Button
                variant="secondary"
                icon={<Network className="h-3.5 w-3.5" />}
                onClick={handleWeeklyJob}
                loading={loadings.weeklyJob}
              >
                执行每周维护
              </Button>
              <ResultMessage result={results.weeklyJob} />
            </div>

            <hr className="border-border-light" />

            {/* 系统检查 */}
            <div className="space-y-2">
              <p className="text-ink-tertiary text-xs font-medium tracking-wider uppercase">
                系统健康检查
              </p>
              <Button
                variant="secondary"
                icon={<Zap className="h-3.5 w-3.5" />}
                onClick={handleCheckHealth}
                loading={loadings.health}
              >
                检查系统状态
              </Button>
              <ResultMessage result={results.health} />
            </div>
          </div>
        </Card>
      </div>

      {/* 可观测性：Worker 心跳 + 主题抓取错误 */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Worker 心跳 */}
        <Card>
          <CardHeader
            title="Worker 心跳"
            description="worker 健康状态（心跳时效）"
            action={
              <button
                onClick={refreshObservability}
                disabled={obsLoading}
                className="text-ink-tertiary hover:text-ink transition-colors disabled:opacity-50"
                aria-label="刷新"
              >
                <RefreshCw className={`h-5 w-5 ${obsLoading ? "animate-spin" : ""}`} />
              </button>
            }
          />
          <div className="space-y-3">
            {heartbeat === null ? (
              <div className="flex items-center gap-2 rounded-lg bg-error-light px-3 py-3 text-sm text-error">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                <span>心跳文件缺失或损坏 — worker 可能未启动或共享卷未挂载</span>
              </div>
            ) : heartbeat.is_stale ? (
              <div className="flex items-start gap-2 rounded-lg bg-error-light px-3 py-3 text-sm text-error">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <div>
                  <p className="font-medium">心跳过期（{heartbeat.age_seconds}s &gt; {staleThreshold}s）</p>
                  <p className="mt-1 text-xs">worker 可能卡死或全部任务失败。最近错误：{heartbeat.error || "N/A"}</p>
                  <p className="mt-1 text-xs">worker 每 10min 自检发告警邮件给 notify_default_to。</p>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-2 rounded-lg bg-success-light px-3 py-3 text-sm text-success">
                <HeartPulse className="h-4 w-4 shrink-0" />
                <span>正常 — 心跳距今 {heartbeat.age_seconds}s（阈值 {staleThreshold}s）</span>
              </div>
            )}
          </div>
        </Card>

        {/* 主题抓取错误 */}
        <Card>
          <CardHeader
            title="主题抓取错误"
            description="最近抓取失败的 topic（可重新抓取）"
            action={<AlertTriangle className="text-ink-tertiary h-5 w-5" />}
          />
          <div className="space-y-3">
            {failedTopics.length === 0 ? (
              <div className="flex items-center gap-2 rounded-lg bg-success-light px-3 py-3 text-sm text-success">
                <CheckCircle2 className="h-4 w-4 shrink-0" />
                <span>无抓取错误的 topic</span>
              </div>
            ) : (
              <div className="max-h-80 space-y-2 overflow-y-auto">
                {failedTopics.map((t) => (
                  <div
                    key={t.id}
                    className="rounded-lg border border-border-light p-3 text-sm"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-ink font-medium">{t.name}</span>
                      <Button
                        variant="secondary"
                        size="sm"
                        icon={<RotateCw className="h-3.5 w-3.5" />}
                        onClick={() => handleRefetchTopic(t.id, t.name)}
                        loading={refetchingId === t.id}
                        className="shrink-0"
                      >
                        重新抓取
                      </Button>
                    </div>
                    <p className="text-ink-tertiary mt-1 text-xs">
                      {t.last_run_at ? `最近运行：${new Date(t.last_run_at).toLocaleString()}` : "无运行记录"}
                    </p>
                    <p className="text-error mt-1 text-xs break-words">
                      {t.last_error || "未知错误"}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

function ResultMessage({ result }: { result?: OperationResult }) {
  if (!result) return null;

  return (
    <div
      className={`flex items-start gap-2 rounded-lg px-3 py-2 text-sm ${
        result.success ? "bg-success-light text-success" : "bg-error-light text-error"
      }`}
    >
      {result.success ? (
        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
      ) : (
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      )}
      <span>{result.message}</span>
    </div>
  );
}
