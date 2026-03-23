/**
 * PDF Reader - 沉浸式论文阅读器（连续滚动 + AI 功能）
 * @author Color2333
 */
import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { paperApi } from "@/services/api";
import { ToolPanel } from "./ToolPanel/ToolPanel";
import { TranslationPanel } from "./ToolPanel/TranslationPanel";
import { AggregationPanel } from "./ToolPanel/AggregationPanel";
import { CanvasPanel } from "./ToolPanel/CanvasPanel";
import {
  X,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Minimize2,
  BookOpen,
  Loader2,
} from "lucide-react";

pdfjs.GlobalWorkerOptions.workerSrc = `https://cdn.jsdelivr.net/npm/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

interface PdfReaderProps {
  paperId: string;
  paperTitle: string;
  paperArxivId?: string;  // arXiv ID（用于在线链接）
  paperPdfPath?: string | null;  // 本地 PDF 路径
  onClose: () => void;
}

export default function PdfReader({ paperId, paperTitle, paperArxivId, paperPdfPath, onClose }: PdfReaderProps) {
  const [numPages, setNumPages] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [scale, setScale] = useState(1.2);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  /* AI 侧栏 */
  const [selectedText, setSelectedText] = useState("");

  /* 页面输入 */
  const [pageInput, setPageInput] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  // 优先本地 PDF，没有则用 arXiv 在线代理
  const pdfUrl = useMemo(() => {
    // 有本地 PDF 优先使用
    if (paperPdfPath) {
      const token = localStorage.getItem('auth_token') || '';
      return `/papers/${paperId}/pdf${token ? `?token=${encodeURIComponent(token)}` : ''}`;
    }
    // 没有本地 PDF 但有 arXiv ID，用在线代理
    if (paperArxivId && !paperArxivId.startsWith('ss-')) {
      const token = localStorage.getItem('auth_token') || '';
      return `/papers/proxy-arxiv-pdf/${paperArxivId}${token ? `?token=${encodeURIComponent(token)}` : ''}`;
    }
    // 最后尝试本地 PDF 端点
    const token = localStorage.getItem('auth_token') || '';
    return `/papers/${paperId}/pdf${token ? `?token=${encodeURIComponent(token)}` : ''}`;
  }, [paperId, paperArxivId, paperPdfPath]);

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

        {/* 右侧: 关闭 */}
        <div className="flex items-center gap-1">
          <button onClick={onClose} className="toolbar-btn hover:bg-red-500/20 hover:text-red-300" title="关闭 (Esc)">
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* PDF 主体 - 连续滚动 - 左半屏 */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-auto pb-10"
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
          style={{ right: "50%" }}
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

      {/* 右侧面板 - 右半屏 */}
      <div className="flex w-1/2 shrink-0">
        <ToolPanel selectedText={selectedText} paperId={paperId}>
          {{
            translation: <TranslationPanel selectedText={selectedText} paperId={paperId} />,
            aggregation: <AggregationPanel selectedText={selectedText} paperId={paperId} />,
            canvas: <CanvasPanel paperId={paperId} paperTitle={paperTitle} />,
          }}
        </ToolPanel>
      </div>
    </div>
  );
}
