/**
 * Operations - 运维操作
 * 覆盖 API: POST /citations/sync/*, POST /jobs/*, GET /system/status
 * @author Bamzc
 */
import { useState } from "react";
import { Card, CardHeader, Button, Input } from "@/components/ui";
import { useToast } from "@/contexts/ToastContext";
import { citationApi, jobApi, systemApi } from "@/services/api";
import type { CitationSyncResult, SystemStatus } from "@/types";
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

  const setLoading = (key: string, val: boolean) =>
    setLoadings((prev) => ({ ...prev, [key]: val }));

  const setResult = (key: string, result: OperationResult) =>
    setResults((prev) => ({ ...prev, [key]: result }));

  const handleSyncPaper = async () => {
    if (!syncPaperId.trim()) return;
    setLoading("syncPaper", true);
    try {
      const res = await citationApi.syncPaper(syncPaperId);
      setResult("syncPaper", {
        success: true,
        message: (res.message as string) || "论文引用同步已启动",
        data: res,
      });
      toast("success", `✅ ${res.message || "论文引用同步已启动"}\n你可以在侧边栏或 Dashboard 查看进度`);
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
    if (!syncTopicId.trim()) return;
    setLoading("syncTopic", true);
    try {
      const res = await citationApi.syncTopic(syncTopicId);
      setResult("syncTopic", {
        success: true,
        message: (res.message as string) || "主题引用同步已启动",
        data: res,
      });
      toast("success", `✅ ${res.message || "主题引用同步已启动"}\n你可以在侧边栏或 Dashboard 查看进度`);
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
      toast("success", `✅ ${res.message || "增量引用同步已启动"}\n你可以在侧边栏或 Dashboard 查看进度`);
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
      setResult("dailyJob", {
        success: true,
        message: res.message || "每日任务已启动",
        data: res,
      });
      toast("success", `✅ ${res.message || "每日任务已启动"}\n你可以在侧边栏或 Dashboard 查看进度`);
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
      setResult("weeklyJob", {
        success: true,
        message: res.message || "每周图维护已启动",
        data: res,
      });
      toast("success", `✅ ${res.message || "每周图维护已启动"}\n你可以在侧边栏或 Dashboard 查看进度`);
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
    } finally {
      setLoading("health", false);
    }
  };

  return (
    <div className="animate-fade-in space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-ink">Operations</h1>
        <p className="mt-1 text-sm text-ink-secondary">
          引用同步、定时任务、系统检查等运维操作
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* 引用同步 */}
        <Card>
          <CardHeader
            title="引用同步"
            description="同步论文之间的引用关系"
            action={<Link2 className="h-5 w-5 text-ink-tertiary" />}
          />
          <div className="space-y-4">
            {/* 单篇同步 */}
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase tracking-wider text-ink-tertiary">
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
              <p className="text-xs font-medium uppercase tracking-wider text-ink-tertiary">
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
              <p className="text-xs font-medium uppercase tracking-wider text-ink-tertiary">
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
            action={<Calendar className="h-5 w-5 text-ink-tertiary" />}
          />
          <div className="space-y-4">
            {/* 每日任务 */}
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase tracking-wider text-ink-tertiary">
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
              <p className="text-xs font-medium uppercase tracking-wider text-ink-tertiary">
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
              <p className="text-xs font-medium uppercase tracking-wider text-ink-tertiary">
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
    </div>
  );
}

function ResultMessage({ result }: { result?: OperationResult }) {
  if (!result) return null;

  return (
    <div
      className={`flex items-start gap-2 rounded-lg px-3 py-2 text-sm ${
        result.success
          ? "bg-success-light text-success"
          : "bg-error-light text-error"
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
