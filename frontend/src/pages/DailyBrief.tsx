/**
 * Daily Brief - 研究简报（现代精致版）
 * @author Bamzc
 */
import { useState, useEffect, useCallback } from "react";
import { Button, Spinner, Empty } from "@/components/ui";
import { briefApi, generatedApi } from "@/services/api";
import type { DailyBriefResponse, GeneratedContentListItem, GeneratedContent } from "@/types";
import {
  Newspaper, Send, CheckCircle2, Mail, FileText, Calendar, Clock,
  Trash2, ChevronRight, Eye, Sparkles,
} from "lucide-react";

export default function DailyBrief() {
  const [date, setDate] = useState("");
  const [recipient, setRecipient] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<DailyBriefResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [history, setHistory] = useState<GeneratedContentListItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [selectedContent, setSelectedContent] = useState<GeneratedContent | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try { const res = await generatedApi.list("daily_brief", 50); setHistory(res.items); }
    catch {} finally { setHistoryLoading(false); }
  }, []);

  useEffect(() => { loadHistory(); }, [loadHistory]);

  const handleGenerate = async () => {
    setLoading(true); setError(null); setResult(null); setSelectedContent(null);
    try {
      const data: Record<string, string> = {};
      if (date) data.date = date;
      if (recipient) data.recipient = recipient;
      const res = await briefApi.daily(Object.keys(data).length > 0 ? data : undefined);
      setResult(res); loadHistory();
    } catch (err) { setError(err instanceof Error ? err.message : "生成失败"); }
    finally { setLoading(false); }
  };

  const handleView = async (item: GeneratedContentListItem) => {
    setDetailLoading(true); setResult(null);
    try { setSelectedContent(await generatedApi.detail(item.id)); }
    catch {} finally { setDetailLoading(false); }
  };

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try { await generatedApi.delete(id); setHistory((p) => p.filter((h) => h.id !== id)); if (selectedContent?.id === id) setSelectedContent(null); }
    catch {}
  };

  const fmtTime = (iso: string) => {
    const d = new Date(iso);
    return isNaN(d.getTime()) ? iso : d.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Shanghai" });
  };

  return (
    <div className="animate-fade-in space-y-6">
      {/* 页面头 */}
      <div className="page-hero rounded-2xl p-6">
        <div className="flex items-center gap-3">
          <div className="rounded-xl bg-primary/10 p-2.5"><Newspaper className="h-5 w-5 text-primary" /></div>
          <div>
            <h1 className="text-2xl font-bold text-ink">研究简报</h1>
            <p className="mt-0.5 text-sm text-ink-secondary">自动汇总最新研究进展，历史简报自动保存</p>
          </div>
        </div>
      </div>

      {/* 生成区 */}
      <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm">
        <div className="mb-4 flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-warning" />
          <h3 className="text-sm font-semibold text-ink">生成简报</h3>
        </div>
        <div className="flex flex-wrap items-end gap-4">
          <div className="space-y-1.5">
            <label className="flex items-center gap-1 text-xs font-medium text-ink-secondary">
              <Calendar className="h-3 w-3" /> 日期（可选）
            </label>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="form-input w-44" />
          </div>
          <div className="space-y-1.5">
            <label className="flex items-center gap-1 text-xs font-medium text-ink-secondary">
              <Mail className="h-3 w-3" /> 收件人（可选）
            </label>
            <input type="email" value={recipient} onChange={(e) => setRecipient(e.target.value)} placeholder="user@example.com" className="form-input w-56" />
          </div>
          <Button icon={<Send className="h-4 w-4" />} onClick={handleGenerate} loading={loading}>
            生成简报
          </Button>
        </div>

        {error && (
          <div className="mt-4 rounded-xl border border-error/20 bg-error-light px-4 py-3 text-sm text-error">{error}</div>
        )}

        {result && (
          <div className="mt-4 space-y-2">
            <div className="flex items-center gap-2 rounded-xl bg-success-light px-4 py-3">
              <CheckCircle2 className="h-4 w-4 text-success" />
              <span className="text-sm font-medium text-success">简报生成成功</span>
            </div>
            <div className="flex gap-4 text-xs text-ink-tertiary">
              <span className="flex items-center gap-1"><FileText className="h-3 w-3" />{result.saved_path}</span>
              <span className="flex items-center gap-1"><Mail className="h-3 w-3" />{result.email_sent ? "已发送" : "未发送"}</span>
            </div>
          </div>
        )}
      </div>

      {/* 双栏 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        {/* 历史列表 */}
        <div className="lg:col-span-1">
          <div className="rounded-2xl border border-border bg-surface p-4 shadow-sm">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-ink">历史简报</h3>
              <span className="rounded-full bg-page px-2 py-0.5 text-[10px] font-medium text-ink-tertiary">{history.length}</span>
            </div>
            {historyLoading ? (
              <Spinner text="加载中..." />
            ) : history.length === 0 ? (
              <Empty title="暂无历史" className="py-8" />
            ) : (
              <div className="max-h-[60vh] space-y-0.5 overflow-y-auto">
                {history.map((item) => (
                  <button
                    key={item.id}
                    onClick={() => handleView(item)}
                    className={`group flex w-full items-center justify-between rounded-xl px-3 py-2.5 text-left transition-colors ${
                      selectedContent?.id === item.id
                        ? "bg-primary/8 text-primary"
                        : "text-ink hover:bg-hover"
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{item.title}</p>
                      <div className="mt-0.5 flex items-center gap-1 text-[10px] text-ink-tertiary">
                        <Clock className="h-2.5 w-2.5" />{fmtTime(item.created_at)}
                      </div>
                    </div>
                    <div className="flex items-center gap-0.5">
                      <button
                        onClick={(e) => handleDelete(item.id, e)}
                        className="rounded p-1 text-ink-tertiary opacity-0 transition-opacity hover:text-error group-hover:opacity-100"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                      <ChevronRight className="h-3.5 w-3.5 text-ink-tertiary" />
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* 内容预览 */}
        <div className="lg:col-span-3">
          {detailLoading && <Spinner text="加载内容..." />}

          {!detailLoading && selectedContent && (
            <div className="animate-fade-in rounded-2xl border border-border bg-surface p-6 shadow-sm">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <h3 className="text-base font-semibold text-ink">{selectedContent.title}</h3>
                  <p className="text-xs text-ink-tertiary">{new Date(selectedContent.created_at).toLocaleString("zh-CN")}</p>
                </div>
                <Eye className="h-5 w-5 text-primary" />
              </div>
              <div
                className="brief-html-preview prose-custom rounded-xl border border-border bg-white p-5 dark:bg-surface"
                dangerouslySetInnerHTML={{ __html: selectedContent.markdown }}
              />
            </div>
          )}

          {!detailLoading && !selectedContent && !result && (
            <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border py-20">
              <div className="rounded-2xl bg-page p-6">
                <Newspaper className="h-10 w-10 text-ink-tertiary/30" />
              </div>
              <p className="mt-4 text-sm text-ink-tertiary">生成新的简报，或从左侧选择历史查看</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
