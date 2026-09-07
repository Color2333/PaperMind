/**
 * Claude 风格的设置页面 - 左侧导航 + 右侧内容
 */
import { useState } from "react";
import { Sparkles, Cpu, Mail, GitBranch, Settings, ChevronRight, KeyRound } from "lucide-react";
import { cn } from "@/lib/utils";
import { LLMSettingsTab } from "@/components/settings/LLMSettingsTab";
import { EmailSettingsTab } from "@/components/settings/EmailSettingsTab";
import { OpsSettingsTab } from "@/components/settings/OpsSettingsTab";
import { TokensSettingsTab } from "@/components/settings/TokensSettingsTab";
import { PiSettingsTab } from "@/components/settings/PiSettingsTab";

type SettingsTab = "llm" | "pi" | "email" | "ops" | "tokens";

const NAV_ITEMS: { key: SettingsTab; label: string; icon: typeof Cpu }[] = [
  { key: "llm", label: "LLM 配置", icon: Cpu },
  { key: "pi", label: "Pi 引擎", icon: Sparkles },
  { key: "email", label: "邮箱与报告", icon: Mail },
  { key: "tokens", label: "API 令牌", icon: KeyRound },
  { key: "ops", label: "运维", icon: Settings },
];

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<SettingsTab>("llm");

  return (
    <div className="flex h-full">
      {/* 左侧边栏 */}
      <aside className="w-56 shrink-0 border-r border-border bg-page">
        <div className="p-4">
          <h1 className="mb-4 text-sm font-semibold text-ink">设置</h1>
          <nav className="space-y-0.5">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.key;
              return (
                <button
                  type="button"
                  key={item.key}
                  onClick={() => setActiveTab(item.key)}
                  className={cn(
                    "flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
                    isActive
                      ? "bg-primary/10 text-primary font-medium"
                      : "text-ink-secondary hover:bg-hover hover:text-ink"
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                  {isActive && <ChevronRight className="ml-auto h-3 w-3" />}
                </button>
              );
            })}
          </nav>
        </div>
      </aside>

      {/* 右侧内容 */}
      <main className="flex-1 overflow-y-auto bg-surface">
        <div className="mx-auto max-w-3xl p-8">
          {activeTab === "llm" && <LLMSettingsTab />}
          {activeTab === "pi" && <PiSettingsTab />}
          {activeTab === "email" && <EmailSettingsTab />}
          {activeTab === "tokens" && <TokensSettingsTab />}
          {activeTab === "ops" && <OpsSettingsTab />}
        </div>
      </main>
    </div>
  );
}
