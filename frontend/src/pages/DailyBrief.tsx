/**
 * Daily Brief - 研究简报（重构：清晰排版 + 暗色适配 + 阅读体验优化）
 * @author Bamzc
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Spinner, Empty } from "@/components/ui";
import { useToast } from "@/contexts/ToastContext";
import DOMPurify from "dompurify";
import ConfirmDialog from "@/components/ConfirmDialog";
import { briefApi, generatedApi, tasksApi } from "@/services/api";
import type { GeneratedContentListItem, GeneratedContent } from "@/types";
import {
  Newspaper, Send, CheckCircle2, Mail, FileText, Calendar, Clock,
  Trash2, ChevronRight, Sparkles, Plus, RefreshCw, X,
} from "lucide-react";

export default function DailyBrief() {
  const { toast } = useToast();
  const navigate = useNavigate();
  const briefRef = useRef<HTMLDivElement>(null);
  const [date, setDate] = useState("");
  const [recipient, setRecipient] = useState("");
  const [loading, setLoading] = useState(false);
  const [taskProgress, setTaskProgress] = useState<string>("");
  const [genDone, setGenDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [history, setHistory] = useState<GeneratedContentListItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [selectedContent, setSelectedContent] = useState<GeneratedContent | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [showGenPanel, setShowGenPanel] = useState(false);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try { const res = await generatedApi.list("daily_brief", 50); setHistory(res.items); }
    catch { toast("error", "加载历史简报失败"); } finally { setHistoryLoading(false); }
  }, [toast]);

  useEffect(() => { loadHistory(); }, [loadHistory]);

  // 自动加载最新一份
  useEffect(() => {
    if (history.length > 0 && !selectedContent) {
      handleView(history[0]);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [history]);

  // 事件委托：点击简报中的论文卡片跳转到详情页
  useEffect(() => {
    const el = briefRef.current;
    if (!el) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      const card = target.closest<HTMLElement>("[data-paper-id]");
      if (card) {
        const paperId = card.dataset.paperId;
        if (paperId) navigate(`/papers/${paperId}`);
      }
    };
    el.addEventListener("click", handler);
    return () => el.removeEventListener("click", handler);
  }, [navigate, selectedContent]);

  const handleGenerate = async () => {
    setLoading(true); setError(null); setGenDone(false); setTaskProgress("正在提交任务...");
    try {
      const data: Record<string, string> = {};
      if (date) data.date = date;
      if (recipient) data.recipient = recipient;
      const res = await briefApi.daily(Object.keys(data).length > 0 ? data : undefined);
      const taskId = res.task_id;
      setTaskProgress("任务已提交，正在生成简报...");

      // 轮询任务状态，直到完成或失败
      const POLL_INTERVAL = 3000;
      const MAX_WAIT_MS = 5 * 60 * 1000; // 最多等 5 分钟
      const startTime = Date.now();

      await new Promise<void>((resolve, reject) => {
        const poll = async () => {
          if (Date.now() - startTime > MAX_WAIT_MS) {
            reject(new Error("生成超时，请稍后刷新查看结果"));
            return;
          }
          try {
            const status = await tasksApi.getStatus(taskId);
            const pct = Math.round(status.progress * 100);
            setTaskProgress(status.message || `生成中... ${pct}%`);
            if (status.status === "completed") { resolve(); return; }
            if (status.status === "failed") { reject(new Error(status.error || "生成失败")); return; }
          } catch {
            // 轮询出错不中断，继续重试
          }
          setTimeout(poll, POLL_INTERVAL);
        };
        poll();
      });

      setGenDone(true);
      setTaskProgress("");
      await loadHistory();
      setShowGenPanel(false);
      toast("success", "简报生成成功");
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成失败");
      setTaskProgress("");
    } finally {
      setLoading(false);
    }
  };

  const handleView = async (item: GeneratedContentListItem) => {
    setDetailLoading(true); setSelectedContent(null);
    try { setSelectedContent(await generatedApi.detail(item.id)); }
    catch { toast("error", "加载简报内容失败"); } finally { setDetailLoading(false); }
  };

  const handleDelete = async (id: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    try { await generatedApi.delete(id); setHistory((p) => p.filter((h) => h.id !== id)); if (selectedContent?.id === id) setSelectedContent(null); }
    catch { toast("error", "删除简报失败"); }
  };

  const fmtDate = (iso: string) => {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1);
    const isYesterday = d.toDateString() === yesterday.toDateString();
    if (isToday) return `今天 ${d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`;
    if (isYesterday) return `昨天 ${d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`;
    return d.toLocaleDateString("zh-CN", { month: "short", day: "numeric" }) + " " + d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  };

  return (
    <div className="animate-fade-in flex h-full flex-col">
      {/* 顶栏 */}
      <div className="flex shrink-0 items-center justify-between border-b border-border px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="rounded-xl bg-primary/10 p-2"><Newspaper className="h-5 w-5 text-primary" /></div>
          <div>
            <h1 className="text-lg font-bold text-ink">研究简报</h1>
            <p className="text-xs text-ink-tertiary">自动汇总最新研究进展</p>
          </div>
        </div>
        <Button
          size="sm"
          icon={showGenPanel ? <X className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />}
          onClick={() => setShowGenPanel(!showGenPanel)}
        >
          {showGenPanel ? "收起" : "生成新简报"}
        </Button>
      </div>

      {/* 生成面板（可折叠） */}
      {showGenPanel && (
        <div className="shrink-0 border-b border-border bg-surface/50 px-6 py-4">
          <div className="flex flex-wrap items-end gap-4">
            <div className="space-y-1">
              <label className="flex items-center gap-1 text-[11px] font-medium text-ink-secondary">
                <Calendar className="h-3 w-3" /> 日期
              </label>
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
                className="h-9 rounded-lg border border-border bg-page px-3 text-xs text-ink focus:border-primary focus:outline-none" />
            </div>
            <div className="space-y-1">
              <label className="flex items-center gap-1 text-[11px] font-medium text-ink-secondary">
                <Mail className="h-3 w-3" /> 邮件通知
              </label>
              <input type="email" value={recipient} onChange={(e) => setRecipient(e.target.value)}
                placeholder="可选"
                className="h-9 w-48 rounded-lg border border-border bg-page px-3 text-xs text-ink placeholder:text-ink-placeholder focus:border-primary focus:outline-none" />
            </div>
            <Button icon={loading ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} onClick={handleGenerate} loading={loading}>
              生成
            </Button>
          </div>
          {error && <p className="mt-2 text-xs text-error">{error}</p>}
          {taskProgress && !error && (
            <p className="mt-2 flex items-center gap-1.5 text-xs text-ink-secondary">
              <RefreshCw className="h-3 w-3 animate-spin" />
              {taskProgress}
            </p>
          )}
          {genDone && !loading && (
            <div className="mt-2 flex items-center gap-2">
              <CheckCircle2 className="h-3.5 w-3.5 text-success" />
              <span className="text-xs text-success">生成成功</span>
            </div>
          )}
        </div>
      )}

      {/* 主体：左侧列表 + 右侧内容 */}
      <div className="flex min-h-0 flex-1">
        {/* 左侧历史列表 */}
        <div className="w-56 shrink-0 overflow-y-auto border-r border-border bg-page/30 lg:w-64">
          <div className="px-3 pb-2 pt-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-ink-tertiary">
              历史简报 ({history.length})
            </p>
          </div>
          {historyLoading ? (
            <div className="p-4"><Spinner text="" /></div>
          ) : history.length === 0 ? (
            <div className="px-3 py-8 text-center text-xs text-ink-tertiary">
              <Newspaper className="mx-auto mb-2 h-8 w-8 text-ink-tertiary/20" />
              暂无简报
            </div>
          ) : (
            <div className="space-y-0.5 px-2 pb-4">
              {history.map((item) => {
                const active = selectedContent?.id === item.id;
                return (
                  <div
                    role="button"
                    tabIndex={0}
                    key={item.id}
                    onClick={() => handleView(item)}
                    onKeyDown={(e) => { if (e.key === "Enter") handleView(item); }}
                    className={`group flex w-full cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-all ${
                      active
                        ? "bg-primary/10 text-primary"
                        : "text-ink hover:bg-surface"
                    }`}
                  >
                    <FileText className={`h-3.5 w-3.5 shrink-0 ${active ? "text-primary" : "text-ink-tertiary"}`} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-medium">{item.title.replace("Daily Brief: ", "")}</p>
                      <p className="mt-0.5 text-[10px] text-ink-tertiary">{fmtDate(item.created_at)}</p>
                    </div>
                    <button
                      aria-label="删除"
                      onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(item.id); }}
                      className="shrink-0 rounded p-0.5 text-ink-tertiary opacity-0 transition-opacity hover:text-error group-hover:opacity-100"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* 右侧内容 */}
        <div className="min-w-0 flex-1 overflow-y-auto">
          {detailLoading && (
            <div className="flex h-full items-center justify-center">
              <Spinner text="加载简报..." />
            </div>
          )}

          {!detailLoading && selectedContent && (
            <div className="animate-fade-in">
              {/* 内容头 */}
              <div className="border-b border-border px-8 py-5">
                <h2 className="text-xl font-bold text-ink">{selectedContent.title}</h2>
                <p className="mt-1 text-xs text-ink-tertiary">
                  <Clock className="mr-1 inline h-3 w-3" />
                  {new Date(selectedContent.created_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })}
                </p>
              </div>

              {/* 简报正文 */}
              <div className="px-8 py-6">
                <div
                  ref={briefRef}
                  className="brief-content"
                  dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(selectedContent.markdown, { ADD_ATTR: ["data-paper-id", "data-arxiv-id"] }) }}
                />
              </div>
            </div>
          )}

          {!detailLoading && !selectedContent && (
            <div className="flex h-full flex-col items-center justify-center text-ink-tertiary">
              <div className="rounded-2xl bg-page p-6"><Sparkles className="h-10 w-10 text-ink-tertiary/20" /></div>
              <p className="mt-4 text-sm">点击「生成新简报」或从左侧选择查看</p>
            </div>
          )}
        </div>
      </div>

      {/* 简报内容样式覆盖 */}
      <style>{briefContentStyles}</style>

      <ConfirmDialog
        open={!!confirmDeleteId}
        title="删除简报"
        description="确定要删除这份研究简报吗？"
        variant="danger"
        confirmLabel="删除"
        onConfirm={async () => { if (confirmDeleteId) { await handleDelete(confirmDeleteId); setConfirmDeleteId(null); } }}
        onCancel={() => setConfirmDeleteId(null)}
      />
    </div>
  );
}

/**
 * 覆盖后端生成的 HTML 简报样式，适配 app 主题 + 暗色模式
 */
const briefContentStyles = `
.brief-content {
  max-width: 720px;
  margin: 0 auto;
  color: var(--color-ink, #1a1a2e);
  font-family: inherit;
  line-height: 1.7;
}

/* 重置后端内联样式 */
.brief-content body,
.brief-content html {
  all: unset;
  display: block;
}
.brief-content * {
  font-family: inherit !important;
  box-sizing: border-box;
}

/* 标题 */
.brief-content h1 {
  font-size: 1.5rem;
  font-weight: 800;
  margin-bottom: 4px;
  color: var(--color-ink, #111);
}
.brief-content .subtitle {
  font-size: 0.8rem;
  color: var(--color-ink-tertiary, #888);
  margin-bottom: 1.5rem;
}

/* 统计卡片 */
.brief-content .stats {
  display: grid !important;
  grid-template-columns: repeat(4, 1fr) !important;
  gap: 12px;
  margin-bottom: 2rem;
}
.brief-content .stat-card {
  background: var(--color-page, #f8f9fa) !important;
  border: 1px solid var(--color-border, #e2e8f0) !important;
  border-radius: 12px !important;
  padding: 16px !important;
  text-align: center;
}
.brief-content .stat-num {
  font-size: 2rem !important;
  font-weight: 800 !important;
  color: var(--color-primary, #6366f1) !important;
  line-height: 1.2;
}
.brief-content .stat-label {
  font-size: 0.7rem !important;
  color: var(--color-ink-tertiary, #888) !important;
  margin-top: 4px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* 区块标题 */
.brief-content .section {
  margin-bottom: 2rem;
}
.brief-content .section-title {
  font-size: 1rem !important;
  font-weight: 700 !important;
  color: var(--color-ink, #111) !important;
  margin-bottom: 0.75rem;
  padding-bottom: 0.5rem;
  border-bottom: 2px solid var(--color-primary, #6366f1) !important;
  display: flex;
  align-items: center;
  gap: 6px;
}

/* 推荐卡片 */
.brief-content .rec-card {
  background: var(--color-surface, #fff) !important;
  border: 1px solid var(--color-border, #e2e8f0) !important;
  border-left: 3px solid var(--color-primary, #6366f1) !important;
  border-radius: 10px !important;
  padding: 14px 16px !important;
  margin-bottom: 10px;
  transition: box-shadow 0.2s;
}
.brief-content .rec-card:hover {
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
.brief-content .rec-title {
  font-weight: 600 !important;
  font-size: 0.85rem !important;
  color: var(--color-ink, #111) !important;
  line-height: 1.4;
}
.brief-content .rec-meta {
  font-size: 0.7rem !important;
  color: var(--color-ink-tertiary, #999) !important;
  margin-top: 4px;
}
.brief-content .rec-reason {
  font-size: 0.8rem !important;
  color: var(--color-ink-secondary, #666) !important;
  margin-top: 6px;
  line-height: 1.5;
}

/* 关键词标签 */
.brief-content .kw-tag {
  display: inline-flex !important;
  align-items: center;
  background: var(--color-primary, #6366f1) !important;
  background: color-mix(in srgb, var(--color-primary, #6366f1) 12%, transparent) !important;
  color: var(--color-primary, #6366f1) !important;
  border-radius: 9999px !important;
  padding: 4px 12px !important;
  font-size: 0.72rem !important;
  font-weight: 500 !important;
  margin: 3px !important;
  border: 1px solid color-mix(in srgb, var(--color-primary, #6366f1) 20%, transparent);
}

/* 论文卡片 */
.brief-content .paper-item {
  background: var(--color-surface, #fff) !important;
  border: 1px solid var(--color-border, #e2e8f0) !important;
  border-radius: 10px !important;
  padding: 14px 16px !important;
  margin-bottom: 8px;
  transition: border-color 0.2s;
}
.brief-content .paper-item:hover {
  border-color: color-mix(in srgb, var(--color-primary, #6366f1) 40%, var(--color-border, #e2e8f0));
}
.brief-content .paper-title {
  font-weight: 600 !important;
  font-size: 0.85rem !important;
  color: var(--color-ink, #111) !important;
  line-height: 1.4;
}
.brief-content .paper-id {
  font-size: 0.65rem !important;
  color: var(--color-ink-tertiary, #aaa) !important;
  margin-top: 3px;
  font-family: ui-monospace, monospace !important;
}
.brief-content .paper-summary {
  font-size: 0.8rem !important;
  color: var(--color-ink-secondary, #555) !important;
  margin-top: 8px !important;
  line-height: 1.6;
  white-space: pre-wrap;
}

/* 主题分组 */
.brief-content .topic-group {
  margin-bottom: 1.5rem;
}
.brief-content .topic-name {
  font-size: 0.85rem !important;
  font-weight: 700 !important;
  color: var(--color-primary, #6366f1) !important;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.brief-content .topic-name::before {
  content: "";
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-primary, #6366f1);
}

/* 页脚 */
.brief-content .footer {
  text-align: center;
  color: var(--color-ink-tertiary, #aaa) !important;
  font-size: 0.7rem !important;
  margin-top: 2.5rem;
  padding-top: 1rem;
  border-top: 1px solid var(--color-border, #e2e8f0) !important;
}

/* Deep read cards */
.brief-content .deep-card {
  background: linear-gradient(135deg, color-mix(in srgb, var(--color-primary) 5%, var(--color-surface)) 0%, color-mix(in srgb, var(--color-primary) 10%, var(--color-surface)) 100%) !important;
  border: 1px solid color-mix(in srgb, var(--color-primary) 30%, var(--color-border)) !important;
  border-left: 4px solid var(--color-primary) !important;
  border-radius: 12px !important;
  padding: 18px !important;
  margin-bottom: 14px;
  transition: box-shadow 0.2s;
}
.brief-content .deep-card:hover {
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.12);
}
.brief-content .deep-title {
  font-weight: 700 !important;
  font-size: 0.9rem !important;
  color: var(--color-ink) !important;
}
.brief-content .deep-section {
  margin-top: 10px !important;
}
.brief-content .deep-section-label {
  font-size: 0.7rem !important;
  font-weight: 600 !important;
  color: var(--color-primary) !important;
  margin-bottom: 4px !important;
}
.brief-content .deep-text {
  font-size: 0.8rem !important;
  color: var(--color-ink-secondary) !important;
  line-height: 1.6;
  margin: 0 !important;
}
.brief-content .risk-list {
  margin: 4px 0 0 16px !important;
  padding: 0 !important;
  font-size: 0.72rem !important;
  color: #b45309 !important;
}
.brief-content .risk-list li {
  margin-bottom: 2px;
}

/* Score badges */
.brief-content .score-badge {
  font-weight: 700 !important;
  border-radius: 9999px !important;
  white-space: nowrap;
}
.brief-content .score-sm {
  font-size: 0.65rem !important;
  padding: 1px 6px !important;
}
.brief-content .score-high {
  background: #dcfce7 !important;
  color: #15803d !important;
}
.brief-content .score-mid {
  background: #fef3c7 !important;
  color: #b45309 !important;
}
.brief-content .score-low {
  background: #fee2e2 !important;
  color: #dc2626 !important;
}

/* Innovation tags */
.brief-content .innovation-tags {
  display: flex !important;
  flex-wrap: wrap !important;
  gap: 4px !important;
  margin-top: 6px !important;
}
.brief-content .innovation-tag {
  display: inline-block !important;
  background: color-mix(in srgb, #f59e0b 12%, transparent) !important;
  color: #92400e !important;
  border-radius: 6px !important;
  padding: 3px 8px !important;
  font-size: 0.68rem !important;
}

/* Deep badge */
.brief-content .deep-badge {
  background: color-mix(in srgb, var(--color-primary) 15%, transparent) !important;
  color: var(--color-primary) !important;
  padding: 1px 6px !important;
  border-radius: 4px !important;
  font-size: 0.6rem !important;
  font-weight: 600 !important;
}

/* Paper header */
.brief-content .paper-header {
  display: flex !important;
  align-items: flex-start !important;
  justify-content: space-between !important;
  gap: 8px !important;
}

/* 暗色模式 */
:root.dark .brief-content,
.dark .brief-content {
  color: var(--color-ink, #e2e8f0);
}
.dark .brief-content .stat-card {
  background: var(--color-surface, #1e1e2e) !important;
  border-color: var(--color-border, #333) !important;
}
.dark .brief-content .rec-card {
  background: var(--color-surface, #1e1e2e) !important;
  border-color: var(--color-border, #333) !important;
}
.dark .brief-content .paper-item {
  background: var(--color-surface, #1e1e2e) !important;
  border-color: var(--color-border, #333) !important;
}
.dark .brief-content .rec-card:hover,
.dark .brief-content .paper-item:hover,
.dark .brief-content .deep-card:hover {
  box-shadow: 0 2px 8px rgba(0,0,0,0.3);
}
.dark .brief-content .deep-card {
  background: linear-gradient(135deg, color-mix(in srgb, var(--color-primary) 8%, var(--color-surface)) 0%, color-mix(in srgb, var(--color-primary) 12%, var(--color-surface)) 100%) !important;
  border-color: color-mix(in srgb, var(--color-primary) 30%, var(--color-border)) !important;
}
.dark .brief-content .deep-card:hover {
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.2);
}
.dark .brief-content .innovation-tag {
  background: color-mix(in srgb, #f59e0b 15%, transparent) !important;
  color: #fbbf24 !important;
}
.dark .brief-content .score-high {
  background: #052e16 !important;
  color: #4ade80 !important;
}
.dark .brief-content .score-mid {
  background: #451a03 !important;
  color: #fbbf24 !important;
}
.dark .brief-content .score-low {
  background: #450a0a !important;
  color: #f87171 !important;
}
.dark .brief-content .risk-list {
  color: #fbbf24 !important;
}
`;
