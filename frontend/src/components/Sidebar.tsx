/**
 * 侧边栏 - AI 应用风格：图标网格 + 对话历史 + 设置弹窗
 * @author Bamzc
 */
import { useState, useEffect, useMemo, useCallback } from "react";
import { NavLink, useNavigate, useLocation } from "react-router-dom";
import { cn } from "@/lib/utils";
import { useConversationCtx } from "@/contexts/ConversationContext";
import { useGlobalTasks } from "@/contexts/GlobalTaskContext";
import { groupByDate } from "@/hooks/useConversations";
import { SettingsDialog } from "./SettingsDialog";
import ConfirmDialog from "@/components/ConfirmDialog";
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
  Menu,
  X,
  PenTool,
  Loader2,
} from "lucide-react";
import { paperApi } from "@/services/api";

/* 工具网格定义 */
const TOOLS = [
  { to: "/collect", icon: Search, label: "论文收集", accent: true },
  { to: "/papers", icon: FileText, label: "论文库", accent: false },
  { to: "/graph", icon: Network, label: "引用图谱", accent: false },
  { to: "/writing", icon: PenTool, label: "写作助手", accent: true },
  { to: "/wiki", icon: BookOpen, label: "Wiki", accent: false },
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
  const [mobileOpen, setMobileOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [unreadCount, setUnreadCount] = useState(0);
  const navigate = useNavigate();
  const location = useLocation();
  const { activeTasks, hasRunning } = useGlobalTasks();

  useEffect(() => {
    const fetchUnread = () => {
      paperApi.folderStats().then((s: any) => {
        setUnreadCount(s.by_status?.unread ?? 0);
      }).catch(() => {});
    };
    fetchUnread();
    const timer = setInterval(fetchUnread, 30000);
    return () => clearInterval(timer);
  }, [location.pathname]);
  const {
    metas,
    activeId,
    createConversation,
    switchConversation,
    deleteConversation,
  } = useConversationCtx();
  const groups = useMemo(() => groupByDate(metas), [metas]);

  /* 路由变化时关闭移动端侧边栏 */
  useEffect(() => { setMobileOpen(false); }, [location.pathname]);

  const handleNewChat = useCallback(() => {
    createConversation();
    if (location.pathname !== "/") navigate("/");
    setMobileOpen(false);
  }, [createConversation, location.pathname, navigate]);

  const handleSelectChat = useCallback((id: string) => {
    switchConversation(id);
    if (location.pathname !== "/") navigate("/");
    setMobileOpen(false);
  }, [switchConversation, location.pathname, navigate]);

  return (
    <>
      {/* 移动端汉堡菜单 */}
      <button
        onClick={() => setMobileOpen(true)}
        className="fixed left-3 top-3 z-40 rounded-lg bg-surface p-2 shadow-md lg:hidden"
        aria-label="打开菜单"
      >
        <Menu className="h-5 w-5 text-ink" />
      </button>

      {/* 移动端遮罩 */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <aside className={cn(
        "fixed left-0 top-0 z-50 flex h-screen w-[240px] flex-col border-r border-border bg-sidebar transition-transform duration-200",
        mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
      )}>
        {/* 移动端关闭按钮 */}
        <button
          onClick={() => setMobileOpen(false)}
          className="absolute right-2 top-3 rounded-lg p-1.5 text-ink-tertiary hover:bg-hover lg:hidden"
          aria-label="关闭菜单"
        >
          <X className="h-4 w-4" />
        </button>
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

        {/* 活跃任务进度条 */}
        {hasRunning && activeTasks.length > 0 && (
          <div className="mx-3 mb-2 rounded-xl bg-gradient-to-r from-primary/10 to-info/10 border border-primary/20 p-3">
            <div className="mb-2 flex items-center gap-2">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
              <span className="text-xs font-semibold text-primary">运行中</span>
            </div>
            {activeTasks.slice(0, 2).map((task) => (
              <div key={task.task_id} className="mb-2 last:mb-0">
                <div className="mb-1 flex items-center justify-between text-[11px]">
                  <span className="font-medium text-ink truncate flex-1">{task.title}</span>
                  <span className="ml-2 text-ink-tertiary shrink-0">{task.progress_pct}%</span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-page">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-primary to-info transition-all duration-300"
                    style={{ width: `${task.progress_pct}%` }}
                  />
                </div>
                <p className="mt-1 text-[10px] text-ink-secondary truncate">{task.message}</p>
              </div>
            ))}
            {activeTasks.length > 2 && (
              <p className="text-[10px] text-ink-tertiary">
                还有 {activeTasks.length - 2} 个任务正在运行...
              </p>
            )}
          </div>
        )}

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
                    "relative flex flex-col items-center gap-1 rounded-xl px-1 py-2.5 text-center transition-all",
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
                {tool.to === "/papers" && unreadCount > 0 && (
                  <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[9px] font-bold text-white">
                    {unreadCount > 99 ? "99+" : unreadCount}
                  </span>
                )}
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
                          setDeleteId(meta.id);
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

      <ConfirmDialog
        open={!!deleteId}
        title="删除对话"
        description="删除后无法恢复，确定要删除这个对话吗？"
        variant="danger"
        confirmLabel="删除"
        onConfirm={() => { if (deleteId) { deleteConversation(deleteId); setDeleteId(null); } }}
        onCancel={() => setDeleteId(null)}
      />
    </>
  );
}
