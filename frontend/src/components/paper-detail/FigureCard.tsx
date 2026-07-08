import { useState, lazy, Suspense } from "react";
import { ImageIcon, ChevronDown, ChevronRight, X, Sparkles } from "lucide-react";
import { paperApi } from "@/services/api";
import type { FigureAnalysisItem } from "@/types";
import { TYPE_ICONS, TYPE_LABELS } from "./figureTypeMeta";

// 重型依赖懒加载，只在真正需要时加载
const Markdown = lazy(() => import("@/components/Markdown"));

/* ================================================================
 * 图表解读卡片
 * ================================================================ */

function FigureCard({
  figure,
  index,
  paperId,
}: {
  figure: FigureAnalysisItem;
  index: number;
  paperId: string;
}) {
  const [expanded, setExpanded] = useState(index < 3);
  const [lightbox, setLightbox] = useState(false);
  const imgUrl = figure.image_url && figure.id ? paperApi.figureImageUrl(paperId, figure.id) : null;

  return (
    <>
      <div className="border-border bg-surface/50 hover:border-border/80 overflow-hidden rounded-xl border transition-all">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex w-full items-center gap-3 px-4 py-3 text-left"
        >
          <div className="bg-page flex h-8 w-8 shrink-0 items-center justify-center rounded-lg">
            {TYPE_ICONS[figure.image_type] || TYPE_ICONS.figure}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-blue-500/10 px-2 py-0.5 text-[10px] font-medium text-blue-600 dark:text-blue-400">
                {TYPE_LABELS[figure.image_type] || figure.image_type}
              </span>
              <span className="text-ink-tertiary text-[10px]">第 {figure.page_number} 页</span>
            </div>
            {figure.caption && (
              <p className="text-ink mt-0.5 truncate text-xs font-medium">{figure.caption}</p>
            )}
          </div>
          {expanded ? (
            <ChevronDown className="text-ink-tertiary h-4 w-4 shrink-0" />
          ) : (
            <ChevronRight className="text-ink-tertiary h-4 w-4 shrink-0" />
          )}
        </button>

        {expanded && (
          <div className="border-border border-t">
            {/* 原图展示区 */}
            {imgUrl ? (
              <div className="bg-page/50 flex justify-center p-4 dark:bg-black/20">
                <img
                  src={imgUrl}
                  alt={figure.caption || `Figure on page ${figure.page_number}`}
                  className="max-h-[400px] max-w-full cursor-zoom-in rounded-lg object-contain shadow-sm transition-transform hover:scale-[1.02]"
                  onClick={(e) => {
                    e.stopPropagation();
                    setLightbox(true);
                  }}
                  loading="lazy"
                />
              </div>
            ) : (
              <div className="bg-page/30 text-ink-tertiary flex items-center justify-center px-4 py-6 text-xs">
                <ImageIcon className="mr-1.5 h-4 w-4" /> 原图未提取（旧版分析结果）
              </div>
            )}

            {/* AI 解读区 */}
            <div className="border-border/50 border-t px-4 py-3">
              <div className="text-primary/70 mb-1.5 flex items-center gap-1.5 text-[10px] font-medium tracking-wide uppercase">
                <Sparkles className="h-3 w-3" /> AI 解读
              </div>
              <div className="prose prose-sm text-ink-secondary dark:prose-invert max-w-none">
                <Suspense fallback={<div className="bg-surface h-8 animate-pulse rounded" />}>
                  <Markdown>{figure.description}</Markdown>
                </Suspense>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 图片灯箱 */}
      {lightbox && imgUrl && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
          onClick={() => setLightbox(false)}
        >
          <button
            className="absolute top-4 right-4 rounded-full bg-white/10 p-2 text-white transition-colors hover:bg-white/20"
            onClick={() => setLightbox(false)}
          >
            <X className="h-5 w-5" />
          </button>
          <img
            src={imgUrl}
            alt={figure.caption || ""}
            className="max-h-[90vh] max-w-[90vw] rounded-lg object-contain shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          />
          {figure.caption && (
            <div className="absolute bottom-6 left-1/2 max-w-xl -translate-x-1/2 rounded-lg bg-black/60 px-4 py-2 text-center text-sm text-white/90">
              {figure.caption}
            </div>
          )}
        </div>
      )}
    </>
  );
}

export default FigureCard;
