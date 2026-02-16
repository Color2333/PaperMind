/**
 * 侧边栏 - AI 应用风格：图标网格 + 对话历史 + 设置弹窗
 * @author Bamzc
 */
import { useState, useEffect } from "react";
import { NavLink, useNavigate, useLocation } from "react-router-dom";
import { cn } from "@/lib/utils";
import { useConversationCtx } from "@/contexts/ConversationContext";
import { groupByDate } from "@/hooks/useConversations";
import { SettingsDialog } from "./SettingsDialog";
import {
  FileText,
  Network,
  BookOpen,
  Newspaper,
  Sparkles,
  Moon,
  Sun,
  Plus,
  MessageSquare,
  Trash2,
  LayoutDashboard,
  Settings,
  Search,
} from "lucide-react";

/* 工具网格定义 */
const TOOLS = [
  { to: "/collect", icon: Search, label: "论文收集", accent: true },
  { to: "/papers", icon: FileText, label: "论文库", accent: false },
  { to: "/graph", icon: Network, label: "引用图谱", accent: false },
  { to: "/wiki", icon: BookOpen, label: "Wiki", accent: true },
  { to: "/brief", icon: Newspaper, label: "研究简报", accent: false },
  { to: "/dashboard", icon: LayoutDashboard, label: "看板", accent: false },
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
  const [showSettings, setShowSettings] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const {
    metas,
    activeId,
    createConversation,
    switchConversation,
    deleteConversation,
  } = useConversationCtx();
  const groups = groupByDate(metas);

  const handleNewChat = () => {
    createConversation();
    if (location.pathname !== "/") navigate("/");
  };

  const handleSelectChat = (id: string) => {
    switchConversation(id);
    if (location.pathname !== "/") navigate("/");
  };

  return (
    <>
      <aside className="fixed left-0 top-0 z-30 flex h-screen w-[240px] flex-col border-r border-border bg-sidebar">
        {/* Logo + 新建对话 */}
        <div className="px-3 pt-4 pb-2">
          <div className="mb-3 flex items-center gap-2.5 px-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary">
              <Sparkles className="h-3.5 w-3.5 text-white" />
            </div>
            <span className="text-base font-semibold tracking-tight text-ink">
              PaperMind
            </span>
          </div>
          <button
            onClick={handleNewChat}
            className="flex w-full items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2.5 text-sm font-medium text-ink transition-all hover:bg-hover hover:shadow-sm"
          >
            <Plus className="h-4 w-4" />
            新对话
          </button>
        </div>

        {/* 工具网格 */}
        <div className="border-b border-border px-3 pb-3">
          <p className="mb-1.5 px-1 text-[10px] font-semibold uppercase tracking-wider text-ink-tertiary">
            工具
          </p>
          <div className="grid grid-cols-3 gap-1.5">
            {TOOLS.map((tool) => (
              <NavLink
                key={tool.to}
                to={tool.to}
                className={({ isActive }) =>
                  cn(
                    "flex flex-col items-center gap-1 rounded-xl px-1 py-2.5 text-center transition-all",
                    isActive
                      ? "bg-primary-light text-primary shadow-sm"
                      : tool.accent
                        ? "bg-page text-ink-secondary hover:bg-hover hover:text-ink"
                        : "text-ink-tertiary hover:bg-hover hover:text-ink-secondary",
                  )
                }
              >
                <tool.icon className="h-4.5 w-4.5" />
                <span className="text-[10px] font-medium leading-tight">
                  {tool.label}
                </span>
              </NavLink>
            ))}
          </div>
        </div>

        {/* 对话历史 */}
        <div className="flex-1 overflow-y-auto px-3 pt-2">
          <p className="mb-1 px-1 text-[10px] font-semibold uppercase tracking-wider text-ink-tertiary">
            对话历史
          </p>
          {groups.length === 0 ? (
            <p className="px-2 py-4 text-center text-xs text-ink-tertiary">
              还没有对话记录
            </p>
          ) : (
            groups.map((group) => (
              <div key={group.label} className="mb-3">
                <p className="mb-0.5 px-2 text-[10px] font-semibold uppercase tracking-wider text-ink-tertiary">
                  {group.label}
                </p>
                <div className="space-y-0.5">
                  {group.items.map((meta) => (
                    <button
                      key={meta.id}
                      onClick={() => handleSelectChat(meta.id)}
                      className={cn(
                        "group flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] transition-all",
                        activeId === meta.id
                          ? "bg-primary-light text-primary font-medium"
                          : "text-ink-secondary hover:bg-hover hover:text-ink",
                      )}
                    >
                      <MessageSquare className="h-3.5 w-3.5 shrink-0" />
                      <span className="flex-1 truncate">{meta.title}</span>
                      <span
                        onClick={(e) => {
                          e.stopPropagation();
                          deleteConversation(meta.id);
                        }}
                        className="hidden shrink-0 rounded p-0.5 text-ink-tertiary hover:bg-error-light hover:text-error group-hover:block"
                      >
                        <Trash2 className="h-3 w-3" />
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>

        {/* 底部：设置 + 暗色 */}
        <div className="border-t border-border px-3 py-2">
          <div className="flex items-center justify-between px-1">
            <button
              onClick={() => setShowSettings(true)}
              className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-medium text-ink-secondary transition-colors hover:bg-hover hover:text-ink"
            >
              <Settings className="h-3.5 w-3.5" />
              设置
            </button>
            <div className="flex items-center gap-1">
              <span className="text-[10px] text-ink-tertiary">v0.2.0</span>
              <button
                onClick={toggleDark}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-ink-tertiary transition-colors hover:bg-hover hover:text-ink"
                title={dark ? "亮色" : "暗色"}
              >
                {dark ? (
                  <Sun className="h-3.5 w-3.5" />
                ) : (
                  <Moon className="h-3.5 w-3.5" />
                )}
              </button>
            </div>
          </div>
        </div>
      </aside>

      {/* 设置弹窗 */}
      {showSettings && (
        <SettingsDialog onClose={() => setShowSettings(false)} />
      )}
    </>
  );
}
