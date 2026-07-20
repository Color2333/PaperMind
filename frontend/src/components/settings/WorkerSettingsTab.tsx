import { useState, useCallback, useEffect } from "react";
import { Clock, RefreshCw } from "lucide-react";
import { useToast } from "@/contexts/ToastContext";
import { Spinner } from "@/components/ui/Spinner";
import { workerScheduleApi } from "@/services/api";
import { getErrorMessage } from "@/lib/errorHandler";
import { cn } from "@/lib/utils";
import type { WorkerScheduleConfig } from "@/types";

/**
 * Worker 调度配置 Tab
 *
 * 网页端修改 cron 表达式 / 闲时处理器开关后，worker 轮询线程在 30s 内
 * 检测到 updated_at 变化并热重载 APScheduler job，无需重启容器。
 *
 * 同步状态：last_applied_at（worker 写回）vs updated_at（前端写入）
 *   - last_applied_at >= updated_at → 已生效
 *   - 否则 → 等待 worker 同步中（最多 30s）
 */
type CronField = keyof Pick<WorkerScheduleConfig, "topic_dispatch_cron" | "cs_feed_dispatch_cron" | "weekly_graph_cron">;

const CRON_FIELDS: { field: CronField; label: string; desc: string; placeholder: string; hint: string }[] = [
  {
    field: "topic_dispatch_cron",
    label: "主题论文抓取",
    desc: "按主题订阅关键词从 ArXiv 抓取论文",
    placeholder: "0 * * * *",
    hint: "默认 0 * * * *（每小时整点）",
  },
  {
    field: "cs_feed_dispatch_cron",
    label: "CS 分类订阅",
    desc: "按 CS 分类目录同步并抓取订阅论文",
    placeholder: "5 * * * *",
    hint: "默认 5 * * * *（每小时 :05，错开避免抢线程）",
  },
  {
    field: "weekly_graph_cron",
    label: "每周图谱维护",
    desc: "同步论文引用关系 + 图谱增量维护",
    placeholder: "0 22 * * 0",
    hint: "默认 0 22 * * 0（UTC 周日 22:00 = 北京周一 06:00）",
  },
];

export function WorkerSettingsTab() {
  const { toast } = useToast();
  const [config, setConfig] = useState<WorkerScheduleConfig | null>(null);
  const [localConfig, setLocalConfig] = useState<WorkerScheduleConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  // 手动刷新同步状态用（点击刷新按钮重新拉 last_applied_at）
  const [refreshing, setRefreshing] = useState(false);

  const loadConfig = useCallback(async () => {
    try {
      const data = await workerScheduleApi.getConfig();
      setConfig(data);
      setLocalConfig(data);
    } catch {
      toast("error", "加载 Worker 调度配置失败");
    }
  }, [toast]);

  useEffect(() => {
    loadConfig().finally(() => setLoading(false));
  }, [loadConfig]);

  const handleUpdateConfig = async (updates: Partial<WorkerScheduleConfig>) => {
    setSubmitting(true);
    try {
      const data = await workerScheduleApi.updateConfig(updates as Record<string, unknown>);
      if (data.config) {
        setConfig(data.config);
        setLocalConfig(data.config);
        toast("success", "已保存，worker 将在 30s 内自动同步");
      }
    } catch (err) {
      toast("error", getErrorMessage(err));
      await loadConfig();
    } finally {
      setSubmitting(false);
    }
  };

  const handleInputChange = (field: CronField, value: string) => {
    setLocalConfig((prev) => (prev ? { ...prev, [field]: value } : prev));
  };

  const handleInputBlur = (field: CronField) => {
    if (!localConfig || !config) return;
    if (localConfig[field] !== config[field]) {
      handleUpdateConfig({ [field]: localConfig[field] });
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const data = await workerScheduleApi.getConfig();
      setConfig(data);
      // 不覆盖 localConfig（避免用户正在编辑的内容被覆盖）
      setLocalConfig((prev) => (prev ? { ...data, ...prev } : data));
    } catch (err) {
      toast("error", getErrorMessage(err));
    } finally {
      setRefreshing(false);
    }
  };

  // 同步状态判定：last_applied_at >= updated_at 即已生效
  const computeSyncStatus = (): { synced: boolean; label: string } => {
    if (!config) return { synced: false, label: "未知" };
    if (!config.last_applied_at) {
      return { synced: false, label: "worker 尚未应用过配置" };
    }
    const applied = new Date(config.last_applied_at).getTime();
    const updated = new Date(config.updated_at).getTime();
    if (applied >= updated) {
      const ageSec = Math.floor((Date.now() - applied) / 1000);
      return { synced: true, label: `已生效（${ageSec}s 前 worker 已同步）` };
    }
    return { synced: false, label: "等待 worker 同步中（最多 30s）" };
  };

  if (loading) return <div className="flex h-64 items-center justify-center"><Spinner /></div>;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-ink">Worker / 调度</h2>
        <p className="mt-1 text-sm text-ink-secondary">
          管理 worker 定时任务调度。修改后 worker 在 30s 内自动热重载，无需重启。
        </p>
      </div>

      {/* 同步状态指示器 */}
      <div className="flex items-center justify-between rounded-xl border border-border bg-page p-4">
        <div className="flex items-center gap-3">
          <div className={cn(
            "flex h-9 w-9 items-center justify-center rounded-lg",
            computeSyncStatus().synced ? "bg-success/10" : "bg-warning/10"
          )}>
            <RefreshCw className={cn("h-4 w-4", computeSyncStatus().synced ? "text-success" : "text-warning", refreshing && "animate-spin")} />
          </div>
          <div>
            <p className="text-sm font-medium text-ink">同步状态</p>
            <p className="text-xs text-ink-secondary">{computeSyncStatus().label}</p>
          </div>
        </div>
        <button
          type="button"
          onClick={handleRefresh}
          disabled={refreshing}
          className="rounded-lg border border-border bg-surface px-3 py-1.5 text-xs text-ink-secondary hover:bg-hover disabled:opacity-50"
        >
          {refreshing ? "刷新中..." : "刷新状态"}
        </button>
      </div>

      {/* cron 配置卡片 */}
      <div className="space-y-3">
        {CRON_FIELDS.map((item) => (
          <div key={item.field} className="rounded-xl border border-border bg-page p-5">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <p className="font-medium text-ink">{item.label}</p>
                <p className="mt-0.5 text-xs text-ink-secondary">{item.desc}</p>
              </div>
            </div>
            <div className="mt-3 space-y-1">
              <label htmlFor={item.field} className="text-[10px] font-medium text-ink-secondary">
                Cron 表达式（UTC 时间）
              </label>
              <input
                id={item.field}
                type="text"
                placeholder={item.placeholder}
                value={localConfig?.[item.field] ?? config?.[item.field] ?? item.placeholder}
                onChange={(e) => handleInputChange(item.field, e.target.value)}
                onBlur={() => handleInputBlur(item.field)}
                disabled={submitting}
                className="w-full rounded border border-border bg-surface px-2.5 py-1.5 font-mono text-xs text-ink placeholder:text-ink-placeholder disabled:opacity-60"
              />
              <p className="text-[10px] text-ink-tertiary">
                {item.hint}
                <br />
                格式：<code className="font-mono">分 时 日 月 周</code>（UTC，北京时间 = UTC + 8）
              </p>
            </div>
          </div>
        ))}
      </div>

      {/* 闲时处理器开关 */}
      <div className="rounded-xl border border-border bg-page p-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
              <Clock className="h-5 w-5 text-primary" />
            </div>
            <div>
              <p className="font-medium text-ink">闲时自动处理器</p>
              <p className="text-xs text-ink-secondary">
                worker 空闲时自动嵌入并粗读未处理论文
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => config && handleUpdateConfig({ idle_processor_enabled: !config.idle_processor_enabled })}
            disabled={submitting || !config}
            className={cn(
              "relative h-6 w-11 rounded-full transition-colors disabled:opacity-60",
              config?.idle_processor_enabled ? "bg-primary" : "bg-ink-tertiary"
            )}
          >
            <span className={cn(
              "absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform",
              config?.idle_processor_enabled ? "translate-x-6" : "translate-x-0.5"
            )} />
          </button>
        </div>
        <p className="mt-3 text-[10px] text-ink-tertiary">
          关闭后 worker 不会在空闲时段自动处理论文，但已调度的 cron 任务仍正常执行
        </p>
      </div>

      {/* 说明区 */}
      <div className="rounded-xl border border-dashed border-border bg-page p-4">
        <p className="text-[11px] leading-relaxed text-ink-tertiary">
          <span className="font-medium text-ink-secondary">说明：</span>
          所有 cron 基于 UTC 时间，北京时间 = UTC + 8。修改保存后 worker 轮询线程在 30s 内
          检测到变化并重排 APScheduler job（<code className="font-mono">replace_existing=True</code>），
          无需重启容器。每日简报的 cron 在「邮箱与报告」tab 单独配置。
        </p>
      </div>
    </div>
  );
}
