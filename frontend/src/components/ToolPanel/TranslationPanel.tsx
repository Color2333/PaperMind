import { useState, useCallback } from 'react';
import { Loader2, Copy, Check, Languages, FileText } from 'lucide-react';
import Markdown from '@/components/Markdown';
import { paperApi } from '@/services/api';

type AiAction = 'explain' | 'translate' | 'summarize';

interface AiResult {
  action: AiAction;
  text: string;
  result: string;
}

interface Segment {
  id: string;
  type: 'paragraph' | 'figure';
  content: string;
  translation?: string;
}

type PanelMode = 'selection' | 'paragraph';

interface TranslationPanelProps {
  selectedText: string;
  paperId: string;
}

export function TranslationPanel({ selectedText, paperId }: TranslationPanelProps) {
  const [mode, setMode] = useState<PanelMode>('selection');
  const [aiLoading, setAiLoading] = useState(false);
  const [aiResults, setAiResults] = useState<AiResult[]>([]);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [translating, setTranslating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsPdfDownload, setNeedsPdfDownload] = useState(false);

  const handleAiAction = useCallback(async (action: AiAction, text?: string) => {
    const t = text || selectedText;
    if (!t) return;
    setAiLoading(true);
    try {
      const res = await paperApi.aiExplain(paperId, t, action);
      setAiResults((prev) => [{ action, text: t.slice(0, 100), result: res.result }, ...prev]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setAiResults((prev) => [{ action, text: t.slice(0, 100), result: `错误: ${msg}` }, ...prev]);
    } finally {
      setAiLoading(false);
    }
  }, [paperId, selectedText]);

  const handleCopy = useCallback((idx: number, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedIdx(idx);
    setTimeout(() => setCopiedIdx(null), 2000);
  }, []);

  const actionLabels: Record<AiAction, { label: string }> = {
    explain: { label: '解释' },
    translate: { label: '翻译' },
    summarize: { label: '总结' },
  };

  const handleTranslateFull = useCallback(async () => {
    setMode('paragraph');
    if (segments.length > 0) {
      return;
    }

    setTranslating(true);
    setError(null);
    try {
      const token = localStorage.getItem('auth_token') || '';
      const res = await fetch(`/papers/${paperId}/segments`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setSegments(data.segments || []);
      } else if (res.status === 404) {
        const data = await res.json();
        if (data.detail?.includes('没有 PDF') || data.detail?.includes('PDF 文件不存在')) {
          setNeedsPdfDownload(true);
        }
        setError('请先下载 PDF 才能使用全文对照');
      } else {
        setError('加载分段失败，请稍后重试');
      }
    } catch (err) {
      console.error('Failed to load segments:', err);
      setError('网络错误，请检查连接');
    } finally {
      setTranslating(false);
    }
  }, [paperId, segments.length]);

  const handleDownloadPdf = async () => {
    setTranslating(true);
    setError(null);
    try {
      const token = localStorage.getItem('auth_token') || '';
      const res = await fetch(`/papers/${paperId}/download-pdf`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        setNeedsPdfDownload(false);
        setError(null);
        handleTranslateFull();
      } else {
        setError('PDF下载失败');
      }
    } catch (err) {
      console.error('Failed to download PDF:', err);
      setError('PDF下载失败');
    } finally {
      setTranslating(false);
    }
  };

  const handleTranslateSegments = useCallback(async () => {
    if (segments.length === 0) return;
    setTranslating(true);
    try {
      const token = localStorage.getItem('auth_token') || '';
      const res = await fetch('/translate/segments', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ segments, target_lang: 'zh' }),
      });
      if (res.ok) {
        const data = await res.json();
        setSegments(data.segments || []);
      }
    } catch (err) {
      console.error('Failed to translate segments:', err);
    } finally {
      setTranslating(false);
    }
  }, [segments]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex gap-2 border-b border-white/10 px-4 py-2">
        <button
          type="button"
          onClick={() => setMode('selection')}
          className={`text-xs ${mode === 'selection' ? 'text-primary' : 'text-white/40'}`}
        >
          划词翻译
        </button>
        <button
          type="button"
          onClick={handleTranslateFull}
          className={`text-xs flex items-center gap-1 ${mode === 'paragraph' ? 'text-primary' : 'text-white/40'}`}
        >
          <FileText className="h-3 w-3" />
          全文对照
        </button>
      </div>

      {mode === 'selection' ? (
        <SelectionView
          selectedText={selectedText}
          aiLoading={aiLoading}
          aiResults={aiResults}
          copiedIdx={copiedIdx}
          handleAiAction={handleAiAction}
          handleCopy={handleCopy}
          actionLabels={actionLabels}
        />
      ) : (
        <ParagraphView
          segments={segments}
          translating={translating}
          handleTranslate={handleTranslateSegments}
          handleCopy={handleCopy}
          error={error}
          needsPdfDownload={needsPdfDownload}
          handleDownloadPdf={handleDownloadPdf}
        />
      )}
    </div>
  );
}

interface SelectionViewProps {
  selectedText: string;
  aiLoading: boolean;
  aiResults: AiResult[];
  copiedIdx: number | null;
  handleAiAction: (action: AiAction, text?: string) => void;
  handleCopy: (idx: number, text: string) => void;
  actionLabels: Record<AiAction, { label: string }>;
}

function SelectionView({
  selectedText,
  aiLoading,
  aiResults,
  copiedIdx,
  handleAiAction,
  handleCopy,
  actionLabels,
}: SelectionViewProps) {
  return (
    <>
      {selectedText && (
        <div className="border-b border-white/10 px-4 py-3">
          <p className="mb-2 text-xs text-white/40">选中文本</p>
          <p className="mb-3 line-clamp-3 rounded-md bg-white/5 p-2 text-xs leading-relaxed text-white/70">
            {selectedText}
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => handleAiAction('explain')}
              disabled={aiLoading}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-amber-500/10 py-1.5 text-xs text-amber-300 hover:bg-amber-500/20 disabled:opacity-50"
            >
              解释
            </button>
            <button
              type="button"
              onClick={() => handleAiAction('translate')}
              disabled={aiLoading}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-blue-500/10 py-1.5 text-xs text-blue-300 hover:bg-blue-500/20 disabled:opacity-50"
            >
              翻译
            </button>
            <button
              type="button"
              onClick={() => handleAiAction('summarize')}
              disabled={aiLoading}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-emerald-500/10 py-1.5 text-xs text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
            >
              总结
            </button>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-auto px-4 py-3">
        {aiLoading && (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2">
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            <span className="text-xs text-primary">AI 分析中...</span>
          </div>
        )}

        {aiResults.length === 0 && !aiLoading && (
          <div className="flex flex-col items-center gap-3 pt-12 text-center">
            <Languages className="h-10 w-10 text-white/10" />
            <p className="text-sm text-white/40">选中论文文本</p>
            <p className="text-xs text-white/20">即可使用 AI 解释、翻译、总结</p>
          </div>
        )}

        {aiResults.map((r, idx) => {
          const resultKey = `${r.action}-${r.text.slice(0, 20)}`;
          return (
            <div key={resultKey} className="mb-4 overflow-hidden rounded-xl border border-white/[.08]">
              <div className="flex items-center justify-between border-b border-white/[.06] px-3.5 py-2">
                <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium ${
                  r.action === 'explain' ? 'bg-amber-500/10 text-amber-300' :
                  r.action === 'translate' ? 'bg-blue-500/10 text-blue-300' :
                  'bg-emerald-500/10 text-emerald-300'
                }`}>
                  {actionLabels[r.action].label}
                </span>
                <button
                  type="button"
                  onClick={() => handleCopy(idx, r.result)}
                  className="rounded-md p-1 text-white/20 hover:bg-white/10"
                >
                  {copiedIdx === idx ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                </button>
              </div>
              <div className="border-b border-white/[.04] px-3.5 py-2">
                <p className="line-clamp-2 border-l-2 border-white/10 pl-2.5 text-[11px] leading-relaxed text-white/30 italic">
                  {r.text}
                </p>
              </div>
              <div className="px-3.5 py-3">
                <Markdown className="pdf-ai-markdown">{r.result}</Markdown>
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}

interface ParagraphViewProps {
  segments: Segment[];
  translating: boolean;
  handleTranslate: () => void;
  handleCopy: (idx: number, text: string) => void;
  error?: string | null;
  needsPdfDownload?: boolean;
  handleDownloadPdf?: () => void;
}

function ParagraphView({ segments, translating, handleTranslate, handleCopy, error, needsPdfDownload, handleDownloadPdf }: ParagraphViewProps) {
  const allTranslated = segments.length > 0 && segments.every(s => s.translation);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-white/10 px-4 py-2">
        {segments.length === 0 ? (
          error?.includes('PDF') ? (
            <button
              type="button"
              onClick={handleDownloadPdf}
              disabled={translating}
              className="w-full rounded-lg bg-blue-500/20 py-2 text-sm text-blue-300 hover:bg-blue-500/30 disabled:opacity-50"
            >
              {translating ? '下载中...' : '📥 下载 PDF'}
            </button>
          ) : (
            <p className="text-xs text-white/40">点击上方"全文对照"加载分段</p>
          )
        ) : !allTranslated ? (
          <button
            type="button"
            onClick={handleTranslate}
            disabled={translating}
            className="w-full rounded-lg bg-primary/20 py-2 text-sm text-primary hover:bg-primary/30 disabled:opacity-50"
          >
            {translating ? '翻译中...' : '翻译全文'}
          </button>
        ) : (
          <p className="text-center text-xs text-emerald-400">翻译完成</p>
        )}
      </div>

      <div className="flex-1 overflow-auto px-4 py-3">
        {error && (
          <div className="mb-4 flex flex-col items-center gap-2 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-4 text-center">
            <p className="text-xs text-red-300">{error}</p>
            {needsPdfDownload && handleDownloadPdf ? (
              <button
                type="button"
                onClick={handleDownloadPdf}
                className="text-xs text-blue-400 underline hover:text-blue-300"
              >
                下载 PDF
              </button>
            ) : (
              <button
                type="button"
                onClick={handleTranslate}
                className="text-xs text-red-400 underline hover:text-red-300"
              >
                重试
              </button>
            )}
          </div>
        )}
        {translating && segments.length === 0 && (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2">
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            <span className="text-xs text-primary">加载分段中...</span>
          </div>
        )}

        {segments.length === 0 && !translating && (
          <div className="flex flex-col items-center gap-3 pt-12 text-center">
            <FileText className="h-10 w-10 text-white/10" />
            <p className="text-sm text-white/40">点击"全文对照"</p>
            <p className="text-xs text-white/20">加载并翻译论文段落</p>
          </div>
        )}

        {segments.map((seg, idx) => (
          <div key={seg.id || idx} className="mb-4 overflow-hidden rounded-xl border border-white/[.08]">
            <div className="flex items-center justify-between border-b border-white/[.06] px-3.5 py-2">
              <span className="text-[11px] text-white/40">
                {seg.type === 'figure' ? '图表' : `段落 ${idx + 1}`}
              </span>
              {seg.translation && (
                <button
                  type="button"
                  onClick={() => handleCopy(idx, seg.translation!)}
                  className="rounded-md p-1 text-white/20 hover:bg-white/10"
                >
                  <Copy className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            <div className="px-3.5 py-3">
              <p className="mb-2 text-xs leading-relaxed text-white/70">{seg.content}</p>
              {seg.translation && (
                <>
                  <div className="mb-2 border-t border-white/10" />
                  <p className="text-xs leading-relaxed text-primary/80">{seg.translation}</p>
                </>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
