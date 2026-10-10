/**
 * CommandPalette - ⌘K 全局命令面板
 * 论文搜索 + 页面跳转 + 快捷动作；键盘优先（↑↓ 选择，Enter 执行，Esc 关闭）
 * @author Color2333
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Search, FileText, Network, BookOpen, PenTool, Newspaper,
  LayoutDashboard, Settings, ListTodo, BarChart3, MessageSquare,
  Moon, Sun, Plus, CornerDownLeft, Loader2, SearchX,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { paperApi } from "@/services/api";
import type { Paper } from "@/types";

interface CmdItem {
  id: string;
  label: string;
  hint?: string;
  icon: typeof Search;
  group: "页面" | "论文" | "动作";
  keywords?: string;
  run: () => void;
}

export default function CommandPalette({
  open,
  onClose,
  onToggleTheme,
}: {
  open: boolean;
  onClose: () => void;
  onToggleTheme: () => void;
}) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [papers, setPapers] = useState<Paper[]>([]);
  const [searching, setSearching] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // 打开时聚焦 + 重置
  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [open]);

  // 论文搜索（防抖 250ms）
  useEffect(() => {
    if (!open) return;
    const q = query.trim();
    if (q.length < 2) {
      setPapers([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    const t = setTimeout(() => {
      paperApi
        .latest({ search: q, pageSize: 6 })
        .then((r) => setPapers((r.items ?? []) as unknown as Paper[]))
        .catch(() => setPapers([]))
        .finally(() => setSearching(false));
    }, 250);
    return () => clearTimeout(t);
  }, [query, open]);

  const pageItems: CmdItem[] = useMemo(
    () => [
      { id: "nav-papers", label: "论文库", icon: FileText, group: "页面", run: () => navigate("/papers") },
      { id: "nav-collect", label: "论文收集", icon: Search, group: "页面", run: () => navigate("/collect") },
      { id: "nav-graph", label: "引用图谱", icon: Network, group: "页面", run: () => navigate("/graph") },
      { id: "nav-agent", label: "Agent 对话", icon: MessageSquare, group: "页面", run: () => navigate("/") },
      { id: "nav-research", label: "Research", icon: BookOpen, group: "页面", run: () => navigate("/research") },
      { id: "nav-writing", label: "写作助手", icon: PenTool, group: "页面", run: () => navigate("/writing") },
      { id: "nav-wiki", label: "Wiki", icon: BookOpen, group: "页面", run: () => navigate("/wiki") },
      { id: "nav-brief", label: "研究简报", icon: Newspaper, group: "页面", run: () => navigate("/brief") },
      { id: "nav-dashboard", label: "看板", icon: LayoutDashboard, group: "页面", run: () => navigate("/dashboard") },
      { id: "nav-jobs", label: "任务监控", icon: ListTodo, group: "页面", run: () => navigate("/jobs") },
      { id: "nav-statistics", label: "主题统计", icon: BarChart3, group: "页面", run: () => navigate("/statistics") },
      { id: "nav-settings", label: "设置", icon: Settings, group: "页面", run: () => navigate("/settings") },
    ],
    [navigate],
  );

  const actionItems: CmdItem[] = useMemo(
    () => [
      { id: "act-new-chat", label: "新建对话", icon: Plus, group: "动作", run: () => navigate("/") },
      { id: "act-theme", label: "切换深色/浅色", icon: Moon, group: "动作", run: onToggleTheme },
    ],
    [navigate, onToggleTheme],
  );

  const paperItems: CmdItem[] = useMemo(
    () =>
      papers.map((p) => ({
        id: `paper-${p.id}`,
        label: p.title,
        hint: p.read_status === "deep_read" ? "已精读" : p.read_status === "skimmed" ? "已粗读" : "未读",
        icon: FileText,
        group: "论文" as const,
        run: () => navigate(`/papers/${p.id}`),
      })),
    [papers, navigate],
  );

  // 过滤页面/动作项（论文项已由服务端搜索过滤）
  const q = query.trim().toLowerCase();
  const filteredPages = pageItems.filter(
    (i) => !q || i.label.toLowerCase().includes(q) || i.keywords?.includes(q),
  );
  const filteredActions = actionItems.filter(
    (i) => !q || i.label.toLowerCase().includes(q),
  );
  const flat = useMemo(
    () => [...filteredPages, ...paperItems, ...filteredActions],
    [filteredPages, paperItems, filteredActions],
  );

  // 键盘导航
  const onKey = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive((a) => Math.min(a + 1, flat.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive((a) => Math.max(a - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        flat[active]?.run();
        onClose();
      } else if (e.key === "Escape") {
        onClose();
      }
    },
    [flat, active, onClose],
  );

  // active 项滚入视野
  useEffect(() => {
    listRef.current
      ?.querySelector(`[data-idx="${active}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [active]);

  if (!open) return null;

  let renderIdx = -1;
  const group = (label: string, items: CmdItem[]) => {
    const vis = items.filter(() => true);
    if (vis.length === 0) return null;
    return (
      <div key={label} className="mb-1">
        <p className="text-ink-tertiary px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider">
          {label}
        </p>
        {vis.map((item) => {
          renderIdx += 1;
          const idx = renderIdx;
          return (
            <button
              key={item.id}
              data-idx={idx}
              onMouseEnter={() => setActive(idx)}
              onClick={() => {
                item.run();
                onClose();
              }}
              className={cn(
                "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm transition-colors",
                idx === active ? "bg-primary-light text-primary" : "text-ink hover:bg-hover",
              )}
            >
              <item.icon className="h-4 w-4 shrink-0" />
              <span className="min-w-0 flex-1 truncate">{item.label}</span>
              {item.hint && (
                <span className="text-ink-tertiary shrink-0 text-[10px]">{item.hint}</span>
              )}
              {idx === active && <CornerDownLeft className="text-ink-tertiary h-3 w-3 shrink-0" />}
            </button>
          );
        })}
      </div>
    );
  };

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center bg-black/40 pt-[12vh] backdrop-blur-[2px]"
      onClick={onClose}
    >
      <div
        className="animate-scale-in bg-surface border-border shadow-warm-xl w-full max-w-xl overflow-hidden rounded-2xl border"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-border-light flex items-center gap-3 border-b px-4">
          <Search className="text-ink-tertiary h-4 w-4 shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            onKeyDown={onKey}
            placeholder="搜索论文、跳转页面、执行动作…"
            className="text-ink placeholder:text-ink-placeholder h-12 flex-1 bg-transparent text-sm outline-none"
          />
          {searching && <Loader2 className="text-ink-tertiary h-4 w-4 animate-spin" />}
          <kbd className="text-ink-tertiary border-border rounded border px-1.5 py-0.5 text-[10px]">
            ESC
          </kbd>
        </div>
        <div ref={listRef} className="max-h-[50vh] overflow-y-auto p-2">
          {flat.length === 0 && !searching && (
            <div className="text-ink-tertiary flex flex-col items-center gap-2 py-10 text-sm">
              <SearchX className="h-6 w-6" />
              无匹配结果
            </div>
          )}
          {group("页面", filteredPages)}
          {group("论文", paperItems)}
          {group("动作", filteredActions)}
        </div>
        <div className="border-border-light text-ink-tertiary flex items-center gap-4 border-t px-4 py-2 text-[10px]">
          <span>↑↓ 选择</span>
          <span className="flex items-center gap-1">
            <CornerDownLeft className="h-3 w-3" /> 执行
          </span>
          <span>ESC 关闭</span>
        </div>
      </div>
    </div>
  );
}
