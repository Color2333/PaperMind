/**
 * Tab 切换组件（支持 label 为 ReactNode，可带状态指示器）
 * @author Bamzc
 */
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

interface Tab {
  id: string;
  label: ReactNode;
}

interface TabsProps {
  tabs: Tab[];
  active: string;
  onChange: (id: string) => void;
  className?: string;
}

export function Tabs({ tabs, active, onChange, className }: TabsProps) {
  return (
    <div className={cn("flex gap-1 rounded-lg bg-hover p-1", className)}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md px-4 py-2 text-sm font-medium transition-all duration-150",
            active === tab.id
              ? "bg-surface text-ink shadow-sm"
              : "text-ink-secondary hover:text-ink"
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
