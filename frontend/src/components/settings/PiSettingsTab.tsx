/**
 * Settings → Pi：Pi 网关/引擎适配面板
 * 展示 agent 引擎、pm 网关状态、物化模型与受控工具清单。
 * @author Color2333
 */
import { useCallback, useEffect, useState } from "react";
import { Sparkles, RefreshCw, Terminal, KeyRound, Wrench } from "lucide-react";
import { agentApi } from "@/services/api";
import { Spinner } from "@/components/ui/Spinner";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/utils";
import type { AgentEngineStatus } from "@/types";

export function PiSettingsTab() {
  const [engine, setEngine] = useState<AgentEngineStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setEngine(await agentApi.engine());
    } catch {
      setEngine(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="flex h-64 items-center justify-center"><Spinner /></div>;
  if (!engine) return <div className="text-ink-tertiary py-16 text-center text-sm">引擎状态不可用</div>;

  const isPi = engine.engine === "pi";

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-ink text-lg font-semibold">Pi 引擎</h2>
        <p className="text-ink-secondary mt-1 text-sm">
          Pi（PaperMind-Terminal 的 pm）是 agent 循环与 LLM 网关的唯一实现——
          聊天与后台管线共用同一出口。
        </p>
      </div>

      {/* 引擎状态 */}
      <div className="border-border bg-page rounded-xl border p-5">
        <div className="flex items-center gap-4">
          <div className={cn("flex h-12 w-12 items-center justify-center rounded-xl",
            isPi ? "bg-primary/20" : "bg-warning-light")}>
            <Sparkles className={cn("h-6 w-6", isPi ? "text-primary" : "text-warning")} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-ink font-medium">
                {isPi ? "Pi agent core" : "Python 回退引擎"}
              </span>
              <Badge variant={isPi ? "success" : "warning"}>{isPi ? "active" : "fallback"}</Badge>
            </div>
            <p className="text-ink-tertiary mt-1 text-xs">
              {isPi
                ? "终端 pm 与 Web 共用同一循环、同一工具集"
                : "服务端未安装 pm（PaperMind-Terminal）——聊天已自动回退，管线 LLM 走直连"}
            </p>
          </div>
          <button onClick={load} className="text-ink-secondary hover:bg-hover rounded-lg p-2" aria-label="刷新">
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* 模型物化 */}
      <div className="border-border bg-page rounded-xl border p-5">
        <div className="flex items-center gap-3">
          <KeyRound className="text-primary h-4 w-4" />
          <div className="min-w-0 flex-1">
            <p className="text-ink text-sm font-medium">模型物化</p>
            <p className="text-ink-tertiary mt-0.5 text-xs">
              {engine.chat_model
                ? <>当前模型 <span className="text-ink font-mono">{engine.provider}/{engine.chat_model}</span>
                   ——由 LLM 配置页激活项自动物化为 Pi 的 models.json，改动即时生效</>
                : "暂无激活的 LLM 配置——请到「LLM 配置」添加并激活"}
            </p>
          </div>
        </div>
      </div>

      {/* 网关 */}
      <div className="border-border bg-page rounded-xl border p-5">
        <div className="flex items-center gap-3">
          <Terminal className="text-primary h-4 w-4" />
          <div className="min-w-0 flex-1">
            <p className="text-ink text-sm font-medium">pm gateway（LLM 网关）</p>
            <p className="text-ink-tertiary mt-0.5 text-xs">
              PAPERMIND_LLM_GATEWAY=1 时管线文本补全统一经网关（embedding 例外直连）；
              网关不可用时自动回退直连
            </p>
          </div>
        </div>
      </div>

      {/* 工具清单 */}
      <div className="border-border bg-page rounded-xl border p-5">
        <div className="flex items-center gap-2">
          <Wrench className="text-primary h-4 w-4" />
          <p className="text-ink text-sm font-medium">受控工具集</p>
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {["pm_search_papers", "pm_get_paper", "pm_list_claims", "pm_get_claim_evidence",
            "pm_diff_research_state", "pm_export_research_pack", "pm_submit_job",
            "pm_get_job", "pm_list_jobs", "pm_cancel_job", "read/edit/write/grep/find/ls"].map((t) => (
            <span key={t} className="bg-hover text-ink-secondary rounded px-2 py-0.5 font-mono text-[10px]">
              {t}
            </span>
          ))}
        </div>
        <p className="text-ink-tertiary mt-3 text-xs">
          Pi 内置 coding 工具全部关闭；破坏性操作（提交/取消任务）经确认卡人工把关。
        </p>
      </div>
    </div>
  );
}
