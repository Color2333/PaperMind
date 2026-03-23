/**
 * Daily Brief - 研究简报（重构：清晰排版 + 暗色适配 + 阅读体验优化）
 * @author Color2333
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
  Newspaper,
  Send,
  CheckCircle2,
  Mail,
  FileText,
  Calendar,
  Clock,
  Trash2,
  ChevronRight,
  Sparkles,
  Plus,
  RefreshCw,
  X,
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
    try {
      const res = await generatedApi.list("daily_brief", 50);
      setHistory(res.items);
    } catch {
      toast("error", "加载历史简报失败");
    } finally {
      setHistoryLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

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
    setLoading(true);
    setError(null);
    setGenDone(false);
    setTaskProgress("正在提交任务...");
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
            if (status.status === "completed") {
              resolve();
              return;
            }
            if (status.status === "failed") {
              reject(new Error(status.error || "生成失败"));
              return;
            }
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
    setDetailLoading(true);
    setSelectedContent(null);
    try {
      setSelectedContent(await generatedApi.detail(item.id));
    } catch {
      toast("error", "加载简报内容失败");
    } finally {
      setDetailLoading(false);
    }
  };

  const handleDelete = async (id: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    try {
      await generatedApi.delete(id);
      setHistory((p) => p.filter((h) => h.id !== id));
      if (selectedContent?.id === id) setSelectedContent(null);
    } catch {
      toast("error", "删除简报失败");
    }
  };

  const fmtDate = (iso: string) => {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    const isYesterday = d.toDateString() === yesterday.toDateString();
    if (isToday)
      return `今天 ${d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`;
    if (isYesterday)
      return `昨天 ${d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`;
    return (
      d.toLocaleDateString("zh-CN", { month: "short", day: "numeric" }) +
      " " +
      d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })
    );
  };

  return (
    <div className="animate-fade-in flex h-full flex-col">
      {/* 顶栏 */}
      <div className="border-border flex shrink-0 items-center justify-between border-b px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="bg-primary/10 rounded-xl p-2">
            <Newspaper className="text-primary h-5 w-5" />
          </div>
          <div>
            <h1 className="text-ink text-lg font-bold">研究简报</h1>
            <p className="text-ink-tertiary text-xs">自动汇总最新研究进展</p>
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
        <div className="border-border bg-surface/50 shrink-0 border-b px-6 py-4">
          <div className="flex flex-wrap items-end gap-4">
            <div className="space-y-1">
              <label className="text-ink-secondary flex items-center gap-1 text-[11px] font-medium">
                <Calendar className="h-3 w-3" /> 日期
              </label>
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="border-border bg-page text-ink focus:border-primary h-9 rounded-lg border px-3 text-xs focus:outline-none"
              />
            </div>
            <div className="space-y-1">
              <label className="text-ink-secondary flex items-center gap-1 text-[11px] font-medium">
                <Mail className="h-3 w-3" /> 邮件通知
              </label>
              <input
                type="email"
                value={recipient}
                onChange={(e) => setRecipient(e.target.value)}
                placeholder="可选"
                className="border-border bg-page text-ink placeholder:text-ink-placeholder focus:border-primary h-9 w-48 rounded-lg border px-3 text-xs focus:outline-none"
              />
            </div>
            <Button
              icon={
                loading ? (
                  <RefreshCw className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )
              }
              onClick={handleGenerate}
              loading={loading}
            >
              生成
            </Button>
          </div>
          {error && <p className="text-error mt-2 text-xs">{error}</p>}
          {taskProgress && !error && (
            <p className="text-ink-secondary mt-2 flex items-center gap-1.5 text-xs">
              <RefreshCw className="h-3 w-3 animate-spin" />
              {taskProgress}
            </p>
          )}
          {genDone && !loading && (
            <div className="mt-2 flex items-center gap-2">
              <CheckCircle2 className="text-success h-3.5 w-3.5" />
              <span className="text-success text-xs">生成成功</span>
            </div>
          )}
        </div>
      )}

      {/* 主体：左侧列表 + 右侧内容 */}
      <div className="flex min-h-0 flex-1">
        {/* 左侧历史列表 */}
        <div className="border-border bg-page/30 w-56 shrink-0 overflow-y-auto border-r lg:w-64">
          <div className="px-3 pt-3 pb-2">
            <p className="text-ink-tertiary text-[10px] font-semibold tracking-wider uppercase">
              历史简报 ({history.length})
            </p>
          </div>
          {historyLoading ? (
            <div className="p-4">
              <Spinner text="" />
            </div>
          ) : history.length === 0 ? (
            <div className="text-ink-tertiary px-3 py-8 text-center text-xs">
              <Newspaper className="text-ink-tertiary/20 mx-auto mb-2 h-8 w-8" />
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
                    onKeyDown={(e) => {
                      if (e.key === "Enter") handleView(item);
                    }}
                    className={`group flex w-full cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-all ${
                      active ? "bg-primary/10 text-primary" : "text-ink hover:bg-surface"
                    }`}
                  >
                    <FileText
                      className={`h-3.5 w-3.5 shrink-0 ${active ? "text-primary" : "text-ink-tertiary"}`}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-medium">
                        {item.title.replace("Daily Brief: ", "")}
                      </p>
                      <p className="text-ink-tertiary mt-0.5 text-[10px]">
                        {fmtDate(item.created_at)}
                      </p>
                    </div>
                    <button
                      aria-label="删除"
                      onClick={(e) => {
                        e.stopPropagation();
                        setConfirmDeleteId(item.id);
                      }}
                      className="text-ink-tertiary hover:text-error shrink-0 rounded p-0.5 opacity-0 transition-opacity group-hover:opacity-100"
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
              <div className="border-border border-b px-8 py-5">
                <h2 className="text-ink text-xl font-bold">{selectedContent.title}</h2>
                <p className="text-ink-tertiary mt-1 text-xs">
                  <Clock className="mr-1 inline h-3 w-3" />
                  {new Date(selectedContent.created_at).toLocaleString("zh-CN", {
                    timeZone: "Asia/Shanghai",
                  })}
                </p>
              </div>

              {/* 简报正文 */}
              <div className="px-8 py-6">
                <div
                  ref={briefRef}
                  className="brief-content"
                  dangerouslySetInnerHTML={{
                    __html: DOMPurify.sanitize(selectedContent.markdown, {
                      ADD_ATTR: ["data-paper-id", "data-arxiv-id"],
                    }),
                  }}
                />
              </div>
            </div>
          )}

          {!detailLoading && !selectedContent && (
            <div className="text-ink-tertiary flex h-full flex-col items-center justify-center">
              <div className="bg-page rounded-2xl p-6">
                <Sparkles className="text-ink-tertiary/20 h-10 w-10" />
              </div>
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
        onConfirm={async () => {
          if (confirmDeleteId) {
            await handleDelete(confirmDeleteId);
            setConfirmDeleteId(null);
          }
        }}
        onCancel={() => setConfirmDeleteId(null)}
      />
    </div>
  );
}

/**
 * 覆盖后端生成的 HTML 简报样式，适配 app 主题 + 暗色模式 + 增强视觉层次
 */
const briefContentStyles = `
.brief-content {
  max-width: 800px;
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

/* 标题增强 */
.brief-content h1 {
  font-size: 1.75rem;
  font-weight: 900;
  margin-bottom: 8px;
  background: linear-gradient(135deg, var(--color-primary) 0%, var(--color-primary) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.brief-content .subtitle {
  font-size: 0.85rem;
  color: var(--color-ink-tertiary, #888);
  margin-bottom: 2rem;
  display: flex;
  align-items: center;
  gap: 6px;
}
.brief-content .subtitle::before {
  content: "📅";
}

/* 统计卡片增强 */
.brief-content .stats {
  display: grid !important;
  grid-template-columns: repeat(4, 1fr) !important;
  gap: 16px !important;
  margin-bottom: 2.5rem;
}
.brief-content .stat-card {
  background: linear-gradient(135deg, var(--color-surface) 0%, color-mix(in srgb, var(--color-primary) 3%, var(--color-surface)) 100%) !important;
  border: 1px solid var(--color-border, #e2e8f0) !important;
  border-radius: 14px !important;
  padding: 20px !important;
  text-align: center;
  transition: transform 0.2s, box-shadow 0.2s;
}
.brief-content .stat-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 20px color-mix(in srgb, var(--color-primary) 15%, transparent);
}
.brief-content .stat-num {
  font-size: 2.25rem !important;
  font-weight: 900 !important;
  background: linear-gradient(135deg, var(--color-primary) 0%, color-mix(in srgb, var(--color-primary) 80%, black) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  line-height: 1.2;
}
.brief-content .stat-label {
  font-size: 0.7rem !important;
  color: var(--color-ink-tertiary, #888) !important;
  margin-top: 8px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-weight: 700;
}

/* 焦点区域 - 最高优先级 */
.brief-content .focus-zone {
  background: linear-gradient(135deg, color-mix(in srgb, var(--color-success) 8%, var(--color-surface)) 0%, color-mix(in srgb, var(--color-success) 12%, var(--color-surface)) 100%) !important;
  border: 2px solid var(--color-success, #22c55e) !important;
  border-radius: 18px !important;
  padding: 24px !important;
  margin-bottom: 36px !important;
}
.brief-content .focus-title {
  font-size: 1.25rem !important;
  font-weight: 900 !important;
  color: color-mix(in srgb, var(--color-success) 80%, black) !important;
  margin-bottom: 20px !important;
  display: flex;
  align-items: center;
  gap: 10px;
}
.brief-content .focus-title::before {
  content: "🎯";
  font-size: 1.5rem;
}

/* AI 洞察盒子增强 */
.brief-content .ai-insight-box {
  background: var(--color-surface) !important;
  border-radius: 14px !important;
  padding: 20px !important;
  border-left: 5px solid var(--color-success, #22c55e) !important;
  box-shadow: 0 4px 12px color-mix(in srgb, var(--color-success) 10%, transparent);
}
.brief-content .ai-insight-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.brief-content .ai-insight-icon {
  font-size: 1.5rem;
}
.brief-content .ai-insight-title {
  font-weight: 800 !important;
  color: color-mix(in srgb, var(--color-success) 80%, black) !important;
  font-size: 1rem !important;
}
.brief-content .ai-insight-content {
  font-size: 0.9rem;
  line-height: 1.9;
  color: var(--color-ink-secondary, #4b5563);
}

/* 区块标题增强 */
.brief-content .section {
  margin-bottom: 2.5rem;
}
.brief-content .section-title {
  font-size: 1.1rem !important;
  font-weight: 800 !important;
  color: var(--color-ink, #111) !important;
  margin-bottom: 1rem;
  padding-bottom: 10px;
  border-bottom: 2px solid var(--color-border, #e2e8f0) !important;
  display: flex;
  align-items: center;
  gap: 10px;
}
.brief-content .section-title::before {
  content: "";
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 3px;
  background: linear-gradient(135deg, var(--color-primary) 0%, color-mix(in srgb, var(--color-primary) 70%, black) 100%);
}

/* 推荐卡片增强 */
.brief-content .rec-card {
  background: linear-gradient(135deg, color-mix(in srgb, var(--color-primary) 8%, var(--color-surface)) 0%, color-mix(in srgb, var(--color-primary) 12%, var(--color-surface)) 100%) !important;
  border: 2px solid color-mix(in srgb, var(--color-primary) 30%, var(--color-border)) !important;
  border-left: 4px solid var(--color-primary) !important;
  border-radius: 14px !important;
  padding: 18px !important;
  margin-bottom: 14px;
  transition: all 0.2s;
  cursor: pointer;
}
.brief-content .rec-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px color-mix(in srgb, var(--color-primary) 20%, transparent);
  border-color: var(--color-primary);
}
.brief-content .rec-title {
  font-weight: 700 !important;
  font-size: 0.95rem !important;
  color: var(--color-ink, #111) !important;
  line-height: 1.5;
}
.brief-content .rec-meta {
  font-size: 0.75rem !important;
  color: var(--color-ink-tertiary, #6b7280) !important;
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.brief-content .rec-reason {
  font-size: 0.85rem !important;
  color: var(--color-ink-secondary, #4b5563) !important;
  margin-top: 10px;
  line-height: 1.7;
  font-style: italic;
}

/* 关键词标签增强 */
.brief-content .kw-tag {
  display: inline-flex !important;
  align-items: center;
  gap: 5px;
  background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%) !important;
  color: #92400e !important;
  border-radius: 9999px !important;
  padding: 7px 14px !important;
  font-size: 0.8rem !important;
  font-weight: 700 !important;
  margin: 5px !important;
  border: 2px solid #f59e0b !important;
  transition: transform 0.2s;
}
.brief-content .kw-tag:hover {
  transform: scale(1.08);
}
.brief-content .kw-tag::before {
  content: "🔥";
  font-size: 0.9rem;
}

/* 主题分组增强 */
.brief-content .topic-group {
  margin-bottom: 28px;
  background: var(--color-surface) !important;
  border-radius: 14px !important;
  padding: 18px !important;
  border: 1px solid var(--color-border, #e2e8f0) !important;
}
.brief-content .topic-name {
  font-size: 0.95rem !important;
  font-weight: 800 !important;
  color: var(--color-primary, #6366f1) !important;
  margin-bottom: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 10px;
  border-bottom: 1px dashed var(--color-border, #e2e8f0) !important;
}
.brief-content .topic-name::before {
  content: "📁";
  font-size: 1rem;
}

/* 论文卡片增强 */
.brief-content .paper-item {
  background: var(--color-surface, #fff) !important;
  border: 1.5px solid var(--color-border, #e2e8f0) !important;
  border-radius: 12px !important;
  padding: 16px !important;
  margin-bottom: 12px;
  transition: all 0.2s;
  cursor: pointer;
}
.brief-content .paper-item:hover {
  border-color: color-mix(in srgb, var(--color-primary) 50%, var(--color-border));
  box-shadow: 0 4px 12px color-mix(in srgb, var(--color-primary) 10%, transparent);
  transform: translateY(-2px);
}
.brief-content .paper-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.brief-content .paper-title {
  font-weight: 700 !important;
  font-size: 0.9rem !important;
  color: var(--color-ink, #111) !important;
  line-height: 1.5;
}
.brief-content .paper-id {
  font-size: 0.7rem !important;
  color: var(--color-ink-tertiary, #9ca3af) !important;
  font-family: ui-monospace, monospace !important;
  margin-bottom: 8px;
}
.brief-content .paper-summary {
  font-size: 0.85rem !important;
  color: var(--color-ink-secondary, #6b7280) !important;
  margin-top: 10px !important;
  line-height: 1.7;
  max-height: 65px;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  transition: max-height 0.3s;
}
.brief-content .paper-item:hover .paper-summary {
  max-height: 300px;
}

/* Deep read cards 增强 */
.brief-content .deep-card {
  background: linear-gradient(135deg, color-mix(in srgb, var(--color-primary) 10%, var(--color-surface)) 0%, color-mix(in srgb, var(--color-primary) 15%, var(--color-surface)) 100%) !important;
  border: 2px solid color-mix(in srgb, var(--color-primary) 40%, var(--color-border)) !important;
  border-left: 5px solid var(--color-primary) !important;
  border-radius: 16px !important;
  padding: 20px !important;
  margin-bottom: 18px;
  transition: all 0.2s;
  cursor: pointer;
}
.brief-content .deep-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 20px color-mix(in srgb, var(--color-primary) 20%, transparent);
  border-color: var(--color-primary);
}
.brief-content .deep-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 14px;
}
.brief-content .deep-title {
  font-weight: 800 !important;
  font-size: 1rem !important;
  color: var(--color-ink) !important;
  line-height: 1.4;
}
.brief-content .deep-section {
  margin-top: 14px !important;
}
.brief-content .deep-section-label {
  font-size: 0.7rem !important;
  font-weight: 800 !important;
  color: var(--color-primary) !important;
  margin-bottom: 6px !important;
  display: flex;
  align-items: center;
  gap: 4px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.brief-content .deep-text {
  font-size: 0.85rem !important;
  color: var(--color-ink-secondary) !important;
  line-height: 1.7;
  margin: 0 !important;
}
.brief-content .risk-list {
  margin: 8px 0 0 20px !important;
  padding: 0 !important;
  font-size: 0.75rem !important;
  color: color-mix(in srgb, #f59e0b 80%, black) !important;
}
.brief-content .risk-list li {
  margin-bottom: 5px;
  line-height: 1.5;
}

/* 分数徽章增强 */
.brief-content .score-badge {
  display: inline-flex !important;
  align-items: center;
  justify-content: center;
  border-radius: 9999px !important;
  font-weight: 800 !important;
  font-size: 0.7rem !important;
  padding: 4px 10px !important;
  min-width: 52px;
  border: 1.5px solid transparent;
}
.brief-content .score-high {
  background: linear-gradient(135deg, #dcfce7 0%, #bbf7d0 100%) !important;
  color: #166534 !important;
  border-color: #22c55e !important;
}
.brief-content .score-mid {
  background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%) !important;
  color: #92400e !important;
  border-color: #f59e0b !important;
}
.brief-content .score-low {
  background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%) !important;
  color: #991b1b !important;
  border-color: #ef4444 !important;
}

/* Deep badge 增强 */
.brief-content .deep-badge {
  display: inline-flex !important;
  align-items: center;
  gap: 3px;
  background: linear-gradient(135deg, #ede9fe 0%, #ddd6fe 100%) !important;
  color: #6d28d9 !important;
  padding: 3px 10px !important;
  border-radius: 8px !important;
  font-size: 0.65rem !important;
  font-weight: 800 !important;
  border: 1.5px solid #a855f7 !important;
}
.brief-content .deep-badge::before {
  content: "✨";
  font-size: 0.7rem;
}

/* 创新标签增强 */
.brief-content .innovation-tags {
  display: flex !important;
  flex-wrap: wrap !important;
  gap: 8px !important;
  margin-top: 10px !important;
}
.brief-content .innovation-tag {
  display: inline-flex !important;
  align-items: center;
  gap: 4px;
  background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%) !important;
  color: #78350f !important;
  border-radius: 10px !important;
  padding: 5px 12px !important;
  font-size: 0.7rem !important;
  font-weight: 700 !important;
  border: 1.5px solid #f59e0b !important;
}
.brief-content .innovation-tag::before {
  content: "💡";
  font-size: 0.8rem;
}

/* 按钮增强 */
.brief-content .btn {
  display: inline-block !important;
  padding: 9px 18px !important;
  background: linear-gradient(135deg, var(--color-primary) 0%, color-mix(in srgb, var(--color-primary) 80%, black) 100%) !important;
  color: #fff !important;
  text-decoration: none !important;
  border-radius: 10px !important;
  font-size: 0.75rem !important;
  font-weight: 700 !important;
  margin-top: 10px !important;
  transition: all 0.2s;
  border: none;
  cursor: pointer;
}
.brief-content .btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px color-mix(in srgb, var(--color-primary) 30%, transparent);
}

/* 页脚 */
.brief-content .footer {
  text-align: center;
  color: var(--color-ink-tertiary, #9ca3af) !important;
  font-size: 0.75rem !important;
  margin-top: 56px;
  padding-top: 24px;
  border-top: 2px solid var(--color-border, #e2e8f0) !important;
}
.brief-content .footer a {
  color: var(--color-primary) !important;
  text-decoration: none;
  font-weight: 700;
}
.brief-content .footer a:hover {
  text-decoration: underline;
}

/* 暗色模式增强 */
:root.dark .brief-content,
.dark .brief-content {
  color: var(--color-ink, #e2e8f0);
}
.dark .brief-content .stat-card {
  background: linear-gradient(135deg, var(--color-surface, #1e1e2e) 0%, color-mix(in srgb, var(--color-primary) 8%, var(--color-surface)) 100%) !important;
  border-color: var(--color-border, #333) !important;
}
.dark .brief-content .focus-zone {
  background: linear-gradient(135deg, color-mix(in srgb, var(--color-success) 12%, var(--color-surface)) 0%, color-mix(in srgb, var(--color-success) 18%, var(--color-surface)) 100%) !important;
  border-color: color-mix(in srgb, var(--color-success) 60%, var(--color-border)) !important;
}
.dark .brief-content .ai-insight-box,
.dark .brief-content .rec-card,
.dark .brief-content .paper-item,
.dark .brief-content .topic-group {
  background: var(--color-surface, #1e1e2e) !important;
  border-color: var(--color-border, #333) !important;
}
.dark .brief-content .deep-card {
  background: linear-gradient(135deg, color-mix(in srgb, var(--color-primary) 15%, var(--color-surface)) 0%, color-mix(in srgb, var(--color-primary) 22%, var(--color-surface)) 100%) !important;
  border-color: color-mix(in srgb, var(--color-primary) 50%, var(--color-border)) !important;
}
.dark .brief-content .kw-tag {
  background: linear-gradient(135deg, color-mix(in srgb, #f59e0b 20%, transparent) 0%, color-mix(in srgb, #f59e0b 30%, transparent) 100%) !important;
  color: #fbbf24 !important;
  border-color: #f59e0b !important;
}
.dark .brief-content .innovation-tag {
  background: linear-gradient(135deg, color-mix(in srgb, #f59e0b 18%, transparent) 0%, color-mix(in srgb, #f59e0b 28%, transparent) 100%) !important;
  color: #fbbf24 !important;
}
.dark .brief-content .score-high {
  background: linear-gradient(135deg, #052e16 0%, #064e3b 100%) !important;
  color: #4ade80 !important;
  border-color: #22c55e !important;
}
.dark .brief-content .score-mid {
  background: linear-gradient(135deg, #451a03 0%, #78350f 100%) !important;
  color: #fbbf24 !important;
  border-color: #f59e0b !important;
}
.dark .brief-content .score-low {
  background: linear-gradient(135deg, #450a0a 0%, #7f1d1d 100%) !important;
  color: #f87171 !important;
  border-color: #ef4444 !important;
}
.dark .brief-content .deep-badge {
  background: linear-gradient(135deg, color-mix(in srgb, var(--color-primary) 20%, transparent) 0%, color-mix(in srgb, var(--color-primary) 30%, transparent) 100%) !important;
  color: #c4b5fd !important;
  border-color: #a855f7 !important;
}
.dark .brief-content .risk-list {
  color: #fbbf24 !important;
}
.dark .brief-content .rec-card:hover,
.dark .brief-content .paper-item:hover,
.dark .brief-content .deep-card:hover,
.dark .brief-content .stat-card:hover {
  box-shadow: 0 6px 20px rgba(0,0,0,0.4);
}
`;
