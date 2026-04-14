/**
 * Papers - 论文库（分页 + 文件夹/日期分类导航）
 * @author Color2333
 */
import { useEffect, useState, useCallback, useMemo, useRef, memo } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Badge, Empty, Spinner, Modal, Input } from "@/components/ui";
import { PaperListSkeleton } from "@/components/Skeleton";
import { useToast } from "@/contexts/ToastContext";
import { paperApi, ingestApi, topicApi, pipelineApi, actionApi, tasksApi, tagApi } from "@/services/api";
import { formatDate, truncate } from "@/lib/utils";
import type { Paper, Topic, FolderStats, CollectionAction, Tag as TagType } from "@/types";
import {
  FileText,
  Download,
  Search,
  RefreshCw,
  ExternalLink,
  BookOpen,
  Eye,
  BookMarked,
  ChevronRight,
  ChevronLeft,
  Cpu,
  Zap,
  CheckCircle2,
  Heart,
  LayoutGrid,
  LayoutList,
  Folder,
  FolderOpen,
  Clock,
  Inbox,
  Library,
  Tag,
  Calendar,
  ChevronsLeft,
  ChevronsRight,
  Bot,
  CalendarClock,
  ArrowUp,
  ArrowDown,
  Plus,
  X,
  Edit2,
  Trash2,
} from "lucide-react";

/* ========== 类型 ========== */
interface FolderItem {
  id: string;
  type: "special" | "topic" | "date";
  name: string;
  icon: React.ReactNode;
  count: number;
  color: string;
  /** 日期筛选用 */
  dateStr?: string;
}

const statusBadge: Record<string, { label: string; variant: "default" | "warning" | "success" }> = {
  unread: { label: "未读", variant: "default" },
  skimmed: { label: "已粗读", variant: "warning" },
  deep_read: { label: "已精读", variant: "success" },
};

/**
 * 格式化日期为中文标签
 */
function formatDateLabel(dateStr: string): string {
  const today = new Date();
  const d = new Date(dateStr + "T00:00:00");
  const diffMs = today.getTime() - d.getTime();
  const diffDays = Math.floor(diffMs / 86400000);
  if (diffDays === 0) return "今天";
  if (diffDays === 1) return "昨天";
  if (diffDays === 2) return "前天";
  const m = d.getMonth() + 1;
  const day = d.getDate();
  return `${m}月${day}日`;
}

export default function Papers() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [ingestOpen, setIngestOpen] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchProgress, setBatchProgress] = useState("");
  const [batchPct, setBatchPct] = useState(0);
  const [viewMode, setViewMode] = useState<"list" | "grid">("list");

  /* 分页 */
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);

  /* 文件夹相关 */
  const [folderStats, setFolderStats] = useState<FolderStats | null>(null);
  const [activeFolder, setActiveFolder] = useState("all");
  const [activeDate, setActiveDate] = useState<string | undefined>();
  const [statsLoading, setStatsLoading] = useState(true);
  const [dateSectionOpen, setDateSectionOpen] = useState(false);

  /* 行动记录 */
  const [actionsList, setActionsList] = useState<CollectionAction[]>([]);
  const [actionSectionOpen, setActionSectionOpen] = useState(false);
  const [activeActionId, setActiveActionId] = useState<string | undefined>();

  /* 搜索防抖 */
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const searchTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  /* 排序 + 状态筛选 */
  const [sortBy, setSortBy] = useState("created_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [statusFilter, setStatusFilter] = useState("");
  const [activeCategory, setActiveCategory] = useState<string | undefined>();
  const [csFeeds, setCsFeeds] = useState<{ category_code: string; category_name: string }[]>([]);

  /* 标签相关 */
  const [tags, setTags] = useState<TagType[]>([]);
  const [activeTagIds, setActiveTagIds] = useState<string[]>([]);
  const [tagSectionOpen, setTagSectionOpen] = useState(false);
  const [tagModalOpen, setTagModalOpen] = useState(false);
  const [editingTag, setEditingTag] = useState<TagType | null>(null);
  const [newTagName, setNewTagName] = useState("");
  const [newTagColor, setNewTagColor] = useState("#3b82f6");
  const [tagsLoading, setTagsLoading] = useState(false);

  useEffect(() => {
    clearTimeout(searchTimerRef.current);
    searchTimerRef.current = setTimeout(() => {
      setDebouncedSearch(searchTerm.trim());
      setPage(1);
    }, 350);
    return () => clearTimeout(searchTimerRef.current);
  }, [searchTerm]);

  /* 加载文件夹统计 + 行动记录 */
  const loadFolderStats = useCallback(async () => {
    setStatsLoading(true);
    try {
      const [stats, actionsRes] = await Promise.all([
        paperApi.folderStats(),
        actionApi.list({ limit: 30 }).catch(() => ({ items: [] as CollectionAction[], total: 0 })),
      ]);
      setFolderStats(stats);
      setActionsList(actionsRes.items);
    } catch {
      toast("error", "加载文件夹统计失败");
    } finally {
      setStatsLoading(false);
    }
  }, [toast]);

  /* 加载论文列表 */
  const loadPapers = useCallback(async () => {
    setLoading(true);
    try {
      // 按行动筛选走独立接口
      if (activeActionId) {
        const res = await actionApi.papers(activeActionId, 200);
        setPapers(res.items.map((p) => ({ ...p, abstract: "", metadata: {} }) as unknown as Paper));
        setTotal(res.items.length);
        setTotalPages(1);
        setSelected(new Set());
        setLoading(false);
        return;
      }

      let folder: string | undefined;
      let topicId: string | undefined;

      if (activeFolder === "all") {
        // 默认
      } else if (
        activeFolder === "favorites" ||
        activeFolder === "recent" ||
        activeFolder === "unclassified"
      ) {
        folder = activeFolder;
      } else if (!activeFolder.startsWith("date:")) {
        topicId = activeFolder;
      }

      const res = await paperApi.latest({
        page,
        pageSize,
        topicId,
        folder,
        date: activeDate,
        search: debouncedSearch || undefined,
        status: statusFilter || undefined,
        sortBy,
        sortOrder,
        category: activeCategory || undefined,
        tagIds: activeTagIds.length > 0 ? activeTagIds : undefined,
      });
      setPapers(res.items);
      setTotal(res.total);
      setTotalPages(res.total_pages);
      setSelected(new Set());
    } catch {
      toast("error", "加载论文列表失败");
    } finally {
      setLoading(false);
    }
  }, [
    activeFolder,
    activeDate,
    activeActionId,
    page,
    pageSize,
    debouncedSearch,
    statusFilter,
    sortBy,
    sortOrder,
    activeCategory,
    activeTagIds,
    toast,
  ]);

  /* 加载标签列表 */
  const loadTags = useCallback(async () => {
    setTagsLoading(true);
    try {
      const res = await tagApi.list();
      setTags(res.items);
    } catch {
      toast("error", "加载标签列表失败");
    } finally {
      setTagsLoading(false);
    }
  }, [toast]);

  /* 创建/更新标签 */
  const handleSaveTag = useCallback(async () => {
    if (!newTagName.trim()) {
      toast("error", "标签名称不能为空");
      return;
    }
    try {
      if (editingTag) {
        await tagApi.update(editingTag.id, {
          name: newTagName.trim(),
          color: newTagColor,
        });
        toast("success", "标签更新成功");
      } else {
        await tagApi.create(newTagName.trim(), newTagColor);
        toast("success", "标签创建成功");
      }
      setTagModalOpen(false);
      setEditingTag(null);
      setNewTagName("");
      setNewTagColor("#3b82f6");
      await loadTags();
    } catch (e: unknown) {
      toast("error", editingTag ? "更新标签失败" : "创建标签失败");
    }
  }, [newTagName, newTagColor, editingTag, loadTags, toast]);

  /* 删除标签 */
  const handleDeleteTag = useCallback(
    async (tag: TagType) => {
      if (!window.confirm(`确定要删除标签 "${tag.name}" 吗？`)) {
        return;
      }
      try {
        await tagApi.delete(tag.id);
        toast("success", `标签 "${tag.name}" 已删除`);
        setActiveTagIds((prev) => prev.filter((id) => id !== tag.id));
        await loadTags();
      } catch {
        toast("error", "删除标签失败");
      }
    },
    [loadTags, toast]
  );

  /* 切换标签筛选 */
  const toggleTagFilter = useCallback(
    (tagId: string) => {
      setActiveTagIds((prev) => {
        const newIds = prev.includes(tagId) ? prev.filter((id) => id !== tagId) : [...prev, tagId];
        return newIds;
      });
      setPage(1);
    },
    []
  );

  useEffect(() => {
    loadFolderStats();
    loadTags();
  }, [loadFolderStats, loadTags]);
  useEffect(() => {
    loadPapers();
  }, [loadPapers]);
  useEffect(() => {
    topicApi
      .csFeeds()
      .then((r) => setCsFeeds(r.feeds || []))
      .catch(() => {});
  }, []);

  /* 构建文件夹列表 */
  const folders = useMemo((): FolderItem[] => {
    if (!folderStats) return [];
    const items: FolderItem[] = [
      {
        id: "all",
        type: "special",
        name: "全部论文",
        icon: <Library className="h-4 w-4" />,
        count: folderStats.total,
        color: "text-ink",
      },
      {
        id: "favorites",
        type: "special",
        name: "收藏",
        icon: <Heart className="h-4 w-4" />,
        count: folderStats.favorites,
        color: "text-red-500",
      },
      {
        id: "recent",
        type: "special",
        name: "最近 7 天",
        icon: <Clock className="h-4 w-4" />,
        count: folderStats.recent_7d,
        color: "text-info",
      },
    ];
    for (const t of folderStats.by_topic) {
      items.push({
        id: t.topic_id,
        type: "topic",
        name: t.topic_name,
        icon: <Folder className="h-4 w-4" />,
        count: t.count,
        color: "text-primary",
      });
    }
    if (folderStats.unclassified > 0) {
      items.push({
        id: "unclassified",
        type: "special",
        name: "未分类",
        icon: <Inbox className="h-4 w-4" />,
        count: folderStats.unclassified,
        color: "text-ink-tertiary",
      });
    }
    return items;
  }, [folderStats]);

  /* 日期条目 */
  const dateEntries = useMemo(() => {
    if (!folderStats?.by_date) return [];
    return folderStats.by_date.map((d) => ({
      dateStr: d.date,
      label: formatDateLabel(d.date),
      count: d.count,
    }));
  }, [folderStats]);

  /* 搜索由后端处理，前端直接使用 papers */
  const filtered = papers;

  const toggleSelect = useCallback((id: string) => {
    setSelected((prev) => {
      const n = new Set(prev);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  }, []);
  const toggleSelectAll = useCallback(() => {
    setSelected((prev) =>
      prev.size === filtered.length ? new Set() : new Set(filtered.map((p) => p.id))
    );
  }, [filtered]);

  const handleToggleFavorite = useCallback(
    async (e: React.MouseEvent, id: string) => {
      e.stopPropagation();
      /* 乐观更新 */
      setPapers((prev) => prev.map((p) => (p.id === id ? { ...p, favorited: !p.favorited } : p)));
      try {
        const res = await paperApi.toggleFavorite(id);
        setPapers((prev) =>
          prev.map((p) => (p.id === res.id ? { ...p, favorited: res.favorited } : p))
        );
        loadFolderStats();
      } catch {
        toast("error", "收藏操作失败");
        setPapers((prev) => prev.map((p) => (p.id === id ? { ...p, favorited: !p.favorited } : p)));
      }
    },
    [loadFolderStats, toast]
  );

  const handleBatchSkim = async () => {
    const ids = [...selected].filter((id) => {
      const p = papers.find((pp) => pp.id === id);
      return p && p.read_status === "unread";
    });
    if (!ids.length) {
      setBatchProgress("没有可粗读的未读论文");
      setBatchPct(0);
      return;
    }
    setBatchRunning(true);
    setBatchPct(0);
    const tid = `batch_skim_${Date.now()}`;
    tasksApi
      .track({
        action: "start",
        task_id: tid,
        task_type: "batch_skim",
        title: `批量粗读 ${ids.length} 篇`,
        total: ids.length,
      })
      .catch(() => {});
    let done = 0,
      failed = 0;
    for (const id of ids) {
      done++;
      setBatchProgress(`粗读中 ${done}/${ids.length}`);
      setBatchPct(Math.round((done / ids.length) * 100));
      tasksApi
        .track({
          action: "update",
          task_id: tid,
          current: done,
          message: `粗读中 ${done}/${ids.length}`,
        })
        .catch(() => {});
      try {
        await pipelineApi.skim(id);
      } catch {
        failed++;
      }
    }
    tasksApi
      .track({
        action: "finish",
        task_id: tid,
        success: failed === 0,
        error: failed > 0 ? `${failed} 篇失败` : undefined,
      })
      .catch(() => {});
    setBatchProgress(failed > 0 ? `完成 ${done - failed} 篇，${failed} 篇失败` : `完成 ${done} 篇`);
    setBatchPct(100);
    if (failed > 0) toast("warning", `${failed} 篇粗读失败`);
    else toast("success", `粗读完成 ${done} 篇`);
    setBatchRunning(false);
    await loadPapers();
  };

  const handleBatchEmbed = async () => {
    const ids = [...selected].filter((id) => {
      const p = papers.find((pp) => pp.id === id);
      return p && !p.has_embedding;
    });
    if (!ids.length) {
      setBatchProgress("已全部嵌入");
      setBatchPct(0);
      return;
    }
    setBatchRunning(true);
    setBatchPct(0);
    const tid = `batch_embed_${Date.now()}`;
    tasksApi
      .track({
        action: "start",
        task_id: tid,
        task_type: "batch_embed",
        title: `批量嵌入 ${ids.length} 篇`,
        total: ids.length,
      })
      .catch(() => {});
    let done = 0,
      failed = 0;
    for (const id of ids) {
      done++;
      setBatchProgress(`嵌入中 ${done}/${ids.length}`);
      setBatchPct(Math.round((done / ids.length) * 100));
      tasksApi
        .track({
          action: "update",
          task_id: tid,
          current: done,
          message: `嵌入中 ${done}/${ids.length}`,
        })
        .catch(() => {});
      try {
        await pipelineApi.embed(id);
      } catch {
        failed++;
      }
    }
    tasksApi
      .track({
        action: "finish",
        task_id: tid,
        success: failed === 0,
        error: failed > 0 ? `${failed} 篇失败` : undefined,
      })
      .catch(() => {});
    setBatchProgress(failed > 0 ? `完成 ${done - failed} 篇，${failed} 篇失败` : `完成 ${done} 篇`);
    setBatchPct(100);
    if (failed > 0) toast("warning", `${failed} 篇嵌入失败`);
    else toast("success", `嵌入完成 ${done} 篇`);
    setBatchRunning(false);
    await loadPapers();
  };

  const handleFolderClick = useCallback((folderId: string) => {
    setActiveFolder(folderId);
    setActiveDate(undefined);
    setActiveActionId(undefined);
    setSearchTerm("");
    setPage(1);
  }, []);

  const handleDateClick = useCallback((dateStr: string) => {
    setActiveFolder("date:" + dateStr);
    setActiveDate(dateStr);
    setActiveActionId(undefined);
    setSearchTerm("");
    setPage(1);
  }, []);

  const activeFolderName = useMemo(() => {
    if (activeDate) return formatDateLabel(activeDate) + " 收录";
    return folders.find((f) => f.id === activeFolder)?.name || "全部论文";
  }, [activeFolder, activeDate, folders]);

  const refresh = useCallback(async () => {
    await Promise.all([loadFolderStats(), loadPapers()]);
  }, [loadFolderStats, loadPapers]);

  /* 分页导航 */
  const goPage = useCallback(
    (p: number) => {
      setPage(Math.max(1, Math.min(p, totalPages)));
    },
    [totalPages]
  );

  return (
    <div className="animate-fade-in flex h-full gap-0">
      {/* ========== 左侧文件夹面板 ========== */}
      <aside className="border-border bg-page/50 hidden w-60 shrink-0 flex-col border-r lg:flex">
        {/* 标题 */}
        <div className="flex items-center justify-between p-4 pb-2">
          <h2 className="text-ink text-sm font-semibold">文件夹</h2>
          <button
            aria-label="刷新"
            onClick={refresh}
            className="text-ink-tertiary hover:bg-hover hover:text-ink rounded-lg p-1 transition-colors"
            title="刷新"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>

        {/* 文件夹列表 */}
        <nav className="flex-1 overflow-y-auto px-2 pb-4">
          {statsLoading ? (
            <div className="flex items-center justify-center py-8">
              <Spinner text="" />
            </div>
          ) : (
            <div className="space-y-0.5">
              {folders.map((folder, idx) => {
                const isActive = activeFolder === folder.id && !activeDate;
                const showDivider =
                  (idx > 0 && folder.type !== folders[idx - 1].type) ||
                  (folder.id === "unclassified" && folders[idx - 1]?.type === "topic");
                return (
                  <div key={folder.id}>
                    {showDivider && <div className="border-border-light my-2 border-t" />}
                    {idx === 3 && folders.some((f) => f.type === "topic") && (
                      <p className="text-ink-tertiary mt-3 mb-1 px-2 text-[10px] font-medium tracking-widest uppercase">
                        订阅主题
                      </p>
                    )}
                    <button
                      onClick={() => handleFolderClick(folder.id)}
                      className={`group flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-sm transition-all ${
                        isActive
                          ? "bg-primary/10 text-primary font-medium"
                          : "text-ink-secondary hover:bg-hover hover:text-ink"
                      }`}
                    >
                      <span className={isActive ? "text-primary" : folder.color}>
                        {isActive && folder.type === "topic" ? (
                          <FolderOpen className="h-4 w-4" />
                        ) : (
                          folder.icon
                        )}
                      </span>
                      <span className="flex-1 truncate">{folder.name}</span>
                      <span
                        className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                          isActive ? "bg-primary/15 text-primary" : "bg-page text-ink-tertiary"
                        }`}
                      >
                        {folder.count}
                      </span>
                    </button>
                  </div>
                );
              })}

              {/* ========== 按日期收录 ========== */}
              {dateEntries.length > 0 && (
                <>
                  <div className="border-border-light my-2 border-t" />
                  <button
                    onClick={() => setDateSectionOpen(!dateSectionOpen)}
                    className="flex w-full items-center gap-2 px-2 py-1.5 text-left"
                  >
                    <Calendar className="text-ink-tertiary h-3.5 w-3.5" />
                    <span className="text-ink-tertiary flex-1 text-[10px] font-medium tracking-widest uppercase">
                      按收录日期
                    </span>
                    <ChevronRight
                      className={`text-ink-tertiary h-3 w-3 transition-transform ${dateSectionOpen ? "rotate-90" : ""}`}
                    />
                  </button>
                  {dateSectionOpen && (
                    <div className="space-y-0.5 pl-1">
                      {dateEntries.map((entry) => {
                        const isActive = activeDate === entry.dateStr;
                        return (
                          <button
                            key={entry.dateStr}
                            onClick={() => handleDateClick(entry.dateStr)}
                            className={`group flex w-full items-center gap-2.5 rounded-xl px-3 py-1.5 text-left text-[13px] transition-all ${
                              isActive
                                ? "bg-primary/10 text-primary font-medium"
                                : "text-ink-secondary hover:bg-hover hover:text-ink"
                            }`}
                          >
                            <span
                              className={`text-[11px] ${isActive ? "text-primary" : "text-ink-tertiary"}`}
                            >
                              {entry.dateStr.slice(5)}
                            </span>
                            <span className="flex-1 truncate">{entry.label}</span>
                            <span
                              className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                                isActive
                                  ? "bg-primary/15 text-primary"
                                  : "bg-page text-ink-tertiary"
                              }`}
                            >
                              {entry.count}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </>
              )}

              {/* ========== 行动记录 ========== */}
              {actionsList.length > 0 && (
                <>
                  <div className="border-border-light my-2 border-t" />
                  <button
                    onClick={() => setActionSectionOpen(!actionSectionOpen)}
                    className="flex w-full items-center gap-2 px-2 py-1.5 text-left"
                  >
                    <Download className="text-ink-tertiary h-3.5 w-3.5" />
                    <span className="text-ink-tertiary flex-1 text-[10px] font-medium tracking-widest uppercase">
                      收集记录
                    </span>
                    <ChevronRight
                      className={`text-ink-tertiary h-3 w-3 transition-transform ${actionSectionOpen ? "rotate-90" : ""}`}
                    />
                  </button>
                  {actionSectionOpen && (
                    <div className="space-y-0.5 pl-1">
                      {actionsList.map((action) => {
                        const isActive = activeActionId === action.id;
                        return (
                          <button
                            key={action.id}
                            onClick={() => {
                              setActiveActionId(isActive ? undefined : action.id);
                              if (!isActive) {
                                setActiveFolder("all");
                                setActiveDate(undefined);
                              }
                              setPage(1);
                            }}
                            className={`group flex w-full items-center gap-2 rounded-xl px-3 py-1.5 text-left text-[13px] transition-all ${
                              isActive
                                ? "bg-primary/10 text-primary font-medium"
                                : "text-ink-secondary hover:bg-hover hover:text-ink"
                            }`}
                          >
                            <ActionBadge type={action.action_type} />
                            <span className="min-w-0 flex-1 truncate">{action.title}</span>
                            <span
                              className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${
                                isActive
                                  ? "bg-primary/15 text-primary"
                                  : "bg-page text-ink-tertiary"
                              }`}
                            >
                              {action.paper_count}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </>
              )}

              {/* ========== 标签筛选 ========== */}
              <div className="border-border-light my-2 border-t" />
              <div className="flex items-center justify-between px-2 py-1.5">
                <button
                  onClick={() => setTagSectionOpen(!tagSectionOpen)}
                  className="flex flex-1 items-center gap-2 text-left"
                >
                  <Tag className="text-ink-tertiary h-3.5 w-3.5" />
                  <span className="text-ink-tertiary flex-1 text-[10px] font-medium tracking-widest uppercase">
                    标签筛选
                  </span>
                  <ChevronRight
                    className={`text-ink-tertiary h-3 w-3 transition-transform ${tagSectionOpen ? "rotate-90" : ""}`}
                  />
                </button>
                <button
                  onClick={() => {
                    setEditingTag(null);
                    setNewTagName("");
                    setNewTagColor("#3b82f6");
                    setTagModalOpen(true);
                  }}
                  className="text-ink-tertiary hover:bg-hover hover:text-ink rounded-lg p-1 transition-colors"
                  title="新建标签"
                >
                  <Plus className="h-3.5 w-3.5" />
                </button>
              </div>
              {tagSectionOpen && (
                <div className="space-y-1 px-2 pb-2">
                  {tagsLoading ? (
                    <div className="flex items-center justify-center py-4">
                      <Spinner text="" />
                    </div>
                  ) : tags.length === 0 ? (
                    <p className="text-ink-tertiary px-2 py-3 text-center text-[11px]">
                      暂无标签，点击 + 创建
                    </p>
                  ) : (
                    <div className="flex flex-wrap gap-1.5">
                      {tags.map((tag) => {
                        const isActive = activeTagIds.includes(tag.id);
                        return (
                          <div key={tag.id} className="group relative">
                            <button
                              onClick={() => toggleTagFilter(tag.id)}
                              className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] transition-all ${
                                isActive
                                  ? "ring-2 ring-offset-1"
                                  : "hover:opacity-80"
                              }`}
                              style={{
                                backgroundColor: isActive ? tag.color : `${tag.color}20`,
                                color: isActive ? "white" : tag.color,
                                boxShadow: isActive ? `0 0 0 2px ${tag.color}` : "none",
                              }}
                            >
                              <span className="max-w-24 truncate">{tag.name}</span>
                              <span
                                className={`text-[10px] ${
                                  isActive ? "text-white/80" : "opacity-70"
                                }`}
                              >
                                ({tag.paper_count || 0})
                              </span>
                            </button>
                            <div className="absolute -right-1 -top-1 hidden gap-0.5 rounded-full bg-white shadow-sm group-hover:flex">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setEditingTag(tag);
                                  setNewTagName(tag.name);
                                  setNewTagColor(tag.color);
                                  setTagModalOpen(true);
                                }}
                                className="text-ink-tertiary hover:text-primary rounded-full p-0.5"
                                title="编辑标签"
                              >
                                <Edit2 className="h-2.5 w-2.5" />
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleDeleteTag(tag);
                                }}
                                className="text-ink-tertiary hover:text-error rounded-full p-0.5"
                                title="删除标签"
                              >
                                <Trash2 className="h-2.5 w-2.5" />
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                  {activeTagIds.length > 0 && (
                    <button
                      onClick={() => {
                        setActiveTagIds([]);
                        setPage(1);
                      }}
                      className="text-ink-tertiary hover:text-ink mt-1 w-full text-center text-[10px]"
                    >
                      清除筛选 ({activeTagIds.length})
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
        </nav>

        {/* 底部按钮 */}
        <div className="border-border border-t p-3">
          <Button
            size="sm"
            icon={<Download className="h-3.5 w-3.5" />}
            onClick={() => setIngestOpen(true)}
            className="w-full"
          >
            ArXiv 摄入
          </Button>
        </div>
      </aside>

      {/* ========== 右侧论文列表 ========== */}
      <main className="flex flex-1 flex-col overflow-hidden">
        {/* 头部 */}
        <div className="border-border flex items-center justify-between border-b px-5 py-4">
          <div className="flex items-center gap-3">
            <h1 className="text-ink text-lg font-bold">{activeFolderName}</h1>
            <span className="bg-page text-ink-secondary rounded-full px-2.5 py-0.5 text-xs font-medium">
              {total} 篇
            </span>
          </div>
          <div className="flex items-center gap-2">
            {/* 视图切换 */}
            <div className="border-border bg-surface flex rounded-lg border p-0.5">
              <button
                aria-label="列表视图"
                onClick={() => setViewMode("list")}
                className={`rounded-md p-1.5 transition-colors ${viewMode === "list" ? "bg-primary/10 text-primary" : "text-ink-tertiary hover:text-ink"}`}
              >
                <LayoutList className="h-3.5 w-3.5" />
              </button>
              <button
                aria-label="网格视图"
                onClick={() => setViewMode("grid")}
                className={`rounded-md p-1.5 transition-colors ${viewMode === "grid" ? "bg-primary/10 text-primary" : "text-ink-tertiary hover:text-ink"}`}
              >
                <LayoutGrid className="h-3.5 w-3.5" />
              </button>
            </div>
            <Button
              variant="secondary"
              size="sm"
              icon={<RefreshCw className="h-3.5 w-3.5" />}
              onClick={refresh}
            >
              刷新
            </Button>
            <Button
              size="sm"
              icon={<Download className="h-3.5 w-3.5" />}
              onClick={() => setIngestOpen(true)}
              className="lg:hidden"
            >
              摄入
            </Button>
          </div>
        </div>

        {/* 搜索 + 排序筛选 */}
        <div className="border-border-light flex flex-wrap items-center gap-2 border-b px-5 py-3">
          <div className="relative max-w-sm flex-1">
            <Search className="text-ink-tertiary absolute top-1/2 left-3 h-3.5 w-3.5 -translate-y-1/2" />
            <input
              type="text"
              placeholder="搜索标题、关键词、arxiv ID..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="border-border bg-surface text-ink placeholder:text-ink-placeholder focus:border-primary focus:ring-primary/20 h-8 w-full rounded-lg border pr-3 pl-8 text-xs focus:ring-2 focus:outline-none"
            />
          </div>

          {/* 排序筛选控件 */}
          {selected.size === 0 && (
            <div className="flex shrink-0 items-center gap-1.5">
              {/* 状态筛选 */}
              <div className="border-border bg-surface flex items-center rounded-lg border p-0.5">
                {(
                  [
                    { value: "", label: "全部" },
                    { value: "unread", label: "未读" },
                    { value: "skimmed", label: "已粗读" },
                    { value: "deep_read", label: "已精读" },
                  ] as { value: string; label: string }[]
                ).map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => {
                      setStatusFilter(opt.value);
                      setPage(1);
                    }}
                    className={`rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${statusFilter === opt.value ? "bg-primary/10 text-primary" : "text-ink-tertiary hover:text-ink"}`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>

              {/* 分隔线 */}
              <div className="bg-border-light h-4 w-px" />

              {/* CS 分类筛选 */}
              {csFeeds.length > 0 && (
                <select
                  value={activeCategory || ""}
                  onChange={(e) => {
                    setActiveCategory(e.target.value || undefined);
                    setPage(1);
                  }}
                  className="border-border bg-surface text-ink-secondary focus:border-primary h-7 cursor-pointer rounded-lg border px-2 text-[11px] focus:outline-none"
                >
                  <option value="">全部分类</option>
                  {csFeeds.map((f) => (
                    <option key={f.category_code} value={f.category_code}>
                      {f.category_code}
                    </option>
                  ))}
                </select>
              )}

              {/* 排序字段 */}
              <select
                value={sortBy}
                onChange={(e) => {
                  setSortBy(e.target.value);
                  setPage(1);
                }}
                className="border-border bg-surface text-ink-secondary focus:border-primary h-7 cursor-pointer rounded-lg border px-2 text-[11px] focus:outline-none"
              >
                <option value="created_at">入库时间</option>
                <option value="publication_date">发表时间</option>
                <option value="title">标题</option>
              </select>

              {/* 排序方向 */}
              <button
                onClick={() => {
                  setSortOrder((o) => (o === "desc" ? "asc" : "desc"));
                  setPage(1);
                }}
                className="border-border bg-surface text-ink-tertiary hover:bg-hover hover:text-ink flex h-7 items-center rounded-lg border px-2 transition-colors"
                title={
                  sortOrder === "desc" ? "当前：倒序，点击切换升序" : "当前：升序，点击切换倒序"
                }
              >
                {sortOrder === "desc" ? (
                  <ArrowDown className="h-3.5 w-3.5" />
                ) : (
                  <ArrowUp className="h-3.5 w-3.5" />
                )}
              </button>
            </div>
          )}

          {/* 批量操作 */}
          {selected.size > 0 && (
            <div className="border-primary/20 bg-primary/5 flex items-center gap-2 rounded-lg border px-3 py-1.5">
              <span className="text-primary text-xs font-medium">已选 {selected.size}</span>
              <Button
                size="sm"
                variant="secondary"
                onClick={handleBatchSkim}
                disabled={batchRunning}
                icon={<Zap className="h-3 w-3" />}
              >
                粗读
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={handleBatchEmbed}
                disabled={batchRunning}
                icon={<Cpu className="h-3 w-3" />}
              >
                嵌入
              </Button>
              <button
                onClick={() => setSelected(new Set())}
                className="text-ink-tertiary hover:text-ink text-[10px]"
              >
                取消
              </button>
              {batchProgress && (
                <div className="flex items-center gap-2">
                  {batchRunning && (
                    <div className="bg-border h-1.5 w-24 overflow-hidden rounded-full">
                      <div
                        className="bg-primary h-full rounded-full transition-all duration-300"
                        style={{ width: `${batchPct}%` }}
                      />
                    </div>
                  )}
                  <span className="text-ink-secondary text-[10px]">{batchProgress}</span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* 论文列表 */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="p-4">
              <PaperListSkeleton />
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex items-center justify-center py-16">
              <Empty
                icon={<FileText className="h-14 w-14" />}
                title={searchTerm ? "没有匹配的论文" : "该文件夹暂无论文"}
                description={searchTerm ? "尝试不同的关键词" : "从 ArXiv 摄入论文开始你的研究之旅"}
                action={
                  !searchTerm ? (
                    <Button size="sm" onClick={() => setIngestOpen(true)}>
                      开始摄入
                    </Button>
                  ) : undefined
                }
              />
            </div>
          ) : (
            <div className="p-4">
              {/* 全选 */}
              <div className="mb-2 flex items-center gap-2 px-1">
                <input
                  type="checkbox"
                  checked={selected.size === filtered.length && filtered.length > 0}
                  onChange={toggleSelectAll}
                  className="border-border text-primary focus:ring-primary/30 h-3.5 w-3.5 rounded"
                />
                <span className="text-ink-tertiary text-[11px]">
                  全选 / 第 {page} 页，共 {total} 篇
                </span>
              </div>

              {viewMode === "list" ? (
                <div className="space-y-1.5">
                  {filtered.map((paper) => (
                    <PaperListItem
                      key={paper.id}
                      paper={paper}
                      selected={selected.has(paper.id)}
                      onSelect={() => toggleSelect(paper.id)}
                      onFavorite={(e) => handleToggleFavorite(e, paper.id)}
                      onClick={() => navigate(`/papers/${paper.id}`)}
                    />
                  ))}
                </div>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  {filtered.map((paper) => (
                    <PaperGridItem
                      key={paper.id}
                      paper={paper}
                      onFavorite={(e) => handleToggleFavorite(e, paper.id)}
                      onClick={() => navigate(`/papers/${paper.id}`)}
                    />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* ========== 分页 ========== */}
        {totalPages > 1 && (
          <div className="border-border flex items-center justify-between border-t px-5 py-3">
            <span className="text-ink-tertiary text-xs">
              共 {total} 篇，第 {page}/{totalPages} 页
            </span>
            <div className="flex items-center gap-1">
              <button
                aria-label="首页"
                onClick={() => goPage(1)}
                disabled={page <= 1}
                className="text-ink-secondary hover:bg-hover rounded-lg p-1.5 transition-colors disabled:opacity-30"
                title="首页"
              >
                <ChevronsLeft className="h-4 w-4" />
              </button>
              <button
                aria-label="上一页"
                onClick={() => goPage(page - 1)}
                disabled={page <= 1}
                className="text-ink-secondary hover:bg-hover rounded-lg p-1.5 transition-colors disabled:opacity-30"
                title="上一页"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>

              {/* 页码按钮 */}
              {(() => {
                const items: (number | "dots")[] = [];
                const start = Math.max(1, page - 2);
                const end = Math.min(totalPages, page + 2);

                if (start > 1) items.push(1);
                if (start > 2) items.push("dots");
                for (let i = start; i <= end; i++) items.push(i);
                if (end < totalPages - 1) items.push("dots");
                if (end < totalPages) items.push(totalPages);

                return items.map((item, idx) => {
                  if (item === "dots") {
                    return (
                      <span key={`dots-${idx}`} className="text-ink-tertiary px-1 text-xs">
                        ...
                      </span>
                    );
                  }
                  return (
                    <button
                      key={item}
                      onClick={() => goPage(item)}
                      className={`min-w-[2rem] rounded-lg px-2 py-1.5 text-xs font-medium transition-colors ${
                        item === page
                          ? "bg-primary text-white"
                          : "text-ink-secondary hover:bg-hover"
                      }`}
                    >
                      {item}
                    </button>
                  );
                });
              })()}

              <button
                aria-label="下一页"
                onClick={() => goPage(page + 1)}
                disabled={page >= totalPages}
                className="text-ink-secondary hover:bg-hover rounded-lg p-1.5 transition-colors disabled:opacity-30"
                title="下一页"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
              <button
                aria-label="末页"
                onClick={() => goPage(totalPages)}
                disabled={page >= totalPages}
                className="text-ink-secondary hover:bg-hover rounded-lg p-1.5 transition-colors disabled:opacity-30"
                title="末页"
              >
                <ChevronsRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}
      </main>

      <IngestModal
        open={ingestOpen}
        onClose={() => setIngestOpen(false)}
        onDone={() => {
          loadPapers();
          loadFolderStats();
        }}
      />

      <TagModal
        open={tagModalOpen}
        onClose={() => {
          setTagModalOpen(false);
          setEditingTag(null);
          setNewTagName("");
          setNewTagColor("#3b82f6");
        }}
        editingTag={editingTag}
        tagName={newTagName}
        tagColor={newTagColor}
        onNameChange={setNewTagName}
        onColorChange={setNewTagColor}
        onSave={handleSaveTag}
      />
    </div>
  );
}

/* ========== 论文卡片：列表模式 ========== */
const PaperListItem = memo(function PaperListItem({
  paper,
  selected,
  onSelect,
  onFavorite,
  onClick,
}: {
  paper: Paper;
  selected: boolean;
  onSelect: () => void;
  onFavorite: (e: React.MouseEvent) => void;
  onClick: () => void;
}) {
  const sc = statusBadge[paper.read_status] || statusBadge.unread;
  return (
    <div
      className={`group bg-surface rounded-xl border transition-all hover:shadow-sm ${
        selected ? "border-primary/30 ring-primary/10 ring-1" : "border-border/60"
      }`}
    >
      <div className="flex items-start gap-3 px-3.5 py-3">
        <input
          type="checkbox"
          checked={selected}
          onChange={onSelect}
          onClick={(e) => e.stopPropagation()}
          className="border-border text-primary focus:ring-primary/30 mt-1 h-3.5 w-3.5 shrink-0 rounded"
        />
        <button className="flex min-w-0 flex-1 items-start gap-2.5 text-left" onClick={onClick}>
          {/* 状态图标 */}
          <div
            className={`mt-0.5 shrink-0 rounded-lg p-1.5 ${
              paper.read_status === "deep_read"
                ? "bg-success-light"
                : paper.read_status === "skimmed"
                  ? "bg-warning-light"
                  : "bg-page"
            }`}
          >
            {paper.read_status === "deep_read" ? (
              <BookMarked className="text-success h-3.5 w-3.5" />
            ) : paper.read_status === "skimmed" ? (
              <Eye className="text-warning h-3.5 w-3.5" />
            ) : (
              <BookOpen className="text-ink-tertiary h-3.5 w-3.5" />
            )}
          </div>
          {/* 内容 */}
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex items-start gap-2">
              <h3 className="text-ink group-hover:text-primary text-[13px] leading-snug font-semibold transition-colors">
                {paper.title}
              </h3>
              <Badge variant={sc.variant} className="shrink-0">
                {sc.label}
              </Badge>
              {paper.has_embedding && (
                <span className="bg-info-light text-info inline-flex shrink-0 items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[9px] font-medium">
                  <CheckCircle2 className="h-2.5 w-2.5" /> 嵌入
                </span>
              )}
            </div>
            {paper.title_zh && <p className="text-ink-tertiary text-[11px]">{paper.title_zh}</p>}
            {paper.abstract && (
              <p className="text-ink-secondary text-[11px] leading-relaxed">
                {truncate(paper.abstract, 140)}
              </p>
            )}
            {/* 标签行 */}
            <div className="flex flex-wrap items-center gap-1">
              {paper.topics?.map((t) => (
                <span
                  key={t}
                  className="bg-primary/8 text-primary inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[9px] font-medium"
                >
                  <Tag className="h-2 w-2" />
                  {t}
                </span>
              ))}
              {paper.tags?.map((tag) => (
                <span
                  key={tag.id}
                  className="inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[9px] font-medium"
                  style={{
                    backgroundColor: `${tag.color}20`,
                    color: tag.color,
                  }}
                >
                  <Tag className="h-2 w-2" />
                  {tag.name}
                </span>
              ))}
              {paper.keywords?.slice(0, 3).map((kw) => (
                <span
                  key={kw}
                  className="bg-page text-ink-tertiary rounded-md px-1.5 py-0.5 text-[9px]"
                >
                  {kw}
                </span>
              ))}
            </div>
            {/* 元信息 */}
            <div className="text-ink-tertiary flex items-center gap-3 text-[10px]">
              {paper.arxiv_id && (
                <span className="flex items-center gap-0.5">
                  <ExternalLink className="h-2.5 w-2.5" />
                  {paper.arxiv_id}
                </span>
              )}
              {paper.publication_date && <span>{formatDate(paper.publication_date)}</span>}
            </div>
          </div>
          <ChevronRight className="text-ink-tertiary mt-2 h-3.5 w-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
        </button>
        <button
          aria-label={paper.favorited ? "取消收藏" : "收藏"}
          onClick={onFavorite}
          className="hover:bg-error/10 mt-0.5 shrink-0 rounded-lg p-1 transition-colors"
        >
          <Heart
            className={`h-3.5 w-3.5 ${paper.favorited ? "fill-red-500 text-red-500" : "text-ink-tertiary"}`}
          />
        </button>
      </div>
    </div>
  );
});

/* ========== 论文卡片：网格模式 ========== */
const PaperGridItem = memo(function PaperGridItem({
  paper,
  onFavorite,
  onClick,
}: {
  paper: Paper;
  onFavorite: (e: React.MouseEvent) => void;
  onClick: () => void;
}) {
  const sc = statusBadge[paper.read_status] || statusBadge.unread;
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => e.key === "Enter" && onClick()}
      className="group border-border/60 bg-surface flex cursor-pointer flex-col rounded-xl border p-3.5 text-left transition-all hover:shadow-sm"
    >
      <div className="mb-2 flex items-center justify-between">
        <Badge variant={sc.variant}>{sc.label}</Badge>
        <button
          aria-label={paper.favorited ? "取消收藏" : "收藏"}
          onClick={onFavorite}
          className="hover:bg-error/10 rounded-lg p-1 transition-colors"
        >
          <Heart
            className={`h-3.5 w-3.5 ${paper.favorited ? "fill-red-500 text-red-500" : "text-ink-tertiary"}`}
          />
        </button>
      </div>
      <h3 className="text-ink group-hover:text-primary line-clamp-2 text-[13px] leading-snug font-semibold transition-colors">
        {paper.title}
      </h3>
      {paper.title_zh && (
        <p className="text-ink-tertiary mt-0.5 line-clamp-1 text-[11px]">{paper.title_zh}</p>
      )}
      {paper.abstract && (
        <p className="text-ink-secondary mt-1.5 line-clamp-3 text-[11px] leading-relaxed">
          {truncate(paper.abstract, 100)}
        </p>
      )}
      <div className="mt-auto pt-2.5">
        <div className="flex flex-wrap gap-1">
          {paper.topics?.slice(0, 2).map((t) => (
            <span
              key={t}
              className="bg-primary/8 text-primary inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[9px] font-medium"
            >
              <Tag className="h-2 w-2" />
              {t}
            </span>
          ))}
        </div>
        <div className="text-ink-tertiary mt-1.5 flex items-center justify-between text-[10px]">
          <span>{paper.arxiv_id}</span>
          <span>{paper.publication_date && formatDate(paper.publication_date)}</span>
        </div>
      </div>
    </div>
  );
});

/* ========== 摄入弹窗 ========== */
function IngestModal({
  open,
  onClose,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const [query, setQuery] = useState("");
  const [maxResults, setMaxResults] = useState(20);
  const [topicId, setTopicId] = useState("");
  const [topics, setTopics] = useState<Topic[]>([]);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<number | null>(null);

  const { toast } = useToast();
  useEffect(() => {
    if (open) {
      topicApi
        .list()
        .then((r) => setTopics(r.items))
        .catch(() => {
          toast("error", "加载主题列表失败");
        });
      setResult(null);
    }
  }, [open, toast]);

  const handleIngest = async () => {
    if (!query.trim()) return;
    setLoading(true);
    try {
      const res = await ingestApi.arxiv(query, maxResults, topicId || undefined);
      setResult(res.ingested);
      onDone();
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="ArXiv 论文摄入">
      <div className="space-y-4">
        <Input
          label="搜索查询"
          placeholder="例如: transformer attention mechanism"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="grid grid-cols-2 gap-4">
          <Input
            label="最大数量"
            type="number"
            value={maxResults}
            onChange={(e) => setMaxResults(parseInt(e.target.value) || 20)}
          />
          <div className="space-y-1.5">
            <label className="text-ink block text-sm font-medium">关联主题</label>
            <select
              value={topicId}
              onChange={(e) => setTopicId(e.target.value)}
              className="border-border bg-surface text-ink focus:border-primary h-10 w-full rounded-lg border px-3 text-sm focus:outline-none"
            >
              <option value="">不关联</option>
              {topics.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        {result !== null && (
          <div className="bg-success-light text-success rounded-xl p-3 text-sm font-medium">
            <CheckCircle2 className="mr-2 inline h-4 w-4" />
            成功摄入 {result} 篇论文
          </div>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={onClose}>
            关闭
          </Button>
          <Button onClick={handleIngest} loading={loading}>
            开始摄入
          </Button>
        </div>
      </div>
    </Modal>
  );
}

/* ========== 标签管理弹窗 ========== */
function TagModal({
  open,
  onClose,
  editingTag,
  tagName,
  tagColor,
  onNameChange,
  onColorChange,
  onSave,
}: {
  open: boolean;
  onClose: () => void;
  editingTag: TagType | null;
  tagName: string;
  tagColor: string;
  onNameChange: (name: string) => void;
  onColorChange: (color: string) => void;
  onSave: () => void;
}) {
  const presetColors = [
    "#3b82f6",
    "#10b981",
    "#f59e0b",
    "#ef4444",
    "#8b5cf6",
    "#ec4899",
    "#06b6d4",
    "#84cc16",
  ];

  return (
    <Modal open={open} onClose={onClose} title={editingTag ? "编辑标签" : "新建标签"}>
      <div className="space-y-4">
        <Input
          label="标签名称"
          placeholder="输入标签名称"
          value={tagName}
          onChange={(e) => onNameChange(e.target.value)}
        />
        <div className="space-y-2">
          <label className="text-ink block text-sm font-medium">标签颜色</label>
          <div className="flex flex-wrap gap-2">
            {presetColors.map((color) => (
              <button
                key={color}
                onClick={() => onColorChange(color)}
                className={`h-8 w-8 rounded-full transition-transform ${
                  tagColor === color ? "ring-2 ring-offset-2" : "hover:scale-110"
                }`}
                style={{
                  backgroundColor: color,
                  boxShadow: tagColor === color ? `0 0 0 2px ${color}` : "none",
                }}
              />
            ))}
            <div className="flex items-center gap-2">
              <input
                type="color"
                value={tagColor}
                onChange={(e) => onColorChange(e.target.value)}
                className="h-8 w-8 cursor-pointer rounded border-0"
              />
              <span className="text-ink-tertiary text-[11px]">{tagColor}</span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 pt-2">
          <span className="text-ink-tertiary text-sm">预览：</span>
          <span
            className="inline-flex items-center rounded-md px-3 py-1 text-sm font-medium"
            style={{
              backgroundColor: `${tagColor}20`,
              color: tagColor,
            }}
          >
            {tagName || "标签名称"}
          </span>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button onClick={onSave}>{editingTag ? "保存" : "创建"}</Button>
        </div>
      </div>
    </Modal>
  );
}

function ActionBadge({ type }: { type: string }) {
  const cls = "h-3 w-3 shrink-0";
  switch (type) {
    case "agent_collect":
      return <Bot className={`${cls} text-info`} />;
    case "auto_collect":
      return <CalendarClock className={`${cls} text-success`} />;
    case "manual_collect":
      return <Download className={`${cls} text-primary`} />;
    case "subscription_ingest":
      return <Tag className={`${cls} text-warning`} />;
    default:
      return <FileText className={`${cls} text-ink-tertiary`} />;
  }
}
