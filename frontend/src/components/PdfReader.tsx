/**
 * PDF Reader - 沉浸式论文阅读器（连续滚动 + AI 功能）
 * @author Bamzc
 */
import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { paperApi } from "@/services/api";
import Markdown from "@/components/Markdown";
import {
  X,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Minimize2,
  BookOpen,
  Languages,
  Lightbulb,
  FileText,
  Loader2,
  RotateCw,
  MessageSquareText,
  Sparkles,
  Copy,
  Check,
} from "lucide-react";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

interface PdfReaderProps {
  paperId: string;
  paperTitle: string;
  paperArxivId?: string;  // arXiv ID（用于在线链接）
  onClose: () => void;
}

type AiAction = "explain" | "translate" | "summarize";

interface AiResult {
  action: AiAction;
  text: string;
  result: string;
}

export default function PdfReader({ paperId, paperTitle, paperArxivId, onClose }: PdfReaderProps) {
  const [numPages, setNumPages] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [scale, setScale] = useState(1.2);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  /* AI 侧栏 */
  const [aiPanelOpen, setAiPanelOpen] = useState(false);
  const [selectedText, setSelectedText] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiResults, setAiResults] = useState<AiResult[]>([]);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);

  /* 页面输入 */
  const [pageInput, setPageInput] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  // 混合加载：优先本地 PDF，没有则用后端代理访问 arXiv（解决 CORS 问题）
  const pdfUrl = useMemo(() => {
    // 先尝试本地 PDF（如果有）
    return paperApi.pdfUrl(paperId, paperArxivId);
  }, [paperId, paperArxivId]);

  /**
   * PDF 加载成功
   */
  const onDocumentLoadSuccess = useCallback(({ numPages: n }: { numPages: number }) => {
    setNumPages(n);
    setLoadError(null);
  }, []);

  const onDocumentLoadError = useCallback((error: Error) => {
    setLoadError(`PDF 加载失败: ${error.message}`);
  }, []);

  /**
   * IntersectionObserver: 检测当前可见页面
   */
  useEffect(() => {
    if (numPages === 0 || !scrollRef.current) return;

    const observer = new IntersectionObserver(
      (entries) => {
        let maxRatio = 0;
        let visiblePage = currentPage;
        entries.forEach((entry) => {
          if (entry.isIntersecting && entry.intersectionRatio > maxRatio) {
            maxRatio = entry.intersectionRatio;
            const pg = Number(entry.target.getAttribute("data-page"));
            if (pg) visiblePage = pg;
          }
        });
        if (visiblePage !== currentPage) {
          setCurrentPage(visiblePage);
        }
      },
      {
        root: scrollRef.current,
        threshold: [0, 0.25, 0.5, 0.75, 1],
      },
    );

    pageRefs.current.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [numPages, currentPage]);

  /**
   * 滚动到指定页面
   */
  const scrollToPage = useCallback((p: number) => {
    const target = Math.max(1, Math.min(p, numPages));
    const el = pageRefs.current.get(target);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    setCurrentPage(target);
  }, [numPages]);

  const handlePageInputSubmit = useCallback(() => {
    const n = parseInt(pageInput);
    if (!isNaN(n)) scrollToPage(n);
    setPageInput("");
  }, [pageInput, scrollToPage]);

  /* 缩放 */
  const zoomIn = useCallback(() => setScale((s) => Math.min(s + 0.2, 3)), []);
  const zoomOut = useCallback(() => setScale((s) => Math.max(s - 0.2, 0.5)), []);
  const zoomReset = useCallback(() => setScale(1.2), []);

  /* 全屏 */
  const toggleFullscreen = useCallback(() => {
    if (!isFullscreen) {
      containerRef.current?.requestFullscreen?.();
    } else {
      document.exitFullscreen?.();
    }
  }, [isFullscreen]);

  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", handler);
    return () => document.removeEventListener("fullscreenchange", handler);
  }, []);

  /* 键盘快捷键 */
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") { onClose(); return; }
      if ((e.key === "+" || e.key === "=") && (e.ctrlKey || e.metaKey)) { e.preventDefault(); zoomIn(); }
      if (e.key === "-" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); zoomOut(); }
      if (e.key === "0" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); zoomReset(); }
      if (e.key === "Home") { e.preventDefault(); scrollToPage(1); }
      if (e.key === "End") { e.preventDefault(); scrollToPage(numPages); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [numPages, scrollToPage, onClose, zoomIn, zoomOut, zoomReset]);

  /* 选中文本检测 */
  useEffect(() => {
    const handler = () => {
      const sel = window.getSelection()?.toString().trim();
      if (sel && sel.length > 2) {
        setSelectedText(sel);
      }
    };
    document.addEventListener("mouseup", handler);
    return () => document.removeEventListener("mouseup", handler);
  }, []);

  /* AI 操作 */
  const handleAiAction = useCallback(async (action: AiAction, text?: string) => {
    const t = text || selectedText;
    if (!t) return;
    setAiPanelOpen(true);
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

  /* 复制 AI 结果 */
  const handleCopy = useCallback((idx: number, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedIdx(idx);
    setTimeout(() => setCopiedIdx(null), 2000);
  }, []);

  /**
   * 注册页面 ref
   */
  const setPageRef = useCallback((page: number, el: HTMLDivElement | null) => {
    if (el) {
      pageRefs.current.set(page, el);
    } else {
      pageRefs.current.delete(page);
    }
  }, []);

  const actionLabels: Record<AiAction, { label: string; icon: React.ReactNode; color: string }> = {
    explain: { label: "AI 解释", icon: <Lightbulb className="h-3.5 w-3.5" />, color: "text-amber-600 bg-amber-50 dark:bg-amber-900/20" },
    translate: { label: "翻译", icon: <Languages className="h-3.5 w-3.5" />, color: "text-blue-600 bg-blue-50 dark:bg-blue-900/20" },
    summarize: { label: "总结", icon: <FileText className="h-3.5 w-3.5" />, color: "text-emerald-600 bg-emerald-50 dark:bg-emerald-900/20" },
  };

  /* 生成页码数组 */
  const pages = useMemo(() => Array.from({ length: numPages }, (_, i) => i + 1), [numPages]);

  return (
    <div
      ref={containerRef}
      className="fixed inset-0 z-50 flex bg-ink/95 backdrop-blur-sm"
      style={{ animationName: "fadeIn", animationDuration: "200ms" }}
    >
      {/* 顶部工具栏 */}
      <div className="absolute left-0 right-0 top-0 z-20 flex items-center justify-between border-b border-white/10 bg-[#1e1e2e]/95 px-4 py-2 backdrop-blur-md">
        {/* 左侧: 标题 */}
        <div className="flex min-w-0 items-center gap-3">
          <BookOpen className="h-5 w-5 shrink-0 text-primary" />
          <h2 className="truncate text-sm font-medium text-white/90">{paperTitle}</h2>
        </div>

        {/* 中间: 页码 & 缩放 */}
        <div className="flex items-center gap-1">
          <div className="flex items-center gap-1 rounded-md bg-white/10 px-2 py-1">
            <input
              type="text"
              value={pageInput || ""}
              onChange={(e) => setPageInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handlePageInputSubmit()}
              onBlur={handlePageInputSubmit}
              placeholder={String(currentPage)}
              className="w-8 bg-transparent text-center text-xs text-white/80 placeholder-white/40 outline-none"
            />
            <span className="text-xs text-white/40">/</span>
            <span className="text-xs text-white/60">{numPages}</span>
          </div>

          <div className="mx-2 h-4 w-px bg-white/10" />

          <button onClick={zoomOut} className="toolbar-btn" title="缩小 (Ctrl+-)">
            <ZoomOut className="h-4 w-4" />
          </button>
          <button onClick={zoomReset} className="toolbar-btn-text" title="重置缩放 (Ctrl+0)">
            {Math.round(scale * 100)}%
          </button>
          <button onClick={zoomIn} className="toolbar-btn" title="放大 (Ctrl++)">
            <ZoomIn className="h-4 w-4" />
          </button>

          <div className="mx-2 h-4 w-px bg-white/10" />

          <button onClick={toggleFullscreen} className="toolbar-btn" title="全屏">
            {isFullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </button>
        </div>

        {/* 右侧: AI 功能 & 关闭 */}
        <div className="flex items-center gap-1">
          {selectedText && (
            <div className="mr-2 flex items-center gap-1 rounded-full bg-white/10 px-2 py-1">
              <span className="max-w-[120px] truncate text-xs text-white/60">{selectedText}</span>
              <button onClick={() => handleAiAction("explain")} className="ai-action-btn bg-amber-500/20 text-amber-300 hover:bg-amber-500/30" title="AI 解释">
                <Lightbulb className="h-3 w-3" />
              </button>
              <button onClick={() => handleAiAction("translate")} className="ai-action-btn bg-blue-500/20 text-blue-300 hover:bg-blue-500/30" title="翻译">
                <Languages className="h-3 w-3" />
              </button>
              <button onClick={() => handleAiAction("summarize")} className="ai-action-btn bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30" title="总结">
                <FileText className="h-3 w-3" />
              </button>
            </div>
          )}
          <button
            onClick={() => setAiPanelOpen(!aiPanelOpen)}
            className={`toolbar-btn ${aiPanelOpen ? "bg-primary/30 text-primary" : ""}`}
            title="AI 助手面板"
          >
            <MessageSquareText className="h-4 w-4" />
          </button>
          <button onClick={onClose} className="toolbar-btn hover:bg-red-500/20 hover:text-red-300" title="关闭 (Esc)">
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* PDF 主体 - 连续滚动 */}
      <div
        ref={scrollRef}
        className="mt-12 flex-1 overflow-auto pb-10"
      >
        {loadError ? (
          <div className="flex h-full items-center justify-center">
            <div className="rounded-xl border border-red-500/20 bg-red-500/10 px-6 py-4 text-center">
              <p className="text-sm text-red-300">{loadError}</p>
              <button onClick={() => window.location.reload()} className="mt-2 text-xs text-red-400 underline hover:text-red-300">
                重新加载
              </button>
            </div>
          </div>
        ) : (
          <Document
            file={pdfUrl}
            onLoadSuccess={onDocumentLoadSuccess}
            onLoadError={onDocumentLoadError}
            loading={
              <div className="flex h-96 items-center justify-center">
                <div className="flex flex-col items-center gap-3">
                  <Loader2 className="h-8 w-8 animate-spin text-primary" />
                  <span className="text-sm text-white/60">加载 PDF 中...</span>
                </div>
              </div>
            }
          >
            <div className="flex flex-col items-center gap-4 py-6">
              {pages.map((pg) => {
                const isNearby = Math.abs(pg - currentPage) <= 3;
                return (
                <div
                  key={pg}
                  ref={(el) => setPageRef(pg, el)}
                  data-page={pg}
                  className="relative"
                  style={!isNearby ? { minHeight: `${Math.round(792 * scale)}px`, width: `${Math.round(612 * scale)}px` } : undefined}
                >
                  <div className="absolute -top-0 left-1/2 z-10 -translate-x-1/2 -translate-y-full pb-1">
                    <span className="rounded-full bg-white/10 px-2.5 py-0.5 text-[10px] text-white/30">
                      {pg}
                    </span>
                  </div>
                  {isNearby ? (
                  <Page
                    pageNumber={pg}
                    scale={scale}
                    className="pdf-page-shadow"
                    loading={
                      <div
                        className="flex items-center justify-center bg-white/5"
                        style={{ width: 595 * scale, height: 842 * scale }}
                      >
                        <Loader2 className="h-6 w-6 animate-spin text-white/20" />
                      </div>
                    }
                  />
                  ) : (
                    <div
                      className="flex items-center justify-center bg-white/5 rounded"
                      style={{ width: Math.round(612 * scale), height: Math.round(792 * scale) }}
                    />
                  )}
                </div>
                );
              })}
            </div>
          </Document>
        )}
      </div>

      {/* 底部进度条 */}
      {numPages > 0 && (
        <div
          className="absolute bottom-0 left-0 z-20 flex items-center justify-center gap-3 border-t border-white/10 bg-[#1e1e2e]/90 px-4 py-2 backdrop-blur-md"
          style={{ right: aiPanelOpen ? "384px" : "0" }}
        >
          <div className="h-1 flex-1 max-w-md overflow-hidden rounded-full bg-white/10">
            <div
              className="h-full rounded-full bg-primary/60 transition-all duration-300"
              style={{ width: `${(currentPage / numPages) * 100}%` }}
            />
          </div>
          <span className="text-xs text-white/40">
            第 {currentPage} / {numPages} 页
          </span>
        </div>
      )}

      {/* AI 侧边栏 */}
      <div
        className={`relative mt-12 border-l border-white/10 bg-[#1e1e2e] transition-all duration-300 ${
          aiPanelOpen ? "w-96" : "w-0"
        } overflow-hidden`}
      >
        <div className="flex h-full w-96 flex-col">
          {/* AI 面板头部 */}
          <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              <span className="text-sm font-medium text-white/90">AI 阅读助手</span>
            </div>
            <button
              onClick={() => setAiResults([])}
              className="text-xs text-white/40 hover:text-white/60"
              title="清空记录"
            >
              <RotateCw className="h-3.5 w-3.5" />
            </button>
          </div>

          {/* 快捷 AI 操作 */}
          {selectedText && (
            <div className="border-b border-white/10 px-4 py-3">
              <p className="mb-2 text-xs text-white/40">选中文本</p>
              <p className="mb-3 line-clamp-3 rounded-md bg-white/5 p-2 text-xs leading-relaxed text-white/70">{selectedText}</p>
              <div className="flex gap-2">
                <button
                  onClick={() => handleAiAction("explain")}
                  disabled={aiLoading}
                  className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-amber-500/10 py-1.5 text-xs text-amber-300 transition-colors hover:bg-amber-500/20 disabled:opacity-50"
                >
                  <Lightbulb className="h-3.5 w-3.5" /> 解释
                </button>
                <button
                  onClick={() => handleAiAction("translate")}
                  disabled={aiLoading}
                  className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-blue-500/10 py-1.5 text-xs text-blue-300 transition-colors hover:bg-blue-500/20 disabled:opacity-50"
                >
                  <Languages className="h-3.5 w-3.5" /> 翻译
                </button>
                <button
                  onClick={() => handleAiAction("summarize")}
                  disabled={aiLoading}
                  className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-emerald-500/10 py-1.5 text-xs text-emerald-300 transition-colors hover:bg-emerald-500/20 disabled:opacity-50"
                >
                  <FileText className="h-3.5 w-3.5" /> 总结
                </button>
              </div>
            </div>
          )}

          {/* AI 结果列表 */}
          <div className="flex-1 overflow-auto px-4 py-3">
            {aiLoading && (
              <div className="mb-4 flex items-center gap-2 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2">
                <Loader2 className="h-4 w-4 animate-spin text-primary" />
                <span className="text-xs text-primary">AI 分析中...</span>
              </div>
            )}

            {aiResults.length === 0 && !aiLoading && (
              <div className="flex flex-col items-center gap-3 pt-12 text-center">
                <MessageSquareText className="h-10 w-10 text-white/10" />
                <div>
                  <p className="text-sm text-white/40">选中论文文本</p>
                  <p className="mt-1 text-xs text-white/20">即可使用 AI 解释、翻译、总结</p>
                </div>
                <div className="mt-4 space-y-1.5 text-left text-xs text-white/20">
                  <p>快捷键：</p>
                  <p>Ctrl +/- 缩放 &nbsp; Ctrl+0 重置</p>
                  <p>Home/End 首/末页 &nbsp; Esc 关闭</p>
                  <p>鼠标滚轮自由滚动阅读</p>
                </div>
              </div>
            )}

            {aiResults.map((r, i) => {
              const cfg = actionLabels[r.action];
              return (
                <div
                  key={i}
                  className="mb-4 overflow-hidden rounded-xl border border-white/[.08] bg-gradient-to-b from-white/[.04] to-white/[.02]"
                >
                  {/* 卡片头部 */}
                  <div className="flex items-center justify-between border-b border-white/[.06] px-3.5 py-2">
                    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium ${cfg.color}`}>
                      {cfg.icon} {cfg.label}
                    </span>
                    <button
                      onClick={() => handleCopy(i, r.result)}
                      className="rounded-md p-1 text-white/20 transition-colors hover:bg-white/10 hover:text-white/50"
                      title="复制内容"
                    >
                      {copiedIdx === i ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                  {/* 原文引用 */}
                  <div className="border-b border-white/[.04] px-3.5 py-2">
                    <p className="line-clamp-2 border-l-2 border-white/10 pl-2.5 text-[11px] leading-relaxed text-white/30 italic">
                      {r.text}
                    </p>
                  </div>
                  {/* AI 输出 - Markdown 渲染 */}
                  <div className="px-3.5 py-3">
                    <Markdown className="pdf-ai-markdown">{r.result}</Markdown>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
