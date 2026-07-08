import { Server } from "lucide-react";
import { cn } from "@/lib/utils";

export function ProviderBadge({ provider }: { provider: string }) {
  const colors: Record<string, string> = {
    xiaomi: "bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300",
    zhipu: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
    openai: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300",
    anthropic: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300",
  };
  const labels: Record<string, string> = {
    xiaomi: "小米 MiMo",
    zhipu: "智谱",
    openai: "OpenAI",
    anthropic: "Anthropic",
  };
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium", colors[provider] || "bg-hover text-ink-tertiary")}>
      <Server className="h-2.5 w-2.5" />
      {labels[provider] || provider}
    </span>
  );
}

export function StatusDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    succeeded: "bg-success",
    failed: "bg-error",
    running: "bg-info animate-pulse",
    pending: "bg-warning",
  };
  return <span className={cn("inline-block h-2 w-2 shrink-0 rounded-full", colors[status] || "bg-ink-tertiary")} />;
}
