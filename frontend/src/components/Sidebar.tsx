/**
 * 侧边栏 - AI 应用风格：图标网格 + 对话历史 + 设置弹窗
 * @author Color2333
 */
import { useState, useEffect, useMemo, useCallback } from "react";
import { NavLink, useNavigate, useLocation } from "react-router-dom";
import { cn } from "@/lib/utils";
import { useConversationCtx } from "@/contexts/ConversationContext";
import { useGlobalTasks } from "@/contexts/GlobalTaskContext";
import { groupByDate } from "@/hooks/useConversations";
import ConfirmDialog from "@/components/ConfirmDialog";
import LogoIcon from "@/assets/logo-icon.svg?react";
import {
  FileText,
  Network,
  BookOpen,
  Newspaper,
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
  BarChart3,
  ListTodo,
  PenTool,
  Loader2,
  LogOut,
} from "lucide-react";
import { paperApi, clearAuth } from "@/services/api";

/* 工具网格定义——研究主线分组：收集→沉淀→产出→观测 */
const TOOL_GROUPS: { label: string; items: { to: string; icon: typeof Search; label: string }[] }[] = [
  {
    label: "研究",
    items: [
      { to: "/collect", icon: Search, label: "论文收集" },
      { to: "/papers", icon: FileText, label: "论文库" },
      { to: "/graph", icon: Network, label: "引用图谱" },
      { to: "/research", icon: BookOpen, label: "Research" },
    ],
  },
  {
    label: "产出",
    items: [
      { to: "/writing", icon: PenTool, label: "写作助手" },
      { to: "/wiki", icon: BookOpen, label: "Wiki" },
      { to: "/brief", icon: Newspaper, label: "研究简报" },
    ],
  },
  {
    label: "系统",
    items: [
      { to: "/dashboard", icon: LayoutDashboard, label: "看板" },
      { to: "/jobs", icon: ListTodo, label: "任务监控" },
      { to: "/statistics", icon: BarChart3, label: "主题统计" },
    ],
  },
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
  const [mobileOpen, setMobileOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [unreadCount, setUnreadCount] = useState(0);
  const navigate = useNavigate();
  const location = useLocation();
  const { activeTasks, hasRunning } = useGlobalTasks();

  // folder-stats 每 60s 轮询一次，与路由无关（路由变化不重新注册 interval）
  useEffect(() => {
    const fetchUnread = () => {
      paperApi.folderStats().then((s) => {
        setUnreadCount(s.by_status?.unread ?? 0);
      }).catch(() => {});
    };
    fetchUnread();
    let timer: ReturnType<typeof setInterval> | null = setInterval(fetchUnread, 60000);
    // visibility 暂停：后台标签不再每 60s 拉文件夹统计
    const onVisibility = () => {
      if (document.hidden) {
        if (timer) { clearInterval(timer); timer = null; }
      } else {
        fetchUnread();
        timer = setInterval(fetchUnread, 60000);
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      if (timer) clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);
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
        "border-border bg-sidebar relative flex h-screen w-[240px] shrink-0 flex-col border-r",
        mobileOpen && "fixed left-0 top-0 z-50 h-screen translate-x-0"
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
            <LogoIcon className="h-7 w-7 text-primary" />
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

        {hasRunning && activeTasks.length > 0 && (
          <div className="mx-3 mb-2 rounded-xl bg-gradient-to-r from-primary/10 to-info/10 border border-primary/20 px-3 py-2">
            <div className="flex items-center gap-2">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-primary shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-primary truncate">
                  {activeTasks.length} 个任务进行中
                </p>
                <p className="text-[10px] text-ink-secondary truncate">
                  {activeTasks[0]?.title || ""}
                  {activeTasks.length > 1 ? ` 等${activeTasks.length}个` : ""}
                </p>
              </div>
              <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center shrink-0">
                <span className="text-xs font-bold text-primary">{activeTasks[0]?.progress_pct || 0}%</span>
              </div>
            </div>
          </div>
        )}

        {/* 工具网格——研究主线分组 */}
        <div className="border-b border-border px-3 pb-3">
          {TOOL_GROUPS.map((group) => (
            <div key={group.label} className="mb-2.5 last:mb-0">
              <p className="mb-1.5 px-1 text-[10px] font-semibold uppercase tracking-wider text-ink-tertiary">
                {group.label}
              </p>
              <div className="grid grid-cols-3 gap-1.5">
                {group.items.map((tool) => (
                  <NavLink
                    key={tool.to}
                    to={tool.to}
                    className={({ isActive }) =>
                      cn(
                        "relative flex flex-col items-center gap-1 rounded-xl px-1 py-2.5 text-center transition-all",
                        isActive
                          ? "bg-primary-light text-primary shadow-sm"
                          : "text-ink-secondary hover:bg-hover hover:text-ink",
                      )
                    }
                  >
                    <tool.icon className="h-[18px] w-[18px]" />
                    <span className="text-[10px] leading-tight">{tool.label}</span>
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* 会话列表已迁至对话窄栏（ChatPane）——侧栏只保留工具导航 */}

        {/* 底部：设置 + 暗色 */}
        <div className="border-t border-border px-3 py-2">
          <div className="flex items-center justify-between px-1">
            <button
              onClick={() => navigate("/settings")}
              className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-medium text-ink-secondary transition-colors hover:bg-hover hover:text-ink"
            >
              <Settings className="h-3.5 w-3.5" />
              设置
            </button>
            <div className="flex items-center gap-1">
              <span className="text-[10px] text-ink-tertiary">v0.2.0</span>
              <button
                onClick={() => { clearAuth(); window.location.reload(); }}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-ink-tertiary transition-colors hover:bg-hover hover:text-red-500"
                title="退出登录"
              >
                <LogOut className="h-3.5 w-3.5" />
              </button>
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
