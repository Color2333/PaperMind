import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url
).href;

interface Segment {
  id: string;
  type: string;
  content: string;
  translation?: string;
  pageNumber?: number;
}

interface TranslationPanelProps {
  selectedText: string;
  paperId: string;
  paperArxivId?: string;
  paperPdfPath?: string | null;
}

type ViewMode = 'selection' | 'bilingual';

export function TranslationPanel({ selectedText, paperId, paperArxivId, paperPdfPath }: TranslationPanelProps) {
  const [viewMode, setViewMode] = useState<ViewMode>('selection');
  const [segments, setSegments] = useState<Segment[]>([]);
  const [translating, setTranslating] = useState(false);
  const [numPages, setNumPages] = useState(0);
  const [currentPdfPage, setCurrentPdfPage] = useState(1);

  const leftScrollRef = useRef<HTMLDivElement>(null);
  const rightScrollRef = useRef<HTMLDivElement>(null);

  const [containerWidth, setContainerWidth] = useState(400);
  const scale = useMemo(() => {
    return (containerWidth - 40) / 612;
  }, [containerWidth]);

  const handleLeftScroll = useCallback(() => {
    if (!leftScrollRef.current) return;

    const scrollTop = leftScrollRef.current.scrollTop;
    const pageHeight = 842 * scale + 16 * scale;
    const estimatedPage = Math.floor(scrollTop / pageHeight) + 1;
    const newPage = Math.max(1, Math.min(estimatedPage, numPages));

    if (newPage !== currentPdfPage) {
      setCurrentPdfPage(newPage);
    }

    const targetPageAnchor = document.querySelector(`[data-trans-page="${newPage}"]`);
    if (targetPageAnchor && rightScrollRef.current) {
      const rightRect = rightScrollRef.current.getBoundingClientRect();
      const anchorRect = targetPageAnchor.getBoundingClientRect();
      const offsetTop = anchorRect.top + rightScrollRef.current.scrollTop - rightRect.top - 20;
      rightScrollRef.current.scrollTo({ top: offsetTop, behavior: 'smooth' });
    }
  }, [scale, numPages, currentPdfPage]);

  const scrollPdfToPage = useCallback((pageNum: number) => {
    const pageEl = document.querySelector(`[data-page="${pageNum}"]`);
    if (pageEl && leftScrollRef.current) {
      pageEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, []);

  const handleTranslateFull = useCallback(async () => {
    if (segments.length > 0) {
      setViewMode('bilingual');
      return;
    }

    setTranslating(true);
    try {
      const base = import.meta.env.VITE_API_BASE || 'http://localhost:8000';
      const token = localStorage.getItem('auth_token') || '';

      const segRes = await fetch(`${base}/papers/${paperId}/segments`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!segRes.ok) {
        const data = await segRes.json();
        if (data.detail?.includes('没有 PDF') || data.detail?.includes('PDF 文件不存在')) {
          alert('请先下载 PDF');
        }
        return;
      }

      const segData = await segRes.json();
      const rawSegments = segData.segments || [];
      setSegments(rawSegments);

      const transRes = await fetch(`${base}/translate/segments`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ segments: rawSegments, target_lang: 'zh' }),
      });

      if (transRes.ok) {
        const transData = await transRes.json();
        setSegments(transData.segments || []);
      }

      setViewMode('bilingual');
    } catch (err) {
      console.error('Failed to translate:', err);
    } finally {
      setTranslating(false);
    }
  }, [paperId, segments.length]);

  const onDocumentLoadSuccess = useCallback(({ numPages: n }: { numPages: number }) => {
    setNumPages(n);
  }, []);

  useEffect(() => {
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerWidth(entry.contentRect.width);
      }
    });

    if (leftScrollRef.current) {
      observer.observe(leftScrollRef.current);
    }

    return () => observer.disconnect();
  }, []);

  const pdfUrl = useMemo(() => {
    const token = localStorage.getItem('auth_token') || '';
    const tokenParam = token ? `?token=${encodeURIComponent(token)}` : '';
    const base = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

    if (paperPdfPath) {
      return `${base}/papers/${paperId}/pdf${tokenParam}`;
    }
    if (paperArxivId && !paperArxivId.startsWith('ss-')) {
      return `${base}/papers/proxy-arxiv-pdf/${paperArxivId}${tokenParam}`;
    }
    return `${base}/papers/${paperId}/pdf${tokenParam}`;
  }, [paperId, paperArxivId, paperPdfPath]);

  return (
    <div className="flex h-full flex-col">
      {/* Tab 切换 */}
      <div className="flex gap-2 border-b border-white/10 px-4 py-2">
        <button
          type="button"
          onClick={() => setViewMode('selection')}
          className={`text-xs ${viewMode === 'selection' ? 'text-primary' : 'text-white/40'}`}
        >
          划词翻译
        </button>
        <button
          type="button"
          onClick={handleTranslateFull}
          className={`text-xs flex items-center gap-1 ${viewMode === 'bilingual' ? 'text-primary' : 'text-white/40'}`}
        >
          全文对照
        </button>
      </div>

      {/* 划词翻译模式 */}
      {viewMode === 'selection' && (
        <div className="flex-1 overflow-auto p-4">
          {selectedText ? (
            <div className="rounded-lg border border-white/10 bg-white/5 p-3">
              <p className="text-xs text-white/40 mb-2">选中文本</p>
              <p className="text-sm text-white/80">{selectedText}</p>
            </div>
          ) : (
            <p className="text-sm text-white/40 text-center py-8">
              在左侧 PDF 中选中文本即可翻译
            </p>
          )}
        </div>
      )}

      {/* 双语对照模式 - 左右分栏 */}
      {viewMode === 'bilingual' && (
        <div className="flex flex-1 overflow-hidden">
          {/* 左侧: PDF */}
          <div
            ref={leftScrollRef}
            onScroll={handleLeftScroll}
            className="flex-1 overflow-auto border-r border-white/10"
          >
            <Document
              file={pdfUrl}
              onLoadSuccess={onDocumentLoadSuccess}
              loading={
                <div className="flex items-center justify-center p-8">
                  <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                </div>
              }
            >
              <div className="flex flex-col items-center gap-4 p-4">
                {Array.from(new Array(numPages), (_, i) => i + 1).map((page) => (
                  <div key={page} data-page={page} className="relative">
                    <Page
                      pageNumber={page}
                      scale={scale}
                      className="shadow-lg"
                      loading={
                        <div
                          className="flex items-center justify-center bg-white/5"
                          style={{ width: 612 * scale, height: 842 * scale }}
                        >
                          <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                        </div>
                      }
                    />
                  </div>
                ))}
              </div>
            </Document>
          </div>

          {/* 右侧: 翻译 */}
          <div
            ref={rightScrollRef}
            className="w-full overflow-auto bg-[#1a1a2e]"
          >
            <div className="p-4">
              <h3 className="text-sm font-medium text-white/80 mb-4">译文对照</h3>
              {segments.length === 0 && !translating && (
                <p className="text-xs text-white/40">正在加载翻译...</p>
              )}
              {translating && segments.length === 0 && (
                <div className="flex items-center gap-2">
                  <div className="h-4 w-4 animate-spin rounded-full border border-primary border-t-transparent" />
                  <span className="text-xs text-primary">翻译中...</span>
                </div>
              )}
              {segments.map((seg, idx) => (
                <button
                  type="button"
                  key={seg.id || idx}
                  data-trans-page={seg.pageNumber}
                  className="mb-6 w-full cursor-pointer rounded-lg p-2 text-left hover:bg-white/5 transition-colors"
                  onClick={() => seg.pageNumber && scrollPdfToPage(seg.pageNumber)}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-primary/60">P{seg.pageNumber}</span>
                    <span className="text-xs text-white/20">点击跳转</span>
                  </div>
                  <p className="text-sm text-white/70 leading-relaxed mb-3">{seg.content}</p>
                  {seg.translation && (
                    <div className="border-l-2 border-primary/40 pl-3">
                      <p className="text-xs text-primary/60 mb-1">译文</p>
                      <p className="text-sm text-primary/90 leading-relaxed">{seg.translation}</p>
                    </div>
                  )}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
