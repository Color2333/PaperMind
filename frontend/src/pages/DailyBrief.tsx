/**
 * Daily Brief - 每日简报（含历史记录持久化）
 * 覆盖 API: POST /brief/daily, GET /generated/list, GET /generated/{id}
 * @author Bamzc
 */
import { useState, useEffect, useCallback } from "react";
import { Card, CardHeader, Button, Input, Spinner, Empty } from "@/components/ui";
import { briefApi, generatedApi } from "@/services/api";
import type { DailyBriefResponse, GeneratedContentListItem, GeneratedContent } from "@/types";
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
  Eye,
} from "lucide-react";

export default function DailyBrief() {
  const [date, setDate] = useState("");
  const [recipient, setRecipient] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<DailyBriefResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  /* 历史记录 */
  const [history, setHistory] = useState<GeneratedContentListItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [selectedContent, setSelectedContent] = useState<GeneratedContent | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const res = await generatedApi.list("daily_brief", 50);
      setHistory(res.items);
    } catch {
      /* 静默 */
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const handleGenerate = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    setSelectedContent(null);
    try {
      const data: Record<string, string> = {};
      if (date) data.date = date;
      if (recipient) data.recipient = recipient;
      const res = await briefApi.daily(Object.keys(data).length > 0 ? data : undefined);
      setResult(res);
      loadHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成失败");
    } finally {
      setLoading(false);
    }
  };

  const handleViewHistory = async (item: GeneratedContentListItem) => {
    setDetailLoading(true);
    setResult(null);
    try {
      const detail = await generatedApi.detail(item.id);
      setSelectedContent(detail);
    } catch {
      /* 静默 */
    } finally {
      setDetailLoading(false);
    }
  };

  const handleDeleteHistory = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await generatedApi.delete(id);
      setHistory((prev) => prev.filter((h) => h.id !== id));
      if (selectedContent?.id === id) setSelectedContent(null);
    } catch {
      /* 静默 */
    }
  };

  const formatTime = (iso: string) => {
    const d = new Date(iso);
    return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
  };

  return (
    <div className="animate-fade-in space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-ink">Daily Brief</h1>
        <p className="mt-1 text-sm text-ink-secondary">
          生成每日论文简报，自动汇总最新研究进展，历史简报自动保存
        </p>
      </div>

      {/* 配置 */}
      <Card>
        <CardHeader
          title="生成简报"
          description="指定日期和收件人生成每日简报"
        />
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="flex items-center gap-1.5 text-sm font-medium text-ink">
                <Calendar className="h-3.5 w-3.5" />
                日期（可选）
              </label>
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="h-10 w-full rounded-lg border border-border bg-surface px-3 text-sm text-ink focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </div>
            <Input
              label="收件人邮箱（可选）"
              placeholder="user@example.com"
              value={recipient}
              onChange={(e) => setRecipient(e.target.value)}
            />
          </div>
          <Button
            icon={<Send className="h-4 w-4" />}
            onClick={handleGenerate}
            loading={loading}
          >
            生成简报
          </Button>
        </div>
      </Card>

      {/* 错误 */}
      {error && (
        <Card className="border-error/30 bg-error-light">
          <p className="text-sm text-error">{error}</p>
        </Card>
      )}

      {/* 刚生成的结果 */}
      {result && (
        <Card className="animate-fade-in border-success/30">
          <CardHeader title="简报已生成" />
          <div className="space-y-3">
            <div className="flex items-center gap-3 rounded-lg bg-success-light px-4 py-3">
              <CheckCircle2 className="h-5 w-5 text-success" />
              <span className="text-sm font-medium text-ink">简报生成成功，已自动保存到历史记录</span>
            </div>
            <div className="flex items-center gap-3 rounded-lg bg-page px-4 py-3">
              <FileText className="h-4 w-4 text-ink-tertiary" />
              <div>
                <p className="text-xs text-ink-tertiary">保存路径</p>
                <p className="text-sm text-ink">{result.saved_path}</p>
              </div>
            </div>
            <div className="flex items-center gap-3 rounded-lg bg-page px-4 py-3">
              <Mail className="h-4 w-4 text-ink-tertiary" />
              <div>
                <p className="text-xs text-ink-tertiary">邮件发送</p>
                <p className="text-sm text-ink">
                  {result.email_sent ? "已发送" : "未发送"}
                </p>
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* 双栏：左侧历史列表 + 右侧内容预览 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        {/* 左侧历史列表 */}
        <div className="lg:col-span-1">
          <Card>
            <CardHeader
              title="历史简报"
              action={
                <span className="text-xs text-ink-tertiary">
                  {history.length} 条
                </span>
              }
            />
            {historyLoading ? (
              <Spinner text="加载中..." />
            ) : history.length === 0 ? (
              <Empty title="暂无历史简报" />
            ) : (
              <div className="max-h-[60vh] space-y-1 overflow-y-auto">
                {history.map((item) => (
                  <div
                    key={item.id}
                    onClick={() => handleViewHistory(item)}
                    className={`group flex cursor-pointer items-center justify-between rounded-lg px-3 py-2.5 transition-colors hover:bg-primary/5 ${
                      selectedContent?.id === item.id
                        ? "bg-primary/10 text-primary"
                        : "text-ink"
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">
                        {item.title}
                      </p>
                      <div className="mt-0.5 flex items-center gap-1 text-xs text-ink-tertiary">
                        <Clock className="h-3 w-3" />
                        <span>{formatTime(item.created_at)}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={(e) => handleDeleteHistory(item.id, e)}
                        className="rounded p-1 text-ink-tertiary opacity-0 transition-opacity hover:bg-error/10 hover:text-error group-hover:opacity-100"
                        title="删除"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                      <ChevronRight className="h-4 w-4 text-ink-tertiary" />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* 右侧内容预览 */}
        <div className="lg:col-span-3">
          {detailLoading && <Spinner text="加载内容..." />}

          {!detailLoading && selectedContent && (
            <Card className="animate-fade-in">
              <CardHeader
                title={selectedContent.title}
                description={`生成时间: ${new Date(selectedContent.created_at).toLocaleString("zh-CN")}`}
                action={<Eye className="h-5 w-5 text-primary" />}
              />
              <div
                className="brief-html-preview rounded-lg border border-border bg-white p-4 dark:bg-surface"
                dangerouslySetInnerHTML={{ __html: selectedContent.markdown }}
              />
            </Card>
          )}

          {!detailLoading && !selectedContent && !result && (
            <Card className="flex items-center justify-center py-16">
              <div className="text-center">
                <Newspaper className="mx-auto h-12 w-12 text-ink-tertiary/40" />
                <p className="mt-3 text-sm text-ink-tertiary">
                  生成新的简报，或从左侧选择历史记录查看
                </p>
              </div>
            </Card>
          )}
        </div>
      </div>

      {/* 说明 */}
      <Card className="bg-page">
        <div className="flex items-start gap-3">
          <Newspaper className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
          <div className="space-y-2 text-sm text-ink-secondary">
            <p>每日简报会自动汇总最新收录的论文，生成结构化的研究进展摘要。</p>
            <p>简报内容包含：</p>
            <ul className="list-inside list-disc space-y-1 text-ink-tertiary">
              <li>新收录论文概览</li>
              <li>高评分论文精选</li>
              <li>研究趋势分析</li>
              <li>推荐阅读列表</li>
            </ul>
          </div>
        </div>
      </Card>
    </div>
  );
}
