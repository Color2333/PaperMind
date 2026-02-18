/**
 * Graph Explorer - 知识图谱探索（3 大面板：全局概览 / 引文分析 / 领域洞察）
 * @author Bamzc
 */
import { useState } from "react";
import { Compass, Network, TrendingUp } from "lucide-react";
import OverviewPanel from "@/components/graph/OverviewPanel";
import CitationPanel from "@/components/graph/CitationPanel";
import InsightPanel from "@/components/graph/InsightPanel";

const TABS = [
  { id: "overview", label: "全局概览", icon: Compass },
  { id: "citation", label: "引文分析", icon: Network },
  { id: "insight", label: "领域洞察", icon: TrendingUp },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function GraphExplorer() {
  const [activeTab, setActiveTab] = useState<TabId>("overview");

  return (
    <div className="animate-fade-in space-y-6">
      {/* 页面头 */}
      <div className="page-hero rounded-2xl p-6">
        <div className="flex items-center gap-3">
          <div className="rounded-xl bg-primary/10 p-2.5">
            <Compass className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-ink">知识图谱</h1>
            <p className="mt-0.5 text-sm text-ink-secondary">探索引用关系、领域时间线和知识脉络</p>
          </div>
        </div>
      </div>

      {/* 功能标签 — 3 个大 tab */}
      <div className="flex gap-1 rounded-2xl bg-page p-1.5">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex flex-1 items-center justify-center gap-2 rounded-xl py-2.5 text-sm font-medium transition-all ${
              activeTab === tab.id
                ? "bg-surface text-primary shadow-sm"
                : "text-ink-tertiary hover:text-ink"
            }`}
          >
            <tab.icon className="h-4 w-4" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* 面板内容 */}
      {activeTab === "overview" && <OverviewPanel />}
      {activeTab === "citation" && <CitationPanel />}
      {activeTab === "insight" && <InsightPanel />}
    </div>
  );
}
