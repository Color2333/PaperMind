/**
 * 引文分析面板 — 单篇引用详情 / 主题网络 / 深度溯源
 * @author Bamzc
 */
import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { Link } from "react-router-dom";
import { Button, Badge } from "@/components/ui";
import { useToast } from "@/contexts/ToastContext";
import {
  graphApi, paperApi, topicApi, actionApi, ingestApi,
  type CollectionAction, type ImportTaskStatus, type ReferenceImportEntry,
} from "@/services/api";
import ForceGraph2D from "react-force-graph-2d";
import {
  Search, Network, FileText, Rss, Clock, Loader2,
  ArrowDown, ArrowUp, ChevronDown, ChevronRight, Star,
  Share2, List, RotateCw, ExternalLink, Layers, Bot,
  Download, CalendarClock, PackagePlus, CheckCircle2,
  XCircle, SkipForward, X,
} from "lucide-react";
import type {
  Paper, Topic, CitationTree, CitationDetail, RichCitationEntry,
  TopicCitationNetwork, NetworkNode,
} from "@/types";
import { Section, PaperLink } from "./shared";

const ACTION_TYPE_LABEL: Record<string, string> = {
  initial_import: "初始导入",
  manual_collect: "手动收集",
  auto_collect: "自动收集",
  agent_collect: "Agent 收集",
  subscription_ingest: "订阅入库",
  reference_import: "参考文献导入",
};

function ActionIcon({ type }: { type: string }) {
  const cls = "h-3.5 w-3.5 shrink-0";
  switch (type) {
    case "agent_collect": return <Bot className={`${cls} text-info`} />;
    case "auto_collect": return <CalendarClock className={`${cls} text-success`} />;
    case "manual_collect": return <Download className={`${cls} text-primary`} />;
    case "subscription_ingest": return <Rss className={`${cls} text-warning`} />;
    default: return <FileText className={`${cls} text-ink-tertiary`} />;
  }
}

type PickerMode = "search" | "topic" | "action";
type ViewMode = "list" | "graph";
type AnalysisMode = "paper" | "topic";

export default function CitationPanel() {
  const { toast } = useToast();

  /* 选取器 state */
  const [pickerMode, setPickerMode] = useState<PickerMode>("search");
  const [paperSearch, setPaperSearch] = useState("");
  const [paperResults, setPaperResults] = useState<Paper[]>([]);
  const [paperSearching, setPaperSearching] = useState(false);
  const [showPaperDropdown, setShowPaperDropdown] = useState(false);
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null);
  const [paperId, setPaperId] = useState("");
  const paperDropdownRef = useRef<HTMLDivElement>(null);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const [topics, setTopics] = useState<Topic[]>([]);
  const [actions, setActions] = useState<CollectionAction[]>([]);
  const [pickLoading, setPickLoading] = useState(false);

  /* 数据 */
  const [detailData, setDetailData] = useState<CitationDetail | null>(null);
  const [treeData, setTreeData] = useState<CitationTree | null>(null);
  const [topicNetData, setTopicNetData] = useState<TopicCitationNetwork | null>(null);

  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [analysisMode, setAnalysisMode] = useState<AnalysisMode>("paper");
  const [loading, setLoading] = useState(false);
  const [deepTracing, setDeepTracing] = useState(false);

  /* 初始化：拉主题 / 行动 / 最近论文 */
  useEffect(() => {
    (async () => {
      const [topicRes, recentPapers, actionsRes] = await Promise.all([
        topicApi.list(true).catch(() => ({ items: [] as Topic[] })),
        paperApi.latest({ pageSize: 10 }).catch(() => ({ items: [] as Paper[] })),
        actionApi.list({ limit: 30 }).catch(() => ({ items: [] as CollectionAction[], total: 0 })),
      ]);
      setTopics(topicRes.items);
      if (recentPapers.items.length > 0) setPaperResults(recentPapers.items);
      setActions(actionsRes.items);
    })();
  }, []);

  /* 点击外部关闭下拉 */
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (paperDropdownRef.current && !paperDropdownRef.current.contains(e.target as Node)) {
        setShowPaperDropdown(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  /* 论文搜索（防抖） */
  const handlePaperSearch = useCallback((q: string) => {
    setPaperSearch(q);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    if (!q.trim()) { setPaperResults([]); setShowPaperDropdown(false); return; }
    searchTimerRef.current = setTimeout(async () => {
      setPaperSearching(true);
      try {
        const res = await paperApi.latest({ search: q.trim(), pageSize: 10 });
        setPaperResults(res.items);
        setShowPaperDropdown(true);
      } catch { /* ignore */ }
      finally { setPaperSearching(false); }
    }, 300);
  }, []);

  const handleSelectPaper = useCallback((paper: Paper) => {
    setSelectedPaper(paper);
    setPaperId(paper.id);
    setPaperSearch(paper.title);
    setShowPaperDropdown(false);
  }, []);

  /* 按行动加载论文 */
  const handleSelectAction = useCallback(async (action: CollectionAction) => {
    setPickLoading(true);
    try {
      const res = await actionApi.papers(action.id, 200);
      if (res.items.length > 0) {
        const first = res.items[0];
        setPaperId(first.id);
        setSelectedPaper({ id: first.id, title: first.title, arxiv_id: first.arxiv_id } as Paper);
        setPaperSearch(first.title);
        setPaperResults(res.items.map((p) => ({ id: p.id, title: p.title, arxiv_id: p.arxiv_id } as Paper)));
        setShowPaperDropdown(true);
        toast("success", `已加载「${action.title}」中的 ${res.items.length} 篇论文`);
      } else {
        toast("warning", "该行动没有关联论文");
      }
    } catch { toast("error", "加载行动论文失败"); }
    finally { setPickLoading(false); }
  }, [toast]);

  /* 按主题加载网络 */
  const handleSelectTopic = useCallback(async (topic: Topic) => {
    setPickLoading(true);
    setAnalysisMode("topic");
    try {
      const network = await graphApi.topicNetwork(topic.id);
      setTopicNetData(network);
      setDetailData(null);
      setTreeData(null);
      setViewMode("graph");
      toast("success", `已加载主题「${topic.name}」的引用网络（${network.nodes.length} 篇、${network.edges.length} 条引用）`);
    } catch { toast("error", "加载主题引用网络失败"); }
    finally { setPickLoading(false); }
  }, [toast]);

  /* 查询单篇引用 */
  const handleQuery = useCallback(async () => {
    if (!paperId.trim()) return;
    setLoading(true);
    setAnalysisMode("paper");
    try {
      const [detail, tree] = await Promise.all([
        graphApi.citationDetail(paperId),
        graphApi.citationTree(paperId),
      ]);
      setDetailData(detail);
      setTreeData(tree);
      setTopicNetData(null);
    } catch { toast("error", "查询引用详情失败"); }
    finally { setLoading(false); }
  }, [paperId, toast]);

  /* 深度溯源 */
  const handleDeepTrace = useCallback(async () => {
    if (!topicNetData) return;
    setDeepTracing(true);
    try {
      const result = await graphApi.topicDeepTrace(topicNetData.topic_id);
      setTopicNetData(result);
      toast("success", `深度溯源完成，新增 ${result.stats.new_edges_synced || 0} 条引用边`);
    } catch { toast("error", "深度溯源失败"); }
    finally { setDeepTracing(false); }
  }, [topicNetData, toast]);

  const hasData = detailData || topicNetData || treeData;

  return (
    <div className="space-y-5">
      {/* ---- 论文选取器 ---- */}
      <div className="rounded-2xl border border-border bg-surface p-5 shadow-sm">
        {/* 模式切换 */}
        <div className="mb-3 flex gap-1 rounded-xl bg-page p-1">
          {([["search", "搜索论文", Search], ["topic", "按主题", Rss], ["action", "按行动", Clock]] as const).map(([mode, label, Icon]) => (
            <button
              key={mode}
              onClick={() => setPickerMode(mode as PickerMode)}
              className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg py-2 text-xs font-medium transition-all ${
                pickerMode === mode ? "bg-surface text-primary shadow-sm" : "text-ink-tertiary hover:text-ink"
              }`}
            >
              <Icon className="h-3 w-3" />
              {label}
            </button>
          ))}
        </div>

        {/* 搜索模式 */}
        {pickerMode === "search" && (
          <div className="flex gap-3">
            <div className="relative flex-1" ref={paperDropdownRef}>
              <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-tertiary" />
              <input
                placeholder="搜索论文标题，或直接输入论文 ID..."
                value={paperSearch || paperId}
                onChange={(e) => {
                  const v = e.target.value;
                  setPaperId(v);
                  setSelectedPaper(null);
                  handlePaperSearch(v);
                }}
                onFocus={() => { if (paperResults.length > 0) setShowPaperDropdown(true); }}
                onKeyDown={(e) => { if (e.key === "Enter") { setShowPaperDropdown(false); handleQuery(); } }}
                className="h-11 w-full rounded-xl border border-border bg-page pl-10 pr-4 text-sm text-ink placeholder:text-ink-placeholder focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
              {paperSearching && (
                <div className="absolute right-3 top-1/2 -translate-y-1/2">
                  <Loader2 className="h-4 w-4 animate-spin text-ink-tertiary" />
                </div>
              )}
              {showPaperDropdown && paperResults.length > 0 && (
                <div className="absolute left-0 right-0 top-full z-50 mt-1 max-h-72 overflow-y-auto rounded-xl border border-border bg-surface shadow-lg">
                  {paperResults.map((p) => (
                    <button
                      key={p.id}
                      onClick={() => handleSelectPaper(p)}
                      className={`flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-hover ${
                        selectedPaper?.id === p.id ? "bg-primary/5" : ""
                      }`}
                    >
                      <FileText className="mt-0.5 h-4 w-4 shrink-0 text-ink-tertiary" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-ink">{p.title}</p>
                        <div className="mt-0.5 flex items-center gap-2 text-[10px] text-ink-tertiary">
                          <span>{p.arxiv_id}</span>
                          {p.publication_date && <span>· {p.publication_date.slice(0, 10)}</span>}
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <Button icon={<Search className="h-4 w-4" />} onClick={handleQuery} loading={loading}>分析</Button>
          </div>
        )}

        {/* 按主题 */}
        {pickerMode === "topic" && (
          <div className="space-y-1.5 rounded-xl border border-border bg-page p-3 max-h-64 overflow-y-auto">
            {topics.length === 0 && <p className="text-xs text-ink-tertiary py-2 text-center">暂无订阅主题</p>}
            {topics.map((t) => (
              <button
                key={t.id}
                onClick={() => handleSelectTopic(t)}
                disabled={pickLoading}
                className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-hover disabled:opacity-50"
              >
                <Rss className="h-3.5 w-3.5 shrink-0 text-primary" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-ink">{t.name}</p>
                  <p className="truncate text-[10px] text-ink-tertiary">{t.query}</p>
                </div>
              </button>
            ))}
          </div>
        )}

        {/* 按行动 */}
        {pickerMode === "action" && (
          <div className="space-y-1.5 rounded-xl border border-border bg-page p-3 max-h-64 overflow-y-auto">
            {actions.length === 0 && <p className="text-xs text-ink-tertiary py-2 text-center">暂无行动记录</p>}
            {actions.map((a) => (
              <button
                key={a.id}
                onClick={() => handleSelectAction(a)}
                disabled={pickLoading}
                className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-hover disabled:opacity-50"
              >
                <ActionIcon type={a.action_type} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-ink">{a.title}</p>
                  <div className="mt-0.5 flex items-center gap-2 text-[10px] text-ink-tertiary">
                    <span>{ACTION_TYPE_LABEL[a.action_type] || a.action_type}</span>
                    <span>· {a.paper_count} 篇</span>
                    <span>· {new Date(a.created_at).toLocaleDateString("zh-CN")}</span>
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}

        {/* 已选中论文提示 */}
        {selectedPaper && (
          <div className="mt-2 flex items-center gap-2 rounded-lg bg-primary/5 px-3 py-1.5">
            <Network className="h-3.5 w-3.5 text-primary" />
            <span className="truncate text-xs text-primary">{selectedPaper.title}</span>
            <button
              onClick={() => { setSelectedPaper(null); setPaperId(""); setPaperSearch(""); }}
              className="ml-auto shrink-0 text-xs text-ink-tertiary hover:text-ink"
            >✕</button>
          </div>
        )}

        {/* 批量论文列表 */}
        {pickerMode !== "search" && paperResults.length > 1 && showPaperDropdown && (
          <div className="mt-2 max-h-48 overflow-y-auto rounded-xl border border-border bg-page">
            {paperResults.map((p) => (
              <button
                key={p.id}
                onClick={() => handleSelectPaper(p)}
                className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition-colors hover:bg-hover ${
                  selectedPaper?.id === p.id ? "bg-primary/5 text-primary" : "text-ink-secondary"
                }`}
              >
                <FileText className="h-3 w-3 shrink-0" />
                <span className="truncate">{p.title}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ---- 加载 ---- */}
      {loading && (
        <div className="flex flex-col items-center gap-3 py-12">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <p className="text-sm text-ink-secondary">正在分析引用关系...</p>
        </div>
      )}

      {/* ---- 无结果 ---- */}
      {!loading && !hasData && (
        <div className="flex flex-col items-center rounded-2xl border border-dashed border-border py-16 text-center">
          <Network className="h-8 w-8 text-ink-tertiary/30" />
          <p className="mt-4 text-sm text-ink-tertiary">搜索论文或选择主题，开始引文分析</p>
        </div>
      )}

      {/* ---- 结果区域 ---- */}
      {!loading && hasData && (
        <>
          {/* 视图切换 + 分析模式 */}
          <div className="flex items-center justify-between rounded-2xl border border-border bg-surface px-5 py-3 shadow-sm">
            <div className="flex items-center gap-2 text-sm text-ink-secondary">
              {analysisMode === "topic" ? (
                <><Rss className="h-4 w-4 text-primary" /><span>主题网络：<strong className="text-ink">{topicNetData?.topic_name}</strong></span></>
              ) : (
                <><Network className="h-4 w-4 text-primary" /><span>单篇分析：<strong className="text-ink">{detailData?.paper_title || treeData?.root_title}</strong></span></>
              )}
            </div>
            <div className="flex gap-1 rounded-xl bg-page p-1">
              <button
                onClick={() => setViewMode("list")}
                className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all ${
                  viewMode === "list" ? "bg-surface text-primary shadow-sm" : "text-ink-tertiary hover:text-ink"
                }`}
              >
                <List className="h-3.5 w-3.5" /> 列表
              </button>
              <button
                onClick={() => setViewMode("graph")}
                className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all ${
                  viewMode === "graph" ? "bg-surface text-primary shadow-sm" : "text-ink-tertiary hover:text-ink"
                }`}
              >
                <Share2 className="h-3.5 w-3.5" /> 图谱
              </button>
            </div>
          </div>

          {/* 单篇模式 */}
          {analysisMode === "paper" && detailData && (
            viewMode === "list"
              ? <RichCitationListView data={detailData} />
              : <PaperCitationGraphView detail={detailData} />
          )}

          {/* 主题模式 */}
          {analysisMode === "topic" && topicNetData && (
            <>
              {viewMode === "list"
                ? <TopicNetworkListView data={topicNetData} />
                : <TopicNetworkGraphView data={topicNetData} />}
              <div className="flex items-center justify-center">
                <Button
                  icon={<RotateCw className={`h-4 w-4 ${deepTracing ? "animate-spin" : ""}`} />}
                  loading={deepTracing}
                  onClick={handleDeepTrace}
                >
                  深度溯源
                </Button>
              </div>
            </>
          )}

          {/* 兜底: 老版 citation tree */}
          {!detailData && !topicNetData && treeData && <CitationTreeView data={treeData} />}
        </>
      )}
    </div>
  );
}

/* ==================== 引用列表视图 (单篇) ==================== */
function RichCitationListView({ data }: { data: CitationDetail }) {
  const { toast } = useToast();
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [importTask, setImportTask] = useState<ImportTaskStatus | null>(null);
  const [showModal, setShowModal] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval>>(undefined);

  const allEntries = useMemo(() => {
    const refs = data.references.map((e) => ({ ...e, direction: "reference" as const }));
    const cites = data.cited_by.map((e) => ({ ...e, direction: "citation" as const }));
    return [...refs, ...cites];
  }, [data]);

  const importable = useMemo(
    () => allEntries.map((e, i) => ({ ...e, _idx: i })).filter((e) => !e.in_library),
    [allEntries],
  );

  const toggleSelect = (idx: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(idx) ? next.delete(idx) : next.add(idx);
      return next;
    });
  };

  const selectAll = () => {
    if (selected.size === importable.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(importable.map((e) => e._idx)));
    }
  };

  const startImport = async (indices: number[]) => {
    const entries: ReferenceImportEntry[] = indices.map((i) => {
      const e = allEntries[i];
      return {
        scholar_id: e.scholar_id, title: e.title,
        year: e.year, venue: e.venue,
        citation_count: e.citation_count,
        arxiv_id: e.arxiv_id, abstract: e.abstract,
        direction: e.direction,
      };
    });
    if (entries.length === 0) return;

    setShowModal(true);
    try {
      const { task_id } = await ingestApi.importReferences({
        source_paper_id: data.paper_id,
        source_paper_title: data.paper_title,
        entries,
      });
      pollRef.current = setInterval(async () => {
        try {
          const status = await ingestApi.importStatus(task_id);
          setImportTask(status);
          if (status.status !== "running") {
            clearInterval(pollRef.current);
            toast(
              status.status === "completed" ? "success" : "error",
              `${status.status === "completed" ? "导入完成" : "导入失败"}: 成功 ${status.imported} / 跳过 ${status.skipped} / 失败 ${status.failed}`,
            );
          }
        } catch {
          clearInterval(pollRef.current);
        }
      }, 1000);
    } catch (err) {
      toast("error", `导入启动失败: ${String(err)}`);
      setShowModal(false);
    }
  };

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const hasArxiv = (indices: number[]) => indices.filter((i) => allEntries[i]?.arxiv_id).length;
  const hasNoArxiv = (indices: number[]) => indices.length - hasArxiv(indices);
  const selectedArr = Array.from(selected);

  return (
    <div className="space-y-6 animate-fade-in">
      {/* 统计卡片 */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-xl border border-border bg-page p-3 text-center">
          <p className="text-lg font-bold text-primary">{data.stats.total_references}</p>
          <p className="text-[10px] text-ink-tertiary">参考文献</p>
        </div>
        <div className="rounded-xl border border-border bg-page p-3 text-center">
          <p className="text-lg font-bold text-info">{data.stats.total_cited_by}</p>
          <p className="text-[10px] text-ink-tertiary">被引用</p>
        </div>
        <div className="rounded-xl border border-border bg-success/5 p-3 text-center">
          <p className="text-lg font-bold text-success">{data.stats.in_library_references}</p>
          <p className="text-[10px] text-ink-tertiary">参考文献在库</p>
        </div>
        <div className="rounded-xl border border-border bg-success/5 p-3 text-center">
          <p className="text-lg font-bold text-success">{data.stats.in_library_cited_by}</p>
          <p className="text-[10px] text-ink-tertiary">被引在库</p>
        </div>
      </div>

      {/* 批量操作栏 */}
      {importable.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-dashed border-primary/30 bg-primary/5 px-4 py-3">
          <button
            onClick={selectAll}
            className="flex items-center gap-1.5 text-xs font-medium text-primary hover:underline"
          >
            <div className={`h-4 w-4 rounded border-2 flex items-center justify-center transition-colors ${
              selected.size === importable.length ? "border-primary bg-primary" : "border-ink-tertiary"
            }`}>
              {selected.size === importable.length && <CheckCircle2 className="h-3 w-3 text-white" />}
            </div>
            {selected.size === importable.length ? "取消全选" : `全选 ${importable.length} 篇可入库`}
          </button>
          {selected.size > 0 && (
            <>
              <span className="text-[10px] text-ink-tertiary">
                已选 {selected.size} 篇（{hasArxiv(selectedArr)} 篇有 arXiv，{hasNoArxiv(selectedArr)} 篇仅元数据）
              </span>
              <Button
                size="sm"
                onClick={() => startImport(selectedArr)}
                className="ml-auto gap-1.5"
              >
                <PackagePlus className="h-3.5 w-3.5" />
                一键入库 ({selected.size})
              </Button>
            </>
          )}
          {selected.size === 0 && (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                selectAll();
                setTimeout(() => startImport(importable.map((e) => e._idx)), 50);
              }}
              className="ml-auto gap-1.5"
            >
              <PackagePlus className="h-3.5 w-3.5" />
              全部入库 ({importable.length})
            </Button>
          )}
        </div>
      )}

      {/* 参考文献列表 */}
      {data.references.length > 0 && (
        <Section title={`参考文献 (${data.references.length})`} icon={<ArrowDown className="h-4 w-4 text-primary" />}>
          <div className="space-y-2">
            {data.references.map((entry, i) => (
              <RichCitationCard
                key={i}
                entry={entry}
                idx={i}
                selected={selected.has(i)}
                onToggle={() => toggleSelect(i)}
                onImport={() => startImport([i])}
              />
            ))}
          </div>
        </Section>
      )}

      {/* 被引列表 */}
      {data.cited_by.length > 0 && (
        <Section title={`被引用 (${data.cited_by.length})`} icon={<ArrowUp className="h-4 w-4 text-info" />}>
          <div className="space-y-2">
            {data.cited_by.map((entry, i) => {
              const globalIdx = data.references.length + i;
              return (
                <RichCitationCard
                  key={i}
                  entry={entry}
                  idx={globalIdx}
                  selected={selected.has(globalIdx)}
                  onToggle={() => toggleSelect(globalIdx)}
                  onImport={() => startImport([globalIdx])}
                />
              );
            })}
          </div>
        </Section>
      )}

      {/* 导入进度弹窗 */}
      {showModal && (
        <ImportProgressModal
          task={importTask}
          onClose={() => { setShowModal(false); setImportTask(null); }}
        />
      )}
    </div>
  );
}

function RichCitationCard({
  entry, idx, selected, onToggle, onImport,
}: {
  entry: RichCitationEntry;
  idx: number;
  selected: boolean;
  onToggle: () => void;
  onImport: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className={`rounded-xl border transition-all hover:shadow-sm ${
      selected ? "border-primary/40 bg-primary/5" : "border-border bg-page/50"
    }`}>
      <div className="flex items-start gap-2 px-3 py-3">
        {/* 勾选框 — 仅非在库的显示 */}
        {!entry.in_library ? (
          <button onClick={onToggle} className="mt-0.5 shrink-0">
            <div className={`h-4 w-4 rounded border-2 flex items-center justify-center transition-colors ${
              selected ? "border-primary bg-primary" : "border-ink-tertiary hover:border-primary/60"
            }`}>
              {selected && <CheckCircle2 className="h-3 w-3 text-white" />}
            </div>
          </button>
        ) : (
          <div className="mt-0.5 h-4 w-4 shrink-0" />
        )}

        <button onClick={() => setExpanded(!expanded)} className="flex min-w-0 flex-1 items-start gap-2 text-left">
          <FileText className="mt-0.5 h-4 w-4 shrink-0 text-ink-tertiary" />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <p className="text-sm font-medium text-ink line-clamp-2">{entry.title}</p>
              {entry.in_library && (
                <span className="shrink-0 rounded-md bg-success/10 px-1.5 py-0.5 text-[10px] font-medium text-success">在库</span>
              )}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10px] text-ink-tertiary">
              {entry.year && <span>{entry.year}</span>}
              {entry.venue && <span>{entry.venue}</span>}
              {entry.citation_count != null && <span>引用 {entry.citation_count}</span>}
              {entry.arxiv_id && <span className="font-mono">{entry.arxiv_id}</span>}
            </div>
          </div>
          <div className="shrink-0 pt-1">
            {expanded ? <ChevronDown className="h-3.5 w-3.5 text-ink-tertiary" /> : <ChevronRight className="h-3.5 w-3.5 text-ink-tertiary" />}
          </div>
        </button>

        {/* 单独入库按钮 */}
        {!entry.in_library && (
          <button
            onClick={onImport}
            title="入库此论文"
            className="mt-0.5 shrink-0 rounded-lg p-1.5 text-ink-tertiary hover:bg-primary/10 hover:text-primary transition-colors"
          >
            <PackagePlus className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {expanded && (
        <div className="border-t border-border px-4 py-3">
          {entry.abstract && (
            <p className="text-xs leading-relaxed text-ink-secondary mb-2">{entry.abstract}</p>
          )}
          <div className="flex flex-wrap gap-2">
            {entry.in_library && entry.library_paper_id && (
              <Link to={`/papers/${entry.library_paper_id}`} className="inline-flex items-center gap-1 rounded-lg bg-primary/10 px-2.5 py-1 text-[10px] font-medium text-primary hover:bg-primary/20">
                <ExternalLink className="h-3 w-3" /> 查看详情
              </Link>
            )}
            {entry.arxiv_id && (
              <a href={`https://arxiv.org/abs/${entry.arxiv_id}`} target="_blank" rel="noreferrer"
                className="inline-flex items-center gap-1 rounded-lg bg-page px-2.5 py-1 text-[10px] font-medium text-ink-secondary hover:text-ink">
                <ExternalLink className="h-3 w-3" /> arXiv
              </a>
            )}
            {entry.scholar_id && (
              <a href={`https://www.semanticscholar.org/paper/${entry.scholar_id}`} target="_blank" rel="noreferrer"
                className="inline-flex items-center gap-1 rounded-lg bg-page px-2.5 py-1 text-[10px] font-medium text-ink-secondary hover:text-ink">
                <ExternalLink className="h-3 w-3" /> Semantic Scholar
              </a>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ==================== 导入进度弹窗 ==================== */

function ImportProgressModal({
  task, onClose,
}: {
  task: ImportTaskStatus | null;
  onClose: () => void;
}) {
  const pct = task && task.total > 0 ? Math.round((task.completed / task.total) * 100) : 0;
  const done = task?.status === "completed" || task?.status === "failed";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-lg rounded-2xl bg-surface shadow-xl border border-border">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="flex items-center gap-2">
            <PackagePlus className="h-5 w-5 text-primary" />
            <h3 className="text-sm font-semibold text-ink">参考文献导入</h3>
          </div>
          {done && (
            <button onClick={onClose} className="rounded-lg p-1 hover:bg-page">
              <X className="h-4 w-4 text-ink-tertiary" />
            </button>
          )}
        </div>

        {/* Body */}
        <div className="p-5 space-y-4">
          {/* 进度条 */}
          <div>
            <div className="flex items-center justify-between text-xs text-ink-secondary mb-1.5">
              <span>{task?.status === "running" ? `正在导入: ${task.current || "..."}` : done ? "导入完成" : "准备中..."}</span>
              <span>{pct}%</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-page">
              <div
                className={`h-full rounded-full transition-all duration-300 ${
                  task?.status === "failed" ? "bg-error" : "bg-primary"
                }`}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>

          {/* 统计 */}
          {task && (
            <div className="grid grid-cols-4 gap-3 text-center">
              <div className="rounded-lg bg-page p-2">
                <p className="text-sm font-bold text-ink">{task.total}</p>
                <p className="text-[10px] text-ink-tertiary">总计</p>
              </div>
              <div className="rounded-lg bg-success/5 p-2">
                <p className="text-sm font-bold text-success">{task.imported}</p>
                <p className="text-[10px] text-ink-tertiary">已导入</p>
              </div>
              <div className="rounded-lg bg-warning/5 p-2">
                <p className="text-sm font-bold text-warning">{task.skipped}</p>
                <p className="text-[10px] text-ink-tertiary">跳过</p>
              </div>
              <div className="rounded-lg bg-error/5 p-2">
                <p className="text-sm font-bold text-error">{task.failed}</p>
                <p className="text-[10px] text-ink-tertiary">失败</p>
              </div>
            </div>
          )}

          {/* 结果明细 */}
          {done && task && task.results.length > 0 && (
            <div className="max-h-52 overflow-y-auto rounded-xl border border-border">
              {task.results.map((r, i) => (
                <div key={i} className="flex items-center gap-2 border-b border-border/50 px-3 py-2 last:border-0">
                  {r.status === "imported" && <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-success" />}
                  {r.status === "skipped" && <SkipForward className="h-3.5 w-3.5 shrink-0 text-warning" />}
                  {r.status === "failed" && <XCircle className="h-3.5 w-3.5 shrink-0 text-error" />}
                  <span className="min-w-0 flex-1 truncate text-xs text-ink">{r.title}</span>
                  {r.reason && <span className="shrink-0 text-[10px] text-ink-tertiary">{r.reason}</span>}
                  {r.source && <span className="shrink-0 rounded bg-page px-1.5 py-0.5 text-[10px] text-ink-tertiary">{r.source}</span>}
                </div>
              ))}
            </div>
          )}

          {task?.error && (
            <p className="text-xs text-error">{task.error}</p>
          )}
        </div>

        {/* Footer */}
        {done && (
          <div className="border-t border-border px-5 py-3 flex justify-end">
            <Button size="sm" onClick={onClose}>关闭</Button>
          </div>
        )}
      </div>
    </div>
  );
}

/* ==================== 单篇引用图谱视图 ==================== */
function PaperCitationGraphView({ detail }: { detail: CitationDetail }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 500 });

  useEffect(() => {
    if (!containerRef.current) return;
    const obs = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setDimensions({ width: entry.contentRect.width, height: Math.max(entry.contentRect.height, 500) });
    });
    obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, []);

  const graphData = useMemo(() => {
    const nodes: Array<{ id: string; label: string; group: string; val: number }> = [];
    const links: Array<{ source: string; target: string }> = [];
    const nodeSet = new Set<string>();

    const centerId = detail.paper_id;
    nodes.push({ id: centerId, label: detail.paper_title, group: "center", val: 8 });
    nodeSet.add(centerId);

    for (const ref of detail.references) {
      const nid = ref.library_paper_id || `ref-${ref.scholar_id || ref.title.slice(0, 20)}`;
      if (!nodeSet.has(nid)) {
        nodeSet.add(nid);
        nodes.push({
          id: nid,
          label: ref.title.length > 40 ? ref.title.slice(0, 40) + "..." : ref.title,
          group: ref.in_library ? "in_library" : "reference",
          val: Math.max(2, Math.min(6, Math.log2((ref.citation_count || 1) + 1))),
        });
      }
      links.push({ source: centerId, target: nid });
    }

    for (const cit of detail.cited_by) {
      const nid = cit.library_paper_id || `cit-${cit.scholar_id || cit.title.slice(0, 20)}`;
      if (!nodeSet.has(nid)) {
        nodeSet.add(nid);
        nodes.push({
          id: nid,
          label: cit.title.length > 40 ? cit.title.slice(0, 40) + "..." : cit.title,
          group: cit.in_library ? "in_library" : "citation",
          val: Math.max(2, Math.min(6, Math.log2((cit.citation_count || 1) + 1))),
        });
      }
      links.push({ source: nid, target: centerId });
    }

    return { nodes, links };
  }, [detail]);

  const nodeColor = useCallback((node: { group?: string }) => {
    switch (node.group) {
      case "center": return "#6366f1";
      case "in_library": return "#22c55e";
      case "reference": return "#3b82f6";
      case "citation": return "#f59e0b";
      default: return "#94a3b8";
    }
  }, []);

  return (
    <Section title="引用图谱" icon={<Share2 className="h-4 w-4 text-primary" />}
      desc={`${graphData.nodes.length} 节点 · ${graphData.links.length} 引用边`}>
      <div className="flex flex-wrap gap-3 mb-3 text-[10px]">
        <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-full bg-[#6366f1]" /> 当前论文</span>
        <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-full bg-[#3b82f6]" /> 参考文献</span>
        <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-full bg-[#f59e0b]" /> 引用者</span>
        <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-full bg-[#22c55e]" /> 已入库</span>
      </div>
      <div ref={containerRef} className="h-[500px] w-full rounded-xl border border-border bg-page overflow-hidden">
        <ForceGraph2D
          graphData={graphData}
          width={dimensions.width}
          height={dimensions.height}
          nodeLabel="label"
          nodeColor={nodeColor as any}
          nodeRelSize={5}
          linkDirectionalArrowLength={4}
          linkDirectionalArrowRelPos={1}
          linkColor={() => "rgba(148,163,184,0.3)"}
          cooldownTicks={80}
          nodeCanvasObjectMode={() => "after"}
          nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
            if (!node.x || !node.y) return;
            const label = node.label || "";
            const fontSize = Math.max(10 / globalScale, 2);
            ctx.font = `${fontSize}px Sans-serif`;
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            ctx.fillStyle = "rgba(30,41,59,0.8)";
            if (globalScale > 1.5 || node.group === "center") {
              ctx.fillText(label.slice(0, 30), node.x, node.y + 6);
            }
          }}
        />
      </div>
    </Section>
  );
}

/* ==================== 主题网络列表视图 ==================== */
function TopicNetworkListView({ data }: { data: TopicCitationNetwork }) {
  const hubs = data.nodes.filter((n) => n.is_hub && !n.is_external);
  const externals = data.nodes.filter((n) => n.is_external);
  const internals = data.nodes.filter((n) => !n.is_external);

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-xl border border-border bg-page p-3 text-center">
          <p className="text-lg font-bold text-ink">{data.stats.total_papers}</p>
          <p className="text-[10px] text-ink-tertiary">总论文数</p>
        </div>
        <div className="rounded-xl border border-border bg-page p-3 text-center">
          <p className="text-lg font-bold text-primary">{data.stats.total_edges}</p>
          <p className="text-[10px] text-ink-tertiary">引用边</p>
        </div>
        <div className="rounded-xl border border-border bg-page p-3 text-center">
          <p className="text-lg font-bold text-info">{data.stats.density}</p>
          <p className="text-[10px] text-ink-tertiary">密度</p>
        </div>
        <div className="rounded-xl border border-border bg-warning/5 p-3 text-center">
          <p className="text-lg font-bold text-warning">{data.stats.hub_papers}</p>
          <p className="text-[10px] text-ink-tertiary">Hub 论文</p>
        </div>
      </div>

      {hubs.length > 0 && (
        <Section title={`Hub 论文 (${hubs.length})`} icon={<Star className="h-4 w-4 text-warning" />}>
          <div className="space-y-2">
            {hubs.sort((a, b) => b.in_degree - a.in_degree).map((n) => (
              <div key={n.id} className="flex items-center justify-between rounded-xl border border-warning/20 bg-warning/5 p-3">
                <div className="min-w-0 flex-1">
                  <PaperLink id={n.id} title={n.title} />
                  <div className="mt-0.5 flex gap-3 text-[10px] text-ink-tertiary">
                    {n.year && <span>{n.year}</span>}
                    <span>被引 {n.in_degree}</span>
                    <span>引用 {n.out_degree}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      <Section title={`主题内论文 (${internals.length})`} icon={<Layers className="h-4 w-4 text-primary" />}>
        <div className="space-y-1">
          {internals.sort((a, b) => (b.in_degree + b.out_degree) - (a.in_degree + a.out_degree)).map((n) => (
            <div key={n.id} className="flex items-center gap-3 rounded-xl px-4 py-2.5 transition-colors hover:bg-hover">
              <PaperLink id={n.id} title={n.title} className="min-w-0 flex-1 truncate" />
              <div className="flex shrink-0 gap-2 text-[10px] text-ink-tertiary">
                {n.year && <span>{n.year}</span>}
                <span>↓{n.in_degree}</span>
                <span>↑{n.out_degree}</span>
                {n.is_hub && <Badge variant="warning">Hub</Badge>}
              </div>
            </div>
          ))}
        </div>
      </Section>

      {externals.length > 0 && (
        <Section title={`关键外部论文 (${externals.length})`} icon={<ExternalLink className="h-4 w-4 text-info" />}>
          <div className="space-y-1">
            {externals.sort((a, b) => (b.co_citation_count || 0) - (a.co_citation_count || 0)).map((n) => (
              <div key={n.id} className="flex items-center gap-3 rounded-xl bg-info/5 px-4 py-2.5">
                <PaperLink id={n.id} title={n.title} className="min-w-0 flex-1 truncate" />
                <span className="shrink-0 text-[10px] text-info">共引 {n.co_citation_count || 0}</span>
              </div>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}

/* ==================== 主题网络图谱视图 ==================== */
function TopicNetworkGraphView({ data }: { data: TopicCitationNetwork }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  useEffect(() => {
    if (!containerRef.current) return;
    const obs = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setDimensions({ width: entry.contentRect.width, height: Math.max(entry.contentRect.height, 600) });
    });
    obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, []);

  const graphData = useMemo(() => {
    const nodes = data.nodes.map((n) => ({
      id: n.id,
      label: n.title.length > 30 ? n.title.slice(0, 30) + "..." : n.title,
      group: n.is_external ? "external" : n.is_hub ? "hub" : "internal",
      val: n.is_hub ? 6 : n.is_external ? 4 : 3,
    }));
    const nodeSet = new Set(nodes.map((n) => n.id));
    const links = data.edges
      .filter((e) => nodeSet.has(e.source) && nodeSet.has(e.target))
      .map((e) => ({ source: e.source, target: e.target }));
    return { nodes, links };
  }, [data]);

  const nodeColor = useCallback((node: { group?: string }) => {
    switch (node.group) {
      case "hub": return "#f59e0b";
      case "external": return "#8b5cf6";
      case "internal": return "#3b82f6";
      default: return "#94a3b8";
    }
  }, []);

  return (
    <Section title="主题引用网络" icon={<Share2 className="h-4 w-4 text-primary" />}
      desc={`${data.nodes.length} 论文 · ${data.edges.length} 引用边 · 密度 ${data.stats.density}`}>
      <div className="flex flex-wrap gap-3 mb-3 text-[10px]">
        <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-full bg-[#3b82f6]" /> 主题内</span>
        <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-full bg-[#f59e0b]" /> Hub</span>
        <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-full bg-[#8b5cf6]" /> 外部</span>
      </div>
      <div ref={containerRef} className="h-[600px] w-full rounded-xl border border-border bg-page overflow-hidden">
        <ForceGraph2D
          graphData={graphData}
          width={dimensions.width}
          height={dimensions.height}
          nodeLabel="label"
          nodeColor={nodeColor as any}
          nodeRelSize={5}
          linkDirectionalArrowLength={4}
          linkDirectionalArrowRelPos={1}
          linkColor={() => "rgba(148,163,184,0.25)"}
          cooldownTicks={100}
          nodeCanvasObjectMode={() => "after"}
          nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
            if (!node.x || !node.y) return;
            const label = node.label || "";
            const isHub = node.group === "hub";
            const fontSize = Math.max((isHub ? 12 : 10) / globalScale, 2);
            ctx.font = `${isHub ? "bold " : ""}${fontSize}px Sans-serif`;
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            ctx.fillStyle = isHub ? "#92400e" : "rgba(30,41,59,0.7)";
            if (globalScale > 1.2 || isHub) {
              ctx.fillText(label, node.x, node.y + 6);
            }
          }}
        />
      </div>

      {data.key_external_papers && data.key_external_papers.length > 0 && (
        <div className="mt-4 rounded-xl bg-purple-50 dark:bg-purple-950/20 p-4">
          <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-purple-700 dark:text-purple-300">
            <ExternalLink className="h-3.5 w-3.5" /> 关键外部论文（共引分析）
          </p>
          <div className="space-y-1">
            {data.key_external_papers.map((p) => (
              <div key={p.id} className="flex items-center gap-2 text-sm">
                <PaperLink id={p.id} title={p.title} className="flex-1 truncate" />
                <span className="shrink-0 rounded-md bg-purple-100 dark:bg-purple-900/30 px-2 py-0.5 text-[10px] font-medium text-purple-700 dark:text-purple-300">
                  共引 {p.co_citation_count}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Section>
  );
}

/* ==================== 引用树视图 (兜底) ==================== */
function CitationTreeView({ data }: { data: CitationTree }) {
  return (
    <Section title={data.root_title || "引用树"} icon={<Network className="h-4 w-4 text-primary" />}
      desc={`${data.nodes.length} 节点 · ${data.edge_count} 引用边`}>
      <div className="space-y-4">
        {data.ancestors.length > 0 && (
          <div>
            <p className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-widest text-ink-tertiary">
              <ArrowUp className="h-3 w-3" /> 被引用
            </p>
            <div className="space-y-1">
              {data.ancestors.map((edge, i) => {
                const node = data.nodes.find((n) => n.id === edge.source);
                return (
                  <div key={i} className="flex items-center gap-3 rounded-xl bg-page px-4 py-2.5">
                    <Badge variant="info">L{edge.depth}</Badge>
                    <PaperLink id={edge.source} title={node?.title || edge.source} className="flex-1 truncate" />
                    {node?.year && <span className="text-xs text-ink-tertiary">{node.year}</span>}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <div className="flex items-center gap-3 rounded-2xl border-2 border-primary/30 bg-primary/5 px-5 py-4">
          <Network className="h-5 w-5 text-primary" />
          <span className="text-base font-bold text-ink">{data.root_title}</span>
        </div>

        {data.descendants.length > 0 && (
          <div>
            <p className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-widest text-ink-tertiary">
              <ArrowDown className="h-3 w-3" /> 引用了
            </p>
            <div className="space-y-1">
              {data.descendants.map((edge, i) => {
                const node = data.nodes.find((n) => n.id === edge.target);
                return (
                  <div key={i} className="flex items-center gap-3 rounded-xl bg-page px-4 py-2.5">
                    <Badge variant="success">L{edge.depth}</Badge>
                    <PaperLink id={edge.target} title={node?.title || edge.target} className="flex-1 truncate" />
                    {node?.year && <span className="text-xs text-ink-tertiary">{node.year}</span>}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </Section>
  );
}
