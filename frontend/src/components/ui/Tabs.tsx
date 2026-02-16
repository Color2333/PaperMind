/**
 * Tab切换组件
 * @author Bamzc
 */
import { cn } from "@/lib/utils";

interface Tab {
  id: string;
  label: string;
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
            "rounded-md px-4 py-2 text-sm font-medium transition-all duration-150",
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
