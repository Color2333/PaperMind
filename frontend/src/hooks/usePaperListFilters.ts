import { useEffect, useRef, useState } from "react";

/**
 * usePaperListFilters — 论文列表筛选/排序/分页状态
 *
 * 集中管理 Papers 页面的筛选相关状态：搜索词（带 350ms 防抖）、
 * 文件夹、收录日期、排序、状态筛选、标签筛选与分页。
 * 数据拉取（papers 列表、总数）与 UI 状态（弹窗、选中）仍由调用方持有。
 */
export function usePaperListFilters() {
  const [searchTerm, setSearchTerm] = useState("");

  /* 搜索防抖 */
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const searchTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  /* 分页 */
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);

  /* 文件夹相关 */
  const [activeFolder, setActiveFolder] = useState("all");
  const [activeDate, setActiveDate] = useState<string | undefined>();

  /* 排序 + 状态筛选 */
  const [sortBy, setSortBy] = useState("created_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [statusFilter, setStatusFilter] = useState("");

  /* 标签筛选 */
  const [activeTagIds, setActiveTagIds] = useState<string[]>([]);

  useEffect(() => {
    clearTimeout(searchTimerRef.current);
    searchTimerRef.current = setTimeout(() => {
      setDebouncedSearch(searchTerm.trim());
      setPage(1);
    }, 350);
    return () => clearTimeout(searchTimerRef.current);
  }, [searchTerm]);

  return {
    searchTerm,
    setSearchTerm,
    debouncedSearch,
    page,
    setPage,
    pageSize,
    activeFolder,
    setActiveFolder,
    activeDate,
    setActiveDate,
    sortBy,
    setSortBy,
    sortOrder,
    setSortOrder,
    statusFilter,
    setStatusFilter,
    activeTagIds,
    setActiveTagIds,
  };
}
