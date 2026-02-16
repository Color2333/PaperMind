/**
 * 侧边栏导航 - Claude 风格
 * @author Bamzc
 */
import { useState, useEffect } from "react";
import { NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";
import {
  LayoutDashboard,
  Tags,
  FileText,
  Network,
  BookOpen,
  MessageCircle,
  Newspaper,
  GitBranch,
  Settings,
  Sparkles,
  Cpu,
  Moon,
  Sun,
} from "lucide-react";

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/topics", icon: Tags, label: "Topics" },
  { to: "/papers", icon: FileText, label: "Papers" },
  { to: "/graph", icon: Network, label: "Graph Explorer" },
  { to: "/wiki", icon: BookOpen, label: "Wiki" },
  { to: "/chat", icon: MessageCircle, label: "AI Chat" },
  { to: "/brief", icon: Newspaper, label: "Daily Brief" },
  { to: "/pipelines", icon: GitBranch, label: "Pipelines" },
  { to: "/operations", icon: Settings, label: "Operations" },
  { to: "/settings", icon: Cpu, label: "LLM Settings" },
];

function useDarkMode() {
  const [dark, setDark] = useState(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem("theme") === "dark";
  });

  useEffect(() => {
    const root = document.documentElement;
    if (dark) {
      root.classList.add("dark");
      localStorage.setItem("theme", "dark");
    } else {
      root.classList.remove("dark");
      localStorage.setItem("theme", "light");
    }
  }, [dark]);

  return [dark, () => setDark((d) => !d)] as const;
}

export default function Sidebar() {
  const [dark, toggleDark] = useDarkMode();

  return (
    <aside className="fixed left-0 top-0 z-30 flex h-screen w-[240px] flex-col border-r border-border bg-sidebar">
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-5 py-5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
          <Sparkles className="h-4.5 w-4.5 text-white" />
        </div>
        <span className="text-lg font-semibold tracking-tight text-ink">PaperMind</span>
      </div>

      {/* 导航 */}
      <nav className="mt-2 flex-1 space-y-0.5 px-3">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-150",
                isActive
                  ? "bg-primary-light text-primary"
                  : "text-ink-secondary hover:bg-hover hover:text-ink"
              )
            }
          >
            <item.icon className="h-[18px] w-[18px] shrink-0" />
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>

      {/* 底部 */}
      <div className="border-t border-border px-4 py-4">
        <div className="flex items-center justify-between">
          <span className="text-xs text-ink-tertiary">PaperMind v0.1.0</span>
          <button
            onClick={toggleDark}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-ink-tertiary transition-colors hover:bg-hover hover:text-ink"
            title={dark ? "切换亮色模式" : "切换暗色模式"}
          >
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
        </div>
      </div>
    </aside>
  );
}
