import { useState } from "react";
import { BookOpen, Link2, Calendar, Network, Zap, Play } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { jobApi, citationApi, systemApi } from "@/services/api";
import { cn } from "@/lib/utils";

interface OpResult { success: boolean; message: string; }

export function OpsSettingsTab() {
  const [results, setResults] = useState<Record<string, OpResult>>({});
  const [loadings, setLoadings] = useState<Record<string, boolean>>({});

  const setL = (k: string, v: boolean) => setLoadings((p) => ({ ...p, [k]: v }));
  const setR = (k: string, r: OpResult) => setResults((p) => ({ ...p, [k]: r }));

  const ops = [
    { key: "batchProcess", label: "一键嵌入 & 粗读未读论文", desc: "对所有未读论文执行向量嵌入 + AI 粗读（并行处理）", icon: BookOpen, action: async () => { setL("batchProcess", true); try { const r = await jobApi.batchProcessUnread(50); setR("batchProcess", { success: r.failed === 0, message: r.message }); } catch (err) { setR("batchProcess", { success: false, message: err instanceof Error ? err.message : "失败" }); } finally { setL("batchProcess", false); } } },
    { key: "syncIncremental", label: "增量引用同步", desc: "同步论文之间的引用关系", icon: Link2, action: async () => { setL("syncIncremental", true); try { const r = await citationApi.syncIncremental(); setR("syncIncremental", { success: true, message: `同步完成，处理 ${r.processed_papers ?? 0} 篇，新增 ${r.edges_inserted} 条边` }); } catch (err) { setR("syncIncremental", { success: false, message: err instanceof Error ? err.message : "失败" }); } finally { setL("syncIncremental", false); } } },
    { key: "dailyJob", label: "执行每日任务", desc: "抓取论文 + 生成简报", icon: Calendar, action: async () => { setL("dailyJob", true); try { await jobApi.dailyRun(); setR("dailyJob", { success: true, message: "每日任务执行完成" }); } catch (err) { setR("dailyJob", { success: false, message: err instanceof Error ? err.message : "失败" }); } finally { setL("dailyJob", false); } } },
    { key: "weeklyJob", label: "每周图维护", desc: "引用同步 + 图谱维护", icon: Network, action: async () => { setL("weeklyJob", true); try { await jobApi.weeklyGraphRun(); setR("weeklyJob", { success: true, message: "每周维护执行完成" }); } catch (err) { setR("weeklyJob", { success: false, message: err instanceof Error ? err.message : "失败" }); } finally { setL("weeklyJob", false); } } },
    { key: "health", label: "系统健康检查", desc: "数据库 + 统计信息", icon: Zap, action: async () => { setL("health", true); try { const r = await systemApi.status(); setR("health", { success: r.health.status === "ok", message: `${r.health.status === "ok" ? "正常" : "异常"} | ${r.counts.topics} 主题 | ${r.counts.papers_latest_200} 论文` }); } catch (err) { setR("health", { success: false, message: err instanceof Error ? err.message : "失败" }); } finally { setL("health", false); } } },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-ink">运维操作</h2>
        <p className="mt-1 text-sm text-ink-secondary">执行系统维护和管理任务</p>
      </div>

      <div className="space-y-3">
        {ops.map((op) => {
          const Icon = op.icon;
          const result = results[op.key];
          const loading = loadings[op.key];
          return (
            <div key={op.key} className="rounded-xl border border-border bg-page p-5">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-4">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-hover">
                    <Icon className="h-5 w-5 text-ink-tertiary" />
                  </div>
                  <div>
                    <p className="font-medium text-ink">{op.label}</p>
                    <p className="text-xs text-ink-secondary">{op.desc}</p>
                  </div>
                </div>
                <Button variant="secondary" size="sm" onClick={() => op.action()} disabled={loading}>
                  {loading ? <><Spinner className="mr-1.5 h-3.5 w-3.5" />执行中</> : <><Play className="mr-1.5 h-3.5 w-3.5" />执行</>}
                </Button>
              </div>
              {result && (
                <div className={cn("mt-3 rounded-lg px-3 py-2 text-xs", result.success ? "bg-success/10 text-success" : "bg-error/10 text-error")}>
                  {result.message}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
